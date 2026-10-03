# PAM — build plan (the general-purpose system)

**Status:** the working plan, 2026-10-02. Supersedes the single-Program assumptions in
[`registry-design.md`](registry-design.md); that doc's schema primitives (ULID stable id, WAL,
authored-vs-recorded, the no-tmux invariant, the migration-by-attrition) still hold — this plan
generalizes the entity model on top of them per Mek's Program direction.

## Context — what and why

PAM is a standalone, SQLite-backed, **general-purpose** system that registers **Programs, agents,
teams, projects, roles, and their relationships**. cmux sits on top for the tmux/claudio/session
mechanics. Open Library is not special — it is one **Program** among many (Lenny, Petabox, and
eventually "PAM" itself). The thing Mek wants built is the *general* system; instantiating a specific
Program (the real OL team) is done *with* PAM, via the CLI, as the acceptance test.

We are not greenfield. There is a three-rung ladder already built:

1. `openlibrary-pam/pam.py` — oldest: one polling loop, `gh`, public repo.
2. `pm/pam.py` — fork: five loops, OL working area; much now superseded.
3. **`~/.cmux/agents.db` (97 agents, already SQLite) + `~/Projects/ada`** — current: a real agent
   registry managed by cmux, plus the prose Program→Division-Lead→Agent→Project model.

PAM formalizes rung 3 into schema + CLI and turns the OL-isms (hardcoded `REPO`, the fixed
18-persona roster, the `fleet/*.tsv` parentage files) into **data**.

## Guiding decisions (settled with Mek, 2026-10-02)

- **Agents are first-class and Program-independent.** An agent is a teammate who **joins** Programs
  via *membership*; the same agent can belong to several Programs with a different role and reporting
  line in each. Identity (ULID) is Program-independent.
- **Roles are a seedable catalog, not a baked hierarchy.** PAM ships `program_lead`,
  `division_lead`, `ada_agent` as built-in seed roles; any Program can adopt, override, or define its
  own. Roles carry **permissions** (Division Leads manage Projects; Program Leads manage the Program).
- **Projects are first-class and independent of agents**; agent↔project is also membership. A
  Project's *representation* is Program-configured (OL → a GitHub **epic** issue + subtask issues).
- **`where_are_we` is role-dependent.** A Division Lead's is a fuzzy review of a Project/epic; an ADA
  agent's is a cheap, computed state. We do **not** invent a `phase:*` label scheme or a monotonic
  "% done" — we render what exists: `taxonomy.categorize()` (coarse category from PR/CI/review/cq) +
  the current Oracle stage (first unsatisfied guard in `oracle.yml` `states:`) + the ledger buckets
  (`where_are_we.py`: DONE/STALE/ASSERTED/OPEN vs a SHA; "position is not monotonic").
- **Fold-in vs depend-on:** Oracle stays an external pinned dependency (a general runner); ADA folds
  in as a seed agent-type + a PAM-internal renderer + an onboarding recipe; the cmux spawn glue stays
  at the harness seam. The core `pam` import never touches tmux (`pip install pam` works with no tmux,
  asserted by a test).
- **Authored vs recorded.** The Program *config bundle* (role catalog, label→state map, Oracle
  defaults, onboarding recipes, PM-source pointers) is an **authored file in the Program's repo**,
  read at call time, never cached. SQLite holds only *recorded* facts (who exists, memberships,
  parentage, projects, assignments, asserted phase). `pam program init` scaffolds the config file.

## Data model (`~/.pam/pam.db`, SQLite WAL)

Generalizes cmux's `agents.db`. ULIDs for ids; ISO-8601 UTC timestamps; per-key upserts.

- **programs** (`id, name, framework, tracker='github', gh_account, config_path, created_at`) — one
  row per Program. Pointers only; the config bundle is authored at `config_path`.
- **repos** (`id, program_id→programs, name, repo_url, path, origin, default_branch, created_at`) —
  a Program owns several; each first-class with its own origin + default branch.
- **agents** (`id ULID PK, name, cwd, last_session_id, identity_path, home_path, no_inject, unblock,
  allowed_tools, status active|retired, created_at, retired_at`) — **no program_id**; first-class.
  Partial-unique index on `name WHERE status='active'` keeps one live agent per name (no history
  merge on reuse).
- **roles** (`id, program_id→programs NULL=built-in seed, key, title, description, permissions(JSON),
  config(JSON: oracle_bundle, onboarding_recipe, …), created_at`) — the seedable catalog.
- **memberships** (`id, agent_id→agents, program_id→programs, role_id→roles, team_id→teams NULL,
  reports_to_id→memberships NULL, config(JSON), joined_at, active`) — M:N agent↔program with role,
  reporting edge, per-Program config. `reports_to_id` is a membership→membership edge (arbitrary
  shape, not a fixed 3-level tree); NULL ⇒ reports to the Program Lead.
- **teams** (`id, program_id→programs, name, created_at`) — grouping within a Program (cmux
  workspace). `UNIQUE(program_id, name)`.
- **projects** (`id, program_id→programs, repo_id→repos NULL, title, kind='epic', forge_ref (issue#),
  owner_id→memberships NULL (the Division Lead), year, created_at`) — unit of work; live state read
  from the forge, not stored.
- **project_members** (`id, project_id→projects, agent_id→agents, sub_ref (sub-issue/PR), staffed_by
  →agents NULL, staffed_at, active`) — M:N agent↔project (the ADA agents on an epic's sub-issues).
- **phase_assertions** (`id, agent_id→agents, project_id→projects NULL, repo_id→repos NULL, phase,
  asserted_sha NULL, asserted_at, evidence, created_at`) — asserted state, staleness computed at
  read time vs live HEAD (reuse `ledger.py` prefix-compare).

Monitor-mode acceptance queries map to cheap joins: Division Leads = memberships with a lead role;
their epics = `projects WHERE owner_id=?`; agents on an epic = `project_members WHERE project_id=?`;
"agent without a Division Lead → Program Lead's" = `reports_to_id IS NULL`; a merged ADA agent =
project_member whose PR state is MERGED (computed).

## File structure

```
~/.pam/
  pam.db                  # recorded state
  agents/<agent-id>/      # durable agent home: identity.md, brief, .cq/, notes, ledger,
                          #   cwd, last-session-id, msg-*.md, oracle config
  programs/<program-id>/  # PAM-side recorded per-program artifacts (NOT the authored config)
```
The authored Program config lives in the Program's repo (`config_path`, e.g. `agents/pam.toml` or a
`.pam/` dir), version-controlled, read live.

```
pam/                      # pip-installable, NEVER imports cmux
  db.py        # schema + CRUD (generalized from cmux agents.db)
  ids.py       # ULID (stdlib)
  config.py    # read authored Program config at call time (no cache)
  models.py    # dataclasses
  programs.py agents.py memberships.py roles.py projects.py
  forge/       # tracker adapter — reuse openlibrary-pam/new_pr_bot.py signals; JSON-out/log-err
  state/       # agent-state (reuse heartbeat/taxonomy.py) + ledger renderer (where_are_we.py)
  data/        # seed roles + default oracle bundles (oracle.yml / oracle.pr.yml) as package data
  cli.py       # argparse command surface
tests/test_no_cmux_import.py
pyproject.toml # console_scripts: pam = pam.cli:main ; deps: oracle @ pinned
```

## Command surface (CLI-first)

```
pam program add <name> --repo <url> --path <p> [--tracker github] [--gh-account openlibrary-bot] [--framework ada]
pam program init <name>              # scaffold the authored config bundle into the repo
pam program ls | show <name> | add-repo <name> --repo <url> --path <p> --default-branch <b>
pam role ls [--program p]            # seed + program roles
pam agent onboard <name> --program <p> --role <r> [--session-id id] [--cwd p] [--reports-to <agent>]
pam agent ls | show <name|id> | resolve <name> | retire <id>
pam agent state <name>              # role-dependent where-are-we (ADA: taxonomy + oracle stage + ledger)
pam agent merged                   # all merged ADA agents
pam agent cleanup <name>           # teardown a merged/spun-down agent (records; harness does the kill)
pam project add <title> --program <p> --lead <agent> [--epic <issue#>] [--repo <r>] [--year Y]
pam project ls [--program p] [--active] [--year Y] | state <project> | assign <project> --agent <a> [--sub <N>]
pam membership ls | add <agent> --program <p> --role <r> [--reports-to <agent>]
pam status                          # my Programs; active Projects across Programs
pam verify-binding <repo>           # re-check bound-path origin (spawn-time guard)
```
No `pam` command shells out to tmux. Spawn/attach/resume/onboarding *acts* stay harness-side; PAM
emits the facts and config they consume.

## Reuse map (don't rewrite)

| Need | Reuse | From |
|---|---|---|
| registry CRUD shape | `agents.db` schema + db module | cmux pipx pkg / `cmux_lib/db.py` |
| GitHub signals/data-gatherer | `new_pr_bot.py` (gh wrappers, CI/label/linked-issue parsing, idempotency) | `openlibrary-pam/scripts/gh_scripts/` |
| ADA agent state | `taxonomy.py::categorize()` + `collect.py` signal fns | `ada/heartbeat`, `ada/adadash` |
| per-requirement ledger | `where_are_we.py` + `ledger.py` (DONE/STALE/ASSERTED/OPEN) | `ada-framework` |
| agent-type config bundle | `oracle.yml` / `oracle.pr.yml` (context contract + ordered states) | `ada-oracle` |
| task state machine | `operating-loop.md` (COLLECT→…→ADVANCE, BLOCKED exit) | `pm/workflows` |
| identity shape | `identity.md` (Role/Workspace/Workflow/Responsibilities/Rules/Team) | `~/.cmux/<agent>/` |
| label taxonomy + epic model | `Type:/Needs:/Lead:/Team:/Priority:` labels; epic=issue, subtask-by-#ref | OL GitHub |

## Build phases

1. **Foundation (this unit):** `pam` package skeleton, `db.py` schema, `ids.py` ULID, `config.py`,
   `cli.py` with `program add` / `agent onboard` / `agent ls` / `status` working against
   `~/.pam/pam.db`; `pyproject.toml`; the no-cmux-import test green. Deliverable: you can register a
   Program and onboard an agent from a clean slate.
2. **Roles + Program config:** seed role catalog, `program init` scaffolding, oracle bundles as
   package data, membership + reporting edges, permissions (advisory in CLI).
3. **Forge + state:** `pam/forge` (reuse `new_pr_bot.py`), `pam agent state` / `pam project state`
   composing taxonomy + oracle stage + ledger; `pam project` + kanban from labels.
4. **Migration importer:** reconcile `agents.db` ∪ `sessions.json` ∪ home files ∪ `fleet/*.tsv` into
   PAM rows; assign existing agents to the OL Program with roles/parentage; attrition for dirs.
5. **Dashboard (later unit):** Monitor + Project-Manage views over the registry (generalizes AdaDash).

## Direction check (external research, 2026-10-02)

Validated against Anthropic's guidance, the orchestration-framework landscape, and emerging agent
standards (A2A, AGNTCY/OASF, MCP). Verdict: the core bet is sound and fills a real gap — **no
surveyed tool offers a standalone durable fleet registry over tmux-persistent long-lived agents**
(closest: claude-swarm, Tmux-Orchestrator, Claude Squad — none with a registry DB).

**Keep (validated):** thin SQLite registry with tmux kept separate (`pip install pam`, no tmux);
ULID surrogate id + reusable name (textbook surrogate/natural key); "first-failing-guard,
non-monotonic" state computed from external signals (matches CI/state-machine/agent-runtime
practice); Oracle = Stop-hook verification (Claude Code even ships an `agent`-type Stop hook);
authored-vs-recorded config split (mirrors Claude Code's own `.claude/` vs `~/.claude/`).

**Reconsidered (applied):**
- **Hierarchy is organizational, not a runtime delegation path.** Deep (3+) hierarchies are a
  documented anti-pattern ("deep hierarchy drift": info loss at each delegation boundary; two-level
  supervisor→worker is the sweet spot until a span exceeds ~7). PAM's `reports_to` edge is an
  **org-chart/reporting label**; PAM does **not** build multi-hop real-time agent-to-agent
  delegation (Anthropic: LLMs are poor at it). Runtime delegation stays ≤2 levels.
- **Resume facts must be the full launch spec, not just id+cwd.** `claude --resume` does not restore
  `--model/--mcp-config/--settings/--add-dir/--agent` unless re-passed; cross-project resume-by-id
  (CC ≥2.1.223) makes cwd a disambiguator, not strictly required. Added `agents.launch_spec` (JSON).
  **Never parse `~/.claude/projects/*.jsonl`** (internal format); use `--output-format json`/hooks.

**Adopt (tracked as issues):** expose the registry over **MCP** so a live agent can ask "who's my
lead / what's my assignment / my role" the Anthropic-native way (#18); align the agent schema with
**A2A Agent Card / AGNTCY OASF** fields for future interop (#19); borrow proven mechanics from
claude-swarm (per-agent role/dir context, session restore) and Tmux-Orchestrator (self-scheduling,
inter-agent messaging — our claudio layer) rather than reinventing. A durable-execution engine
(Temporal) is a *future* option only if crash-exact multi-step orchestration is ever needed — not now.

**Scope note:** the full programs/roles/teams/projects model is more than a minimal v1, but it is
justified by a concrete near-term use (building the real OL team), not speculation — which is the bar
Anthropic sets ("add complexity only when it demonstrably improves outcomes").

## Acceptance tests

- **Clean-slate OL team:** build the real OL Program (leads, epics, ADA agents) from empty `~/.pam`
  using only the CLI. If any Monitor-mode question is expensive, that's a schema finding.
- **Dogfood "PAM" as a Program:** Program Lead = PAM; Division Leads = Dash / Oracle / ADA. If PAM
  can model itself, the generality holds.
- **Invariant:** `import pam` pulls in no cmux; `pip install pam` works with no tmux.
