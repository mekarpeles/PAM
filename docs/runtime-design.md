# PAM Runtime — design (the event→action execution layer)

**Status:** design, for review. Design before code — this doc adds no executable code. Resolves the
open questions PAMPaper raised in #35 (delivery idempotency, agent liveness, native SendMessage,
config consistency) before the dispatch path — which acts on live agents — is built.

## What the Runtime is

The Runtime watches a Program's event sources, decides what is actionable, and dispatches to agents
that already exist (or spawns/schedules). **Actions** are its plugins. It is the local, durable answer
to "watch GitHub, react" that an ephemeral runner cannot be (see `why-not-actions.md`).

```
 sources ── poll/schedule ──▶ MATCH actions ──▶ DECIDE (idempotent) ──▶ DISPATCH ──▶ agent
 (forge, cron)                 (triggers)        (dedup vs Store)        (adapter)    (SendMessage/spawn)
```

## The hard boundary (keeps `pip install pam` tmux-free)

- **Decision core** — `pam/runtime/` — is pure and **tmux-free**. It reads the forge + the Store,
  matches actions, and produces a **plan** (a list of intended dispatches). Default mode is
  **dry-run**: decide and emit the plan, dispatch nothing. This mirrors the ported `heartbeat/`
  safety boundary (`--dispatch` → `NotImplementedError`).
- **Dispatch** — a `DispatchAdapter` interface injected at the seam. The cmux/claudio-backed adapter
  lives outside the `pam` core. `pam runtime run --dispatch` enables real execution.

```python
class DispatchAdapter(Protocol):
    def health(self, agent) -> str: ...        # 'alive' | 'idle' | 'dead' | 'unknown'
    def deliver(self, agent, message) -> None: ...   # native SendMessage to a live session
    def spawn(self, agent, launch_spec) -> str: ...  # (re)start from stored launch_spec -> session id
```

## Actions — the plugin model

An action is a declarative manifest (text, in the Program bundle's `actions/`), so it is shareable
and PR-able:

```toml
# actions/spawn-on-assignment.toml
[trigger]            # exactly one of: event | schedule
event = "issue.assigned"            # or: schedule = "0 9 * * *"
match = { label = "Type: Subtask", assignee = "{gh_account}" }

[handler]            # one of: deliver | spawn | run_skill | run_script
spawn = { role = "ada_agent", oracle_bundle = "oracle.pr.yml" }

[guard]              # optional preconditions, refuse-on-unknown
requires = ["no_running_session"]
```

Generic actions ship with PAM; program-specific ones live in the bundle. Handlers are PAM-provided
verbs (`deliver`, `spawn`, `run_skill`, `run_script`); the manifest wires a trigger → a handler +
params that reference the Program's roles/skills/oracle.

## Delivery semantics (PAMPaper #1 — the #1 correctness risk)

**Fire once per material state-change, never once per poll tick.** A PR open for days must not re-fire
the same action every 60s.

- **Dedup key** = `hash(action_id, subject_ref, state_signature)` where `state_signature` is the
  normalized signals the action cares about (e.g. category + review_decision), **with volatile bits
  stripped** (the heartbeat `signal_hash` trick: strip digits so "idle 4.3h" → "idle Xh" doesn't
  churn).
- The Store records `(action_id, subject_ref) → last_signature, last_fired_at, fire_count` in a
  `runtime_fires` table. An action fires only when the signature is **new** or **changed**, honoring a
  per-action **cooldown** (reuse `heartbeat/state.py`'s `new/repeat/changed/cooldown` verdicts).
- **At-least-once with idempotent handlers.** Delivery may retry; handlers must be safe to repeat
  (deliver uses a bot-marker / dedup id; spawn checks `no_running_session` first). We do not promise
  exactly-once; we promise idempotent effect.

## Agent liveness (PAMPaper #2)

"Deliver to an existing agent" assumes a liveness long Claude sessions don't guarantee — they
compact, degrade, or die. So delivery is **health-gated**:

1. `adapter.health(agent)` before delivering.
2. `alive`/`idle` → `deliver` (native SendMessage).
3. `dead` → **respawn-and-rehydrate**: `adapter.spawn(agent, launch_spec)` using the full stored
   `launch_spec` + `last_session_id` + `cwd` (why the launch_spec column exists), then deliver.
4. `unknown` → **refuse and surface** (never silently void); record it and report. Unknown is never
   treated as "delivered."

## Native SendMessage (PAMPaper #3)

Claude now has native SendMessage, so the Runtime does **not** re-implement ADA's socket/mux delivery
stack. The Runtime emits "send message M to agent A"; the dispatch adapter resolves A → its live
session (via the Store's name→id + the harness) and uses **native SendMessage**. What remains below
the adapter is only: session address resolution, health, and (re)spawn — all harness concerns, not
PAM core.

## Config consistency (PAMPaper #8)

Authored config is "read live, never cached" — but *live as of which commit?* **Each Runtime tick
pins the Program bundle at a single SHA** (resolve HEAD once at tick start; read all actions/roles/
oracle/label-map at that SHA for the whole tick). Prevents a mid-tick edit from splitting a decision.

## Triggers: events and schedules

- **Event** triggers poll the forge (REST, not search — the hard-won lesson) with per-source `since`
  cursors in the Store; idempotency as above.
- **Schedule** triggers run cron-like for work an ephemeral runner can't do — checks against infra
  with no runners / secrets-bound hosts (e.g. the WAF daily check). This is `why-not-actions.md`
  reason #2.

## Build order (each a tight, tested unit)

1. **Action manifest schema + loader** (parse `actions/*.toml`, generic + bundle; pure, tested). → #29
2. **Decision core + dry-run** (match triggers, compute plan; `runtime_fires` dedup/cooldown reusing
   the heartbeat verdicts; pure, tested with a fake forge). → #28, #30
3. **DispatchAdapter interface + a dry-run/no-op adapter** (core stays tmux-free; real cmux adapter
   is a separate seam module, later). → #30
4. **Scheduled triggers.** → #31
5. **Reconcile PR #1 (event-loops) + PR #2 (heartbeat) into the above.** → #32

Steps 1–2 are fully testable with no tmux and no network (injected forge). Real dispatch (step 3's
cmux adapter) is gated behind `--dispatch` and reviewed separately because it acts on live agents.

## Decisions (resolved, per stakeholder review #35 — override welcome)

1. **Cooldown is per-action, default 4h.** `spawn-on-assignment` must never cooldown-suppress;
   `nag-on-stale` wants days. So cooldown is an action-level setting, 4h default.
2. **`unknown`-health → refuse + surface + one bounded re-check**, never auto-deliver.
3. **The cmux `DispatchAdapter` lives in cmux** — but the `DispatchAdapter` Protocol *and* a no-op
   adapter stay in `pam` core, so steps 1–2 test tmux-free and the no-cmux-import test stays green.

## Dispatch-path blockers (stakeholder review #35) — gate the LIVE path

The pure decision core (steps 1–2) is safe to build as specified. **These must land before the cmux
dispatch adapter**, because they only bite once PAM acts on live agents:

- **B1 — spawn is a claim, not a pre-check (TOCTOU).** `no_running_session` checked-then-spawned lets
  two overlapping ticks/retries both spawn. Fix: an **atomic claim row** in the Store —
  `runtime_claims(subject_ref PRIMARY KEY, action_id, claimed_at, state)` with `INSERT … ON CONFLICT
  DO NOTHING`; only the winner spawns. (issue → #39)
- **B2 — respawn crash-loop.** If an agent died *from* its task, respawn+redeliver kills it again.
  Fix: **respawn budget + backoff + quarantine-to-human**, and a defined **dirty-worktree policy** on
  rehydrate (don't blow away uncommitted work). (→ #40)
- **B3 — tick overlap.** The SHA pin is intra-tick; a minutes-long dispatch overlaps the next tick on
  a new SHA. Fix: **non-overlapping ticks (a run lock)** or per-subject locks. (→ #41)
- **B4 — fail-closed tick.** A partial forge read yields a plan on incomplete data (a false
  `no_running_session`). Fix: apply the ledger's "refuse when a signal is unreadable" discipline at
  **tick level — abort, don't dispatch**. (→ #42)

### Delivery-semantics refinements (fold into steps 1–2)

- **Dedup key additions:** (a) per-signal normalization, not a global digit-strip (the global strip
  collapses "3 vs 30 review comments"); (b) include the **action's content-hash** in the key so an
  *edited* action re-fires; (c) debounce ≠ cooldown (debounce = settle rapid changes; cooldown =
  rate-limit repeats).
- **Liveness:** name the health *signal* (not just the enum) — e.g. heartbeat file freshness + pane
  liveness; `idle` delivery can still void without a **read/ack**, so delivery should confirm receipt.
- **SHA pin = committed HEAD**, and warn that **uncommitted bundle edits silently don't take effect**
  (so authors know to commit before a tick picks them up).

### Store tables the Runtime adds

`runtime_fires(action_id, subject_ref, last_signature, last_fired_at, fire_count)` (dedup/cooldown),
`runtime_claims(subject_ref PK, action_id, claimed_at, state)` (B1), plus a run-lock row (B3).

### Residual schema note

`teams` and multi-hop `reports_to` are the only entities the Runtime does not consume — keep them
minimal; don't elaborate until an Action or the Monitor view actually reads them.
