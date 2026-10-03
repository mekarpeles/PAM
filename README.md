# PAM: Project Agentic Management

**PAM is one tool for running AI agents against your codebases.** It gives you ADA, an atomic
development agent that takes a single unit of work from an issue to a pull request and then stops, and
for teams it adds the coordination and runtime around a fleet of them.

You run `pam init` in a repo the way you run `git init`, and that repo becomes agent-workable. Open
Library is one Project run this way. Lenny, Petabox, or PAM itself are others, and nothing here is
Open-Library-specific.

## One tool

There is one command surface, `pam`. Installing it sets up the system; there is no separate system
init. ADA ships inside it (`pam/agents/ada/`) because ADA only means something once a Project binds its
placeholders, so it is part of PAM rather than a separate install. A developer who only wants the
atomic agent uses the ADA parts. A team running a fleet uses the rest.

## The vocabulary

- A **Project** is the container: a git repository plus its `.pam/` config. It is what you `pam init`,
  and it may reference more than one repo (Open Library is one Project over five repos). The Project is
  rooted in a repo, not identical to it.
- An **Epic** is a unit of work inside a Project: a bundle of issues, the thing an operator manages day
  to day. In a GitHub-backed Project an Epic is a forge epic issue with sub-issues.
- An **Issue** with its **pull request** is the atomic pair a single ADA owns.
- An **Agent** is a first-class teammate, independent of any one Project; it joins a Project through a
  membership that carries a role and a reporting line, and it can work across repos.

## Where things live (the git model)

PAM splits state the way git does, and for the same reason.

- **`.pam/` in the repo** holds the Project's authored config: the schema, the repos, the inferred
  issue tracker, the ADA setup, roles, labels, and the team definitions under `.pam/agents/<name>/`
  (each agent's `agent.toml` plus a vanilla `identity.md`). It is committed and shared, like
  `.git/config` plus tracked files, and it is valuable standalone: someone who never runs pam or cmux
  still gets the standardized roles and the ADA process by reading it. Clone the repo, run `pam init`
  (or it is already there and `pam` just loads it), and you have the Project.
- **`~/.pam/`** holds your per-developer recorded state: the Store (SQLite) and your per-developer,
  per-Project settings. It is per machine and never shared, like `~/.gitconfig`. The authored agent
  definition lives in the repo's `.pam/agents/`; the live runtime home is provisioned by cmux at spawn
  (named by the agent's uuid, with `cq` and the session there), not committed and not created by
  onboard.

So the authored half travels in the repo, and the recorded half stays on your machine. A teammate who
clones the repo gets the setup, not your running agents.

## The three layers

1. **Store** (`~/.pam/`, SQLite), the recorded state: which Projects you have, your agents,
   memberships, epics, phase. Agents are first-class and Project-independent; they join a Project
   through a membership that carries a role and a reporting line. Every agent has a stable ULID id and
   a reusable display name, and reusing a name can never merge two agents' histories.
2. **Runtime + Actions** (PAM's execution layer). ADA does the work; the Runtime is the management
   layer that keeps a fleet of agents fed from events. It watches your issue and PR environment and
   turns changes into action. Actions are its plugins, modeled on GitHub Actions: a trigger (an event
   or a schedule) plus a handler (deliver to an existing agent, spawn, run a skill, run a script). It
   delivers to agents that already exist rather than starting a fresh container each time.
3. **Project config** in the repo's `.pam/`, the authored setup: roles, skills, the Oracle checks for
   this codebase, actions, the label to state map. Text, version-controlled, reviewed through the same
   PRs as the code.

## ADA, the atomic unit

ADA is the broadly useful piece, because every codebase needs an agent that can take one unit of work
to a quality PR and then stop, while only some need a management layer on top.

ADA lives in `pam/agents/ada/` and is project agnostic: every name in its manual is a placeholder a
Project binds. Its contract, taken from the versions that already work in practice:

- Own one issue end to end. Post a ledger of what must become true, in the issue's own terms. Develop
  in a worktree with red-first tests. Open a draft PR early. Verify in the real environment and sort
  every claim into what you ran and what you read. Get an adversarial review from a subagent before
  marking ready. Never merge.
- The Oracle is a subconscious, not a supervisor. It surfaces at most one thing when you are about to
  stop and have missed something, and silence from it is not approval.
- Stop only when finished or genuinely blocked. Finished means you closed your own ledger and the only
  thing left is a human merge. Blocked means a decision, authorization, or access you searched for
  first and could not resolve. Everything else is still work, so keep going.

That last point is the whole defense against the two failure modes that matter: idling for days
waiting on a human, and being poked by a cron to do low-value work when nothing is left.

## Roles

PAM ships four roles, kept distinct. A Project can define its own on top of these.

- **ada_agent**: ADA, the agent that does the work (one issue and its PR).
- **division_lead**: manages a set of Epics; breaks them into issues and unblocks the ADA agents as a
  consultant.
- **project_lead**: the meta role for a Project; keeps the Project's docs current and unblocks
  Division Leads. Tends the shared setup rather than any single Epic.
- **agent**: the generic catch-all for a team member that is not one of the above.

## Why not GitHub Actions

The obvious home for "watch the forge, react" is a workflow runner. It does not work here, for two
structural reasons. A stock ephemeral runner cannot keep an agent alive: a run gets a container, does
a thing, and is destroyed, while an ADA agent must survive from the moment a PR opens until it merges,
holding a worktree and accumulated context. And some work cannot run in that model at all, like a
scheduled check against infrastructure with no runners or a secrets-bound host. So the event source is
remote and the execution must be local and durable. The honest version of the claim is "why not an
*ephemeral* runner"; a self-hosted runner or a durable-execution service solves part of it, and PAM's
Runtime is the local, durable bridge for the rest.

## cmux and the invariant

cmux integrates with PAM, not the other way around. Its remaining value is workspaces and keeping
agents alive; native SendMessage handles agent-to-agent messaging. PAM never imports cmux, so
`pip install pam` works on a machine with no tmux. The Runtime's decision core is tmux-free and runs
dry-run by default; real dispatch goes through the cmux seam. A test keeps the no-import rule green.

## Conventions

- Docs align first, then code follows to match, and the two land in the same PR. A docs change never
  merges ahead of the code that makes it true. When code and docs disagree, that is a defect to fix.
  See [docs/conventions.md](docs/conventions.md).
- No em-dashes or other AI-slop constructs in anything we write.

## Getting started

```bash
pip install -e .
cd ~/Projects/openlibrary
pam init                                   # create .pam/ here; register the Project in ~/.pam
pam activate openlibrary --as openlibrary-bot   # per-dev identity (virtualenv-style), no creds stored
pam agent onboard ada      --project openlibrary --role project_lead
pam agent onboard reviewer --project openlibrary --role agent
pam agent ls ; pam status
```

`pam init` creates the repo's `.pam/` (commit it) and registers the Project in your `~/.pam`. More in
[docs/quickstart.md](docs/quickstart.md) and [docs/plan.md](docs/plan.md). Backlog and design history
are the [issues](https://github.com/mekarpeles/PAM/issues).

## Status

**Shipped:** `pam init` and the `.pam/`-in-repo config model, including the standalone-readable
standards it seeds (`roles.md`, `agents/`); `pam onboard` writing the committed agent definition into
`.pam/agents/<name>/`; `pam activate` (per-dev, per-Project identity and env, virtualenv-style, no
credentials stored); the Store and CLI (Projects, repos, agents, memberships, roles, epics;
origin-verified binding; full relaunch spec); the forge adapter; computed agent and epic state plus the
ledger renderer; and the Runtime decision core (action manifest loader, dedup/cooldown, dispatch
interface, dry-run). ADA folded into `pam/agents/ada/`.

**Next:** the cmux provisioning seam (`pam spawn`, issue #50); `pam kb`; the Runtime poll loop and,
gated, live dispatch; curating the ADA process and skills into a short set.

**Deferred:** Project publish/install and a central Registry, both superseded by config-in-the-repo;
the cmux integration; the community agent/skill marketplace (`pam registry`).
