# PAM registry — design

**Status:** design, for review. Design before code — this PR adds no executable code.
**Answers:** [`BRIEF-registry.md`](../BRIEF-registry.md) (Mek's direction, 2026-10-02), as routed by Ada.
**Scope of this unit:** the SQLite schema (stable-id decision made), the PAM/cmux authority
boundary, the command surface, and the migration plan for the live fleet. **Does not** modify cmux
and **does not** touch any live agent's directory.

---

## TL;DR

- PAM is a standalone, SQLite-backed registry of **projects → repos → workspaces → agents**, plus
  parentage, staffing, assignment, and asserted phase. It is the durable identity-and-policy layer.
- cmux already ships a correct SQLite registry (`~/.cmux/agents.db`, WAL, per-key upsert) running
  beside a racy JSON one (`sessions.json`). **PAM is the generalization of `agents.db`, promoted to
  the single authority; the `sessions.json` read-modify-write is retired.** This is not greenfield.
- The one hard invariant: **`pip install pam && pam project add …` works on a machine with no
  tmux.** PAM never imports cmux. cmux imports PAM. A test asserts this and stays green.
- **Stable agent id (ULID), separate from the reusable display name.** The id is the primary key;
  the name is a label. A reused name can never merge two agents' histories — enforced in the schema
  by a partial-unique index, and owned at the resolution seam by PAM.
- **Authored state** (project/team definition, roster, capability bindings, doc chain) stays as
  files in the project repo, read at call time, **never cached.** Only **recorded state** (who
  exists, parentage, staffing, assignment, last phase, resume coordinates) lives in SQLite.
- Migration does **not** move a running agent's directory. New agents live in PAM-land; the 39 live
  agents are linked in place and converted by attrition.

---

## 1. Context — why this exists

cmux grew a hardcoded role dict (`cmux_lib/cli.py:18-35`, `KNOWN_AGENTS`) that rotted to 3-of-14
live: it still says `workspace: 'ol-loop'` for agents that moved to `ol-leads`, and it is the only
source of role text because `sessions.json` has no `role` field at all. That is the failure mode
PAM exists to prevent: **a cache of authored facts drifts from the files that define them.** The fix
is not a better cache — it is to stop caching the authored half and read it at call time.

Two registries already coexist in cmux and disagree by construction:

| | `~/.cmux/sessions.json` | `~/.cmux/agents.db` (`cmux_lib/db.py`) |
|---|---|---|
| shape | JSON dict keyed by `name` | SQLite, `agents` table, PK `name` |
| writes | full-file **read-modify-write, no lock** | WAL + `INSERT … ON CONFLICT(name) DO UPDATE` |
| failure | lost updates under concurrent writers (the 2026-07-23 wipe scar tissue is in the load/save guards) | serialized per-key writes, no lost updates |
| rows | 39 (currently running) | 96 (every agent ever started) |
| treated as | recreatable cache (`_ensure_alive` rebuilds tmux from the DB) | durable source |

With ~39 agents that can each `cmux send` one another — and `cmux send → _ensure_alive → cmd_start`
means *sending a message* can trigger a full registry rewrite — the JSON read-modify-write window is
contended, and last-writer-wins silently drops changes. `agents.db` already does it right. **PAM's
job is to promote that model to the single authority and retire the JSON RMW**, while adding the
identity, hierarchy, and policy that neither store has today.

## 2. Scope and non-goals

**In scope (this design):** the schema, the authority boundary, the command surface, the migration
plan, the no-import invariant and its test.

**Out of scope for this unit (design-only; no code, no cmux edits, no live-dir touches):**

- Implementing the `pam` package. This PR is the design.
- Modifying cmux to read/write PAM. That is a later, separate PR against `~/Projects/cmux`. This
  design names the seam; it does not cut it.
- The event loops / scheduler (`docs/event-loops.md`, PR #1) and the heartbeat lifecycle
  (`heartbeat/`, PR #2). PAM is the registry those sit on; this design stays in its lane.
- **Message transport.** `claudio` owns live delivery over unix sockets (only `cmux_lib/daemon.py`
  imports it). PAM owns the *stored* received-message ledger (files in the agent home); it does not
  deliver messages.
- **The `tasks` table** in `agents.db` (9 rows, legacy, superseded by `cq`). PAM does **not** adopt
  task tracking in v1 — that is `cq`'s domain. Named here so it is not left unassigned between the
  layers the way sockets-vs-identity was; if PAM ever records staffing-to-work it does so through
  the `assignments` table (§5), not by resurrecting `tasks`.

## 3. Authored vs recorded — the line we do not cross

| | Authored (files in the project repo) | Recorded (SQLite in `~/.pam/`) |
|---|---|---|
| examples | project/team definition, team roster, capability bindings, doc chain, an agent's `identity.md` | which agents exist, parentage, who staffed whom and when, current assignment, last known phase, resume coordinates |
| read | at call time, **never cached** | queried directly |
| why | this is the half whose cache rotted; files are the source of truth | 38 concurrent writers race a JSON RMW — needs serialized per-key writes |

The rule: **PAM never caches the authored half.** When a command needs a roster or a capability
binding, it reads the file in the repo at that moment. SQLite holds only facts PAM itself asserts.

## 4. The PAM/cmux authority boundary

```
                 AUTHORED (repo files)          RECORDED (PAM, ~/.pam/)        EPHEMERAL (cmux)
 project/team    definition, roster,            projects, repos, teams,        —
                 capability bindings, docs       workspaces (pointers only)
 agent           identity.md                     id, name, parentage, role      socket, daemon pid,
                                                  hint, cwd, last-session-id,    tmux target, started-ts,
                                                  assignment, asserted phase     daemon log, msg archive*
 resume          —                               (session-id, cwd) pair         the act of `claude --resume`
 messaging       —                               stored ledger (files)*         transport (claudio sockets)
```

\* The msg archive / received-message ledger are durable **files in the agent home**, which lives in
PAM-land (`~/.pam/agents/<id>/`). PAM owns the directory; claudio/cmux deliver into it.

**PAM owns** (durable identity + policy + resume coordinates): the `agents.db` identity columns
generalized — `name`, `role` (a recorded *hint*; the authoritative role is authored), `workspace`,
`no_inject`, `unblock`, `allowed_tools`, `identity_path` — **plus** the stable `id`, the
project/repo/workspace hierarchy, parentage, staffing, assignment, asserted phase, and the two
durable facts currently stranded as loose files in the home dir: **`cwd` and `last-session-id`**.

**cmux keeps** the pure-runtime layer, all of it reconstructable from `(name, workspace, cwd)` on
the next `cmux up`: the unix socket, the daemon pid, the tmux session/window/target (pure functions
of `name` + `workspace` via `_tmux_session`/`_tmux_target`), the boot `started` timestamp, the
daemon log. None of this belongs in the authoritative registry.

**The act of resuming stays with cmux/the harness.** PAM *stores* everything a resume needs
(`last_session_id` + the original `cwd` — Claude Code scopes sessions by cwd via
`~/.claude/projects/<slug>`, so the pair is inseparable). PAM never runs `claude --resume` and never
shells out to a terminal multiplexer. If it did, it would need tmux and break the invariant below.
This is the concrete meaning of "an agent must be resumable with no cmux": the *facts* are all in
PAM; the *mechanism* is cmux's.

### 4.1 The invariant that keeps the layers from re-merging

**`pip install pam && pam project add …` must work on a machine with no tmux.** PAM imports nothing
from cmux. cmux may import PAM (cmux uses PAM, never the reverse). A test asserts it and stays green:

```python
# tests/test_no_cmux_import.py (design intent)
def test_pam_never_imports_cmux():
    import sys, pam                     # importing the whole package…
    assert not any(m == "cmux" or m.startswith("cmux_lib")
                   for m in sys.modules)          # …pulls in no cmux
    # plus a source scan: no `import cmux` / `from cmux_lib` anywhere under pam/
```

Operator scripts that *do* need tmux (e.g. `whereis.sh`, §9) ship as standalone executables, not as
imports of the `pam` package — the core import path stays tmux-free.

## 5. SQLite schema

`~/.pam/pam.db`, `PRAGMA journal_mode=WAL` (the property that made `agents.db` safe for concurrent
readers + serialized writers). All ids are **ULIDs** (see §6). Timestamps are ISO-8601 UTC strings,
matching cmux's `started` format. Writes are per-key upserts, never full-table rewrites.

```sql
-- A project is POINTERS ONLY. Everything substantive is authored and read from files at call time.
CREATE TABLE projects (
    id          TEXT PRIMARY KEY,          -- ULID
    name        TEXT NOT NULL UNIQUE,      -- e.g. "openlibrary"
    framework   TEXT,                      -- e.g. "ada"; NULL for a project with no pipeline
    created_at  TEXT NOT NULL
);

-- A project owns SEVERAL repos. Each repo is a first-class row with its OWN origin and default
-- branch — NOT an alias of a primary. Open Library spans openlibrary + openlibrary-i18n + olsystem
-- + ol-kb + the demo repo, whose default branches differ (master vs main); collapsing them to one
-- canonical repo already caused a silent wrong-base branch.
CREATE TABLE repos (
    id             TEXT PRIMARY KEY,       -- ULID
    project_id     TEXT NOT NULL REFERENCES projects(id),
    name           TEXT NOT NULL,          -- e.g. "openlibrary-i18n"
    repo_url       TEXT NOT NULL,          -- canonical remote (owner/name or URL)
    path           TEXT NOT NULL,          -- local checkout — the BOUND PATH (requirement #3)
    origin         TEXT NOT NULL,          -- expected `origin` remote; verified at add, re-checked at spawn
    default_branch TEXT NOT NULL,          -- "master" | "main" — first-class, never inferred
    created_at     TEXT NOT NULL,
    UNIQUE(project_id, name)
);

-- Teams: PAM records that a team exists and belongs to a project. The team ROSTER is AUTHORED
-- (a file in the repo) and read at call time — PAM does not cache membership here.
CREATE TABLE teams (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id),
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(project_id, name)
);

-- project → workspaces → agents. A workspace is a cmux grouping (e.g. "ol-prs", "ol-leads").
CREATE TABLE workspaces (
    id          TEXT PRIMARY KEY,
    project_id  TEXT REFERENCES projects(id),   -- NULL allowed (standalone grouping)
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(project_id, name)
);

-- The core recorded identity. Generalizes cmux agents.db, adding the stable id + hierarchy.
CREATE TABLE agents (
    id              TEXT PRIMARY KEY,      -- ULID — THE stable id, minted once, immutable
    name            TEXT NOT NULL,         -- display label, REUSABLE over time, not unique across history
    project_id      TEXT REFERENCES projects(id),   -- NULL for a personal agent (e.g. a tutor)
    workspace_id    TEXT REFERENCES workspaces(id),
    team_id         TEXT REFERENCES teams(id),
    parent_id       TEXT REFERENCES agents(id),      -- parentage: who spawned this agent
    role            TEXT,                  -- recorded HINT; authoritative role is authored
    cwd             TEXT,                  -- durable: dir the session was started in (resume needs it)
    last_session_id TEXT,                  -- durable: `claude --resume <uuid>`
    identity_path   TEXT,                  -- pointer to the agent's home/definition (see §7)
    home_path       TEXT,                  -- ~/.pam/agents/<id>/  (or legacy symlink target)
    no_inject       INTEGER NOT NULL DEFAULT 0,
    unblock         INTEGER NOT NULL DEFAULT 0,
    allowed_tools   TEXT,
    status          TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'retired'
    created_at      TEXT NOT NULL,
    retired_at      TEXT
);

-- THE no-merge guarantee, in the schema: at most one ACTIVE agent per name at a time. History is
-- preserved because retired rows keep their id and their resume coordinates. (cmux today has only
-- ON CONFLICT(name) — name IS the key — which is exactly why a reused name can clobber a history.)
CREATE UNIQUE INDEX idx_one_active_agent_per_name ON agents(name) WHERE status = 'active';

-- Staffing + current assignment (who was put on what, by whom, when). This is where staffing-to-work
-- lives if PAM ever records it — NOT the legacy `tasks` table.
CREATE TABLE assignments (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL REFERENCES agents(id),
    repo_id     TEXT REFERENCES repos(id),    -- which $REPO of the project
    issue       INTEGER,
    pr          INTEGER,
    staffed_by  TEXT REFERENCES agents(id),   -- who staffed whom
    staffed_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    released_at TEXT
);

-- Asserted phase (requirement #4): status + the commit it was asserted against + WHEN. Staleness is
-- computed at READ time against live HEAD — never stored, never allowed to go stale silently.
CREATE TABLE phase_assertions (
    id            TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL REFERENCES agents(id),
    assignment_id TEXT REFERENCES assignments(id),
    repo_id       TEXT REFERENCES repos(id),  -- whose HEAD to compare against
    phase         TEXT NOT NULL,              -- reuse the heartbeat taxonomy vocabulary (see §8)
    asserted_sha  TEXT,                        -- commit the assertion was made against; NULL = a
                                               -- requirement, not a finding → never "stale"
    asserted_at   TEXT NOT NULL,               -- NET-NEW vs where_are_we.py (see §8); brief #4 wants it
    evidence      TEXT,                        -- optional; a terminal phase with no evidence is "asserted"
    created_at    TEXT NOT NULL
);
```

Notes:

- **No roster/capability table.** Those are authored. Modeling them here would rebuild the cache
  that rotted.
- **`cwd` and `last_session_id` are columns *and* files.** PAM is authoritative; it also writes the
  files into the agent home so cmux's existing name-keyed read path keeps working during migration
  (a compatibility shim, §7).
- **cmux's migrations append columns out of declaration order** (`db.py:57-66` ALTERed
  `unblock`/`allowed_tools`/`identity_path` in later). PAM's reader must select by column name, not
  position — and PAM's own migrations follow the same additive, never-reorder discipline.

## 6. The stable-id decision

**Decision: the agent id is a ULID, minted once at registration, immutable, and the primary key.
The display name is a mutable, reusable label.**

- **Why not name as PK (the status quo):** cmux uses `name` as the key in *both* stores, and
  `last-session-id` is a *name-keyed file on disk*. Reusing a name therefore points a new agent at
  the previous occupant's resume coordinates — the exact history-merge the brief forbids. The hazard
  is in the schema, not hypothetical.
- **Why ULID, not uuid4:** lexicographically sortable by creation time, so "the current agent for a
  reused name" and "the most recent of a name's history" are trivial ordered queries; collision-free
  without coordination; no dependency on the name. (uuid4 would work but loses the ordering that the
  name-reuse and attrition flows want.) ULID generation is a few lines of stdlib (`os.urandom` +
  time) — no third-party dependency, keeping the install light and the no-tmux invariant trivially
  true.
- **How histories stay separate:** the partial-unique index guarantees one *active* row per name;
  retiring an agent (name reuse, or attrition) frees the name while the old row keeps its id and its
  `(last_session_id, cwd)`. Two agents that shared a name over time remain two rows, two histories.

## 7. Agent directories and the name→id resolution seam (section D)

### 7.1 Home directory

`~/.pam/agents/<id>/` is the durable home. It holds the files split to PAM by lifetime: `identity.md`,
the brief / initial prompt, `.cq/` (the agent's own cq db — a separate subsystem PAM hosts but does
not own), received messages (`msg-*.md`), notes, ledger, `cwd`, `last-session-id`. The ephemeral
peers (socket, daemon pid/log, tmux target) stay beside it on the cmux side, exactly where they are
today — they are not inside the home dir now and do not move.

### 7.2 The resolution seam — who owns name → id

Today `cmux up <name>` resumes a stored session **by name**: it reads `~/.cmux/<name>/last-session-id`
and runs `claude --resume <uuid>` in the recorded cwd. There is no id. If PAM mints ids but cmux
keeps addressing by name, the translation happens *somewhere* — and an unlabelled seam there is
precisely how a reused name silently resumes the wrong agent's session.

**PAM owns name→id resolution, because PAM owns the outcome (no merged histories).** The contract:

> `pam resolve <name>` → the **active** agent's `id` and its `(last_session_id, cwd)`.

cmux's resume path asks PAM to resolve a name instead of trusting a name-keyed file. Until cmux is
changed (a later PR), PAM keeps the name-keyed `last-session-id` file in the home dir in sync with
the active row, so the existing cmux read path resolves to the right session by construction. The
seam is named, and it belongs to PAM.

### 7.3 Link direction — and the wart, stated so no one "fixes" it

Two cases, deliberately different, because a live daemon holds an **absolute socket path** and its
directory therefore **cannot be moved**:

- **New agents (target state):** the real home is `~/.pam/agents/<id>/`. cmux points at it via the
  **recorded `identity_path`/`home_path` pointer** (the `agents.identity_path` column already exists
  in `agents.db` — the hook is there). A stored path, not a filesystem symlink: more legible, less
  fragile, and it avoids an inverted link entirely. Direction: **cmux → PAM.**
- **Legacy live agents (migration):** the directory stays at `~/.cmux/<name>/` while the daemon
  holds its socket. PAM creates `~/.pam/agents/<id>/` as a **symlink → the live cmux dir**, records
  the row, and never moves a byte. Direction: **PAM-home → cmux dir.**

So mid-migration a reader sees two populations with opposite link arrangements. **That is correct
and temporary.** The per-agent end condition: when a legacy agent is eventually stopped, `rm`'d, and
recreated, it is reborn in PAM-land with the target-state (cmux → PAM, path-pointer) arrangement.
"Empties by attrition" is per-agent, not a batch. **Do not** attempt a single-pass move of the live
fleet to unify the directions — moving a running agent's directory out from under its daemon's
absolute socket path is the one action that breaks it. The inconsistency is the safe state.

## 8. Asserted phase — reusing the `where_are_we` pattern (requirement #4)

The reusable pattern, from `ada-framework/where_are_we.py` + `ada-oracle/checks/ledger.py`:

- Store `(status, sha)` in the durable record. Read **HEAD live** at render time
  (`git -C <path> rev-parse HEAD`); never guess it, and refuse to classify (don't report "clean")
  if HEAD can't be read.
- Staleness = **prefix-compare** stored `asserted_sha` against live HEAD (`Entry.stale_against`).
  No sha stored ⇒ never stale (it's a requirement, not a finding).
- Present three distinct states, never a bare "ready": **current** (`sha == HEAD`), **stale**
  (settled against a non-HEAD commit — unverified, not wrong), and **asserted** (a terminal status
  with *no evidence* — the ledger claims it, the world backs nothing; flagged highest-cost).

**Net-new vs ADA, stated honestly:** `where_are_we.py` carries the **SHA only** — there is no
asserted-*at* wall-clock timestamp anywhere in it or `ledger.py`, and it renders `DONE AS OF <sha8>`
/ `[status@sha8]`, not the brief's paraphrase "ready as of <sha>, still HEAD". The brief's
requirement #4 explicitly wants the *time* a status was asserted at, so `phase_assertions.asserted_at`
is a deliberate extension of the ADA pattern, not a claim that ADA already has it. PAM renders, e.g.,
`ready as of a1b2c3d (asserted 2026-10-02T14:02Z) — still HEAD` or `… — STALE, HEAD now e4f5g6h`.

Phase vocabulary reuses the heartbeat taxonomy's categories and its `new / repeat / changed /
cooldown` transition semantics (`heartbeat/state.py`, `heartbeat/taxonomy.py`) rather than inventing
a parallel status language.

## 9. Command surface

Every command reads/writes records and/or runs read-only git; **none shells out to tmux** (§4.1).

| command | does |
|---|---|
| `pam project add <name> --repo <url> --path <p> [--framework ada] [--default-branch main]` | create project + its first repo. **Verifies** `git -C <p> remote get-url origin` matches `--repo`'s origin; **refuses on mismatch** (requirement #3). |
| `pam project add-repo <project> --repo <url> --path <p> --default-branch <b>` | add another first-class repo to a project (each with its own origin + default branch). |
| `pam project ls` / `pam project show <name>` | list / inspect (reads authored files at call time for anything substantive). |
| `pam onboard <name> --project <p> --role <r> [--session-id <id>] [--cwd <p>]` | register a session **PAM did not start** (a plain `claude`, or a registered-but-not-started coordinator). Mints the id, binds name→id, records cwd + session-id if given. Closes the "registry is only as complete as the spawner" hole. |
| `pam resolve <name>` | → active `id` + `(last_session_id, cwd)`. The name→id seam (§7.2). |
| `pam agent ls` / `pam agent show <name\|id>` | list / inspect agents. |
| `pam assign <agent> --repo <repo> [--issue N] [--pr N] [--by <agent>]` | record a staffing/assignment. |
| `pam phase <agent> <phase> [--sha <sha>] [--repo <repo>] [--evidence …]` | assert a phase; records `asserted_sha` + `asserted_at`. |
| `pam status <agent>` / `pam where <agent>` | render asserted phase with live-HEAD staleness (§8). |
| `pam retire <agent-id>` | mark retired — frees the name for reuse without merging histories; the attrition step (§7.3). |
| `pam verify-binding <repo>` | re-check a bound path's origin against the recorded value; **the spawn-time re-check** (requirement #3) a spawner calls before launching. A path can be re-pointed (one pointed `~/Projects/openlibrary-ada` at a different repo of the same name); re-verify, don't trust the registration. |

## 10. Migration plan — the fleet is live (39 agents)

No single-pass move. Daemons hold absolute socket paths; moving a running agent's directory breaks
it. Order:

1. **Build PAM, touch nothing live.** Create the `pam` package, `~/.pam/pam.db`, and the no-import
   test. The fleet keeps running on cmux unchanged.
2. **Reconcile three sources into PAM rows, read-only against the fleet:**
   `sessions.json` (39 live) ∪ `agents.db` (96 historical) ∪ each home's `cwd` + `last-session-id`
   files. Mint a ULID per agent; carry `role`/`workspace`/`identity_path`/flags from `agents.db`,
   `cwd` + `last-session-id` from the home files. Reconcile against all 96 so the identity catalog
   is complete, not just the 39 running.
3. **Link the live agents in place** (legacy direction, §7.3): `~/.pam/agents/<id>/` → symlink →
   `~/.cmux/<name>/`. Record `home_path` as that symlink; mark the inverted direction on the row.
   **No files move.**
4. **New agents are born in PAM-land** (target direction): home at `~/.pam/agents/<id>/`, cmux
   pointed at it via the recorded path pointer. From here the two populations coexist.
5. **Attrition, per agent:** when a legacy agent is stopped and recreated, it is reborn in PAM-land
   with the target arrangement. `~/.cmux/` empties one agent at a time.
6. **Retire the JSON RMW** (a *later* cmux PR, out of scope here): cmux reads/writes PAM via a
   `db`-module-shaped API instead of the racy `sessions.json`; `sessions.json` becomes a derived
   view or is dropped. Until then PAM keeps the name-keyed `last-session-id` files in sync so the
   existing cmux path resolves correctly (§7.2).

The unsafe action to guard against at every step: a bulk "cleanup" that moves live directories to
unify link direction. The temporary inconsistency is the safe state.

## 11. Relationship to ADA and Oracle

PAM **installs** ADA and Oracle; it does **not** vendor them. They are fetched **pinned** and
upgradeable separately, so a project holding a fixed Oracle check isn't forced onto a new terminal
tool by a PAM bump. Reconciling with what exists today:

- **Pinned install is net-new.** Today the only install is an *unpinned* one-liner
  (`pipx install git+https://github.com/mekarpeles/oracle.git`, no `@ref`) in `ada-oracle/README.md`
  and `spawn.py`'s preflight. `pipx` must be used (not a venv) because the Oracle Stop-hook
  subprocess needs `oracle` on `PATH`. The mechanism for pinning already works —
  `pipx install 'git+…@<sha>'` — so PAM ships a small manifest of pinned refs and installs from it.
  No submodule, no vendoring.
- **The `$MUX` dependency is aspirational.** ADA does not declare a `$MUX` token anywhere; the string
  lives only in the brief. ADA's *real* dependency mechanism is `oracle.yml`'s `context:` block — a
  flat list of required env vars (`REPO, ISSUE, PR, WORKTREE, BRANCH, PORT, BASE, ADA, LEDGER,
  ADA_ORACLE`) that a launcher populates and `spawn.py`'s `preflight()` refuses to proceed without.
  **PAM satisfies that real mechanism** (populate + verify the context a project's pipeline
  declares). If a named `$MUX`/harness check is still wanted, it is a new contract to add to ADA
  deliberately — not something PAM can "satisfy" against code that doesn't declare it.
- **Harness-category tooling can live here, with care.** `whereis.sh`, `spawn.py`,
  `scheduled_wakeups.py` (today standalone in `ada-oracle`, none wired into `oracle.yml`) are fleet
  tooling the brief places in PAM. Their reusable disciplines are the point: **refuse on ambiguity
  with empty stdout** (`whereis.sh`), **preflight-refuse unless every binding is verified**
  (`spawn.py`: full 40-char base sha, worktree on the PR's real headRefOid, private scratch, hook
  present), **unknown is never "clean"** (`scheduled_wakeups.py`: created/denied/indeterminate as
  three states). `whereis.sh` is tmux-specific, so it ships as a standalone operator script, **not**
  as an import of the `pam` package — the core import path stays tmux-free (§4.1).

## 12. Where this design departs from or extends the brief (so nothing is quiet)

1. **cmux is not pure-JSON.** It already has `agents.db` (SQLite/WAL/upsert). PAM is the
   generalization of that working table, not a greenfield SQLite-vs-JSON build. (Improves the plan.)
2. **`asserted_at` is net-new.** `where_are_we.py` stores the SHA only. The brief wants the time;
   PAM adds the column as a deliberate extension of the ADA pattern.
3. **`$MUX` is aspirational.** PAM satisfies ADA's real `oracle.yml` `context:` mechanism; the
   `$MUX` token would be a new contract to add to ADA, not an existing one to satisfy.
4. **Pinned Oracle/ADA install is net-new.** Today's install is unpinned; PAM builds the pinned,
   no-vendor fetch.
5. **The `tasks` table is explicitly out of scope** (legacy, superseded by `cq`); staffing-to-work,
   if recorded, uses `assignments`.
6. **New-agent linkage is a stored path pointer, not a symlink** (the `identity_path` column already
   exists), which removes the inverted-link wart for the new-agent case; the symlink survives only
   for the legacy can't-move-a-live-daemon case.

None of these changes the brief's four hard requirements; items 2–4 record where the brief's "reuse
X" meets code that doesn't yet have X, so the implementation PRs build it rather than claiming it.

## 13. Open questions for review

1. **`identity_path` vs `home_path`.** The design keeps both (one points at the definition
   `identity.md`, one at the home dir). If they always coincide, collapse to one column.
2. **ULID inline vs a tiny dependency.** Design assumes a ~10-line stdlib ULID to keep the install
   dependency-free. If a vetted dependency is preferred, say so; it does not affect the schema.
3. **`teams` with an authored roster** — confirm PAM should record only team *existence* + project
   linkage, never membership (membership stays authored, read at call time). The schema assumes yes.
4. **When cmux is cut over** (step 6) — out of scope here, but the sequencing (how long the two
   registries run in parallel, who writes which) is the first thing the next unit must pin down.
