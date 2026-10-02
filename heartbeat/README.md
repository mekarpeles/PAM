# heartbeat — agent lifecycle tracking

**Answers one question: which agents are stalled, and is waking them useful?**

It is not a scheduler and not a nag. Design and anti-goals in [`../docs/agent-lifecycle.md`](../docs/agent-lifecycle.md).

| Module | Does |
|---|---|
| `heartbeat.py` | The loop: gather state, classify, decide whether to dispatch |
| `state.py` | What each agent currently is — read, never inferred |
| `taxonomy.py` | Classifying an agent's situation into something actionable |
| `messages.py` | What gets said, and to whom |

## Porting notes, read before running

**This came from a working fleet and still carries that fleet's shape.** Names were replaced with
placeholders — `PROJECT_BOT`, `APP_REPO`, `AGENT_WORKSPACE`, `KB_REPO` — which means **it does not
run as-is.** Those are the binding points a project supplies.

**`known_efforts.json` and `state.json` were deliberately not ported.** They are one program's live
state, not framework. A project supplies its own.

**Nothing here is verified against this repo.** It ran elsewhere; the tests came with it; **treat a
passing test as evidence about the original environment until someone runs them here.** That
distinction is the kind this codebase exists to make.
