# PAM — Project Agentic Management

**PAM is the layer that keeps long-lived agents fed from short-lived events.**

It installs and wires together the pieces an operator needs to run a fleet, and it supplies the one
thing none of them provide: **a bridge from a remote event source to a local agent that is already
running.**

## Why this exists, stated as a constraint rather than a preference

The obvious home for "watch GitHub, react to a push" is GitHub Actions. **It does not work here, for
two independent reasons, and both are structural:**

**An Action cannot keep an agent alive.** A workflow run is ephemeral by design — it gets a container,
does a thing, and the environment is destroyed. An ADA agent is the opposite: expensive to set up,
holding a worktree, a stack, and accumulated context, and **it needs to survive from the moment a PR
opens until that PR merges.** The most an Action can carry across runs is a session id, which is a
pointer to an environment the Action cannot keep.

**And some work cannot run in an Action at all.** A scheduled check against infrastructure that does
not support Actions — private hosts, a config repo with no runners — has nowhere to live in that
model, no matter how the workflow is written.

**So the event source is remote and the execution must be local and durable.** PAM is the API layer
across that gap: it polls or subscribes to a source, decides what is actionable, and **messages an
agent that already exists** rather than starting one.

## What installing PAM gives you

1. **`cmux` + `cq`** — the multiplexer that holds agents, and their task queue.
2. **ADA + the Oracle** — the atomic development pipeline and its verification layer.
3. **PAM itself** — the event bridge and the scheduler for work that cannot be an Action.

## What PAM is not

- **Not the pipeline.** How an agent takes work from issue to merge is ADA's concern.
- **Not your project's structure.** Who leads what, and which repos matter, belong to the project.
- **Not a place for secrets.** It needs credentials to poll; it does not store them.
- **Not a replacement for Actions.** Where an Action works, use one. PAM is for the cases above.

## Getting started

- **[docs/quickstart.md](docs/quickstart.md)** — set up a team from scratch (copy-paste runnable).
- **[docs/plan.md](docs/plan.md)** — the build plan and data model.
- Backlog: the [issues](https://github.com/mekarpeles/PAM/issues) on this repo (epic #5).

```bash
pip install -e .          # the `pam` CLI
pam program add <name> --repo <url> --path <dir>
pam agent onboard <name> --program <name> --role program_lead
pam status
```

## Status

Early but runnable. Phase 1–2 land a working CLI registry (Programs, agents, memberships, roles,
projects); see the quickstart. Assembled from a working implementation in reviewable units.
