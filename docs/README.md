# PAM design notes

| Document | What it covers |
|---|---|
| [why-not-actions](why-not-actions.md) | The two structural reasons CI cannot do this job |
| [event-loops](event-loops.md) | The polling loops: spawn on assignment, clean up on merge |
| [agent-lifecycle](agent-lifecycle.md) | Detecting idleness without nagging — and the anti-goals, which were the hard part |

## The shape of the problem

**An event source is remote and ephemeral. An agent is local and expensive.** Everything here follows
from that mismatch.

A webhook or a poll tells you something changed. **It cannot tell you whether anyone is working on
it, whether that worker is stuck, or whether waking them is useful** — and those are the questions
that decide whether a fleet makes progress or burns tokens looking busy.

**The anti-goal is stated first because it is the thing that goes wrong.** Not *"hi, checking in for
an update."* Not a ping every five minutes. **An orchestrator that cannot distinguish a working agent
from a stalled one will interrupt the first and ignore the second** — which is worse than no
orchestrator, because it adds noise while leaving the real failure in place.
