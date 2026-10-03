# PAM — Project Agentic Management

**PAM is a general-purpose system for running a fleet of long-lived AI agents against real projects.**

You configure a **Program** — your project, your team, your tools — and PAM keeps those agents fed
from the events that matter (a new issue, a PR, a review request, a scheduled check) and keeps track
of who they are and what they're doing. Open Library is one Program; Lenny, Petabox, or PAM itself
are others. Nothing here is Open-Library-specific — OL is an instance.

## The three layers

1. **Registry** (local, SQLite in `~/.pam/`) — identity & policy. **Programs** own repos (code plus a
   shared **Knowledge Base**); **agents** are first-class and Program-independent and **join**
   Programs via a **membership** that carries a **role** and a reporting line; **roles** are a
   seedable catalog (`program_lead` / `division_lead` / `ada_agent` built in, plus your own);
   **projects** are the units of work (a project = a forge epic), worked in isolated **worktrees**.
   Every agent has a stable **ULID id** and a reusable display **name** — reusing a name can never
   merge two agents' histories.

2. **Runtime + Actions** (PAM's execution layer) — the reason PAM exists. The **Runtime** polls your
   Issue/PR environment for changes and turns them into action; **actions** are the plugins it
   triggers, modeled on GitHub Actions/workflows: each is a **trigger** (`on:` an event, or a
   schedule) + a **handler** (deliver-to-an-existing-agent, spawn, run-a-skill, run-a-script). It
   **delivers events to agents that already exist** rather than starting a fresh container each time.

3. **Config bundle** (shareable, in git) — a Program's authored setup: roles, skills, oracle configs,
   actions, onboarding recipes. It lives as **text** in a `pam-{program}` repo (e.g.
   `pam-openlibrary`), version-controlled and PR-able. **Publish** it; others **pull** it.

## The parts of PAM (names)

Clear names for the pieces, so we all mean the same thing:

| Part | What it is |
|---|---|
| **Registry** | The SQLite store of recorded state — Programs, agents, memberships, roles, projects, repo/KB pointers. |
| **Runtime** | PAM's execution layer: watch event sources → decide → dispatch to durable agents. **Actions** (trigger + handler) are its plugins. |
| **Program** | A configured instance (OL, Lenny, PAM-itself). Bundles repos, a Knowledge Base, an Oracle definition, roles, Actions, config. Shareable as `pam-{program}`. |
| **Oracle** | The verification layer. A Program's **Oracle definition** (ordered guard states) is how PAM determines an agent's state for a Project. External, pinned — not vendored. |
| **Knowledge Base (KB)** | A Program-level shared knowledge repo (e.g. `ol-kb`). Authored/shared, part of the Program. |
| **Agent** | A first-class, Program-independent teammate (stable ULID + reusable name). |
| **Role / Membership** | A seedable role catalog; a membership joins an agent to a Program with a role + reporting line. |
| **Project** | A unit of work — a forge epic — worked in an isolated **worktree**. |

This is the next generation of **ADA (Atomic Agent)** — see https://mek.fyi/papers/ada. The ADA
philosophies carry over (atomic agents, the shared Knowledge Base, worktrees, actions); PAM pulls
`cq`, identity/lifecycle, and the action system *into* PAM, reduces cmux to a session/workspace
multiplexer, and uses Claude's native SendMessage for agent messaging.

## Why not GitHub Actions (the founding constraint)

The obvious home for "watch GitHub, react to a push" is GitHub Actions. **It does not work here, for
two independent, structural reasons:**

- **An Action cannot keep an agent alive.** A workflow run is ephemeral; it gets a container, does a
  thing, and is destroyed. An ADA agent is the opposite — expensive to set up, holding a worktree, a
  stack, and accumulated context, and it must survive **from the moment a PR opens until it merges.**
  The most an Action carries across runs is a session id, a pointer to an environment it cannot keep.
- **Some work cannot run in an Action at all** — a scheduled check against infrastructure with no
  runners, a secrets-bound host, a private config repo.

So the event source is remote and the execution must be **local and durable**. PAM's Runtime is the
bridge: it polls or subscribes, decides what is actionable, and **messages an agent that already
exists** (or spawns/schedules) rather than starting one. Where an Action works, use an Action.

## Programs are shareable — the `pam-{program}` model

You should be able to hand your whole setup to someone else so they don't have to build a team from
scratch. PAM makes a Program's **config** serializable to a git repo (like `pam-openlibrary`) — the
dockerhub/pypi model for agent teams:

- **Shared** (text, in the repo): roles + Division-Lead templates, skills, oracle configs, actions,
  recipes, the label→state map, and the **pinned** versions of PAM/ADA/Oracle it builds on.
- **Never shared** (local, in SQLite): which agents exist, their sessions, who claimed which issue —
  the recorded state, which is useless (worse, misleading) to a teammate whose work hasn't started.

Clone a Program → `pam program install` → bind your local values (your checkout paths, your bot
account) → staff it with **your** agents. SQLite stays a local PAM concern and is **regenerated** on
install; a `.db` is never checked into git. Teammates (and their agents) open PRs against the Program
repo to improve the shared setup.

## Fold-in vs depend-on

The rule for what lives where: **a tool that is useful on its own stays its own repo and PAM depends
on it, pinned; a tool that only makes sense inside PAM folds in.** So **Oracle** (a general
verification runner) stays external and pinned; **ADA** folds in as a built-in agent-type + a
PAM-internal progress renderer + an onboarding recipe. Generic assets ship with PAM/ADA; a Program's
bundle holds only its **specific** skills/configs/actions + overrides — it never re-vendors the
generic stuff.

## The invariant that keeps the layers apart

**`pip install pam && pam program add …` works on a machine with no tmux.** PAM never imports cmux;
cmux uses PAM. The Runtime's decision core is tmux-free and can run in **dry-run** (decide, don't
dispatch); actual delivery goes through the cmux/claudio seam. A test keeps this green.

## Getting started

- **[docs/quickstart.md](docs/quickstart.md)** — set up a team from scratch (copy-paste runnable).
- **[docs/plan.md](docs/plan.md)** — the build plan, data model, and external direction-check.
- **[docs/registry-design.md](docs/registry-design.md)** — the registry schema & boundary design.
- Backlog: the [issues](https://github.com/mekarpeles/PAM/issues) (epic #5 and siblings).

```bash
pip install -e .
pam program add OpenLibrary --repo internetarchive/openlibrary --path ~/Projects/openlibrary --framework ada
pam program init OpenLibrary
pam agent onboard ada --program OpenLibrary --role program_lead
pam status
```

## Status

Early but runnable. **Shipped:** the registry CLI (Programs, repos, agents, memberships, roles,
projects; origin-verified binding; full relaunch spec). **In progress:** Program publish/install
(`pam-{program}`), the Runtime + actions, and the forge adapter + computed agent/project
state. Assembled from a working implementation in reviewable units, not written fresh.
