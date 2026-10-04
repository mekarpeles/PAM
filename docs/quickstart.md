# Quickstart: set up a team with PAM

From nothing to a running team you can see. Every command is copy-paste runnable. PAM keeps its
per-developer state in `~/.pam/`; the Project's shared config lives in the repo's `.pam/`. Nothing
here needs tmux.

## Concepts (30 seconds)

- **Project**: the container, a git repo plus its `.pam/` config. It is what you `pam init`, and it can
  reference more than one repo. Rooted in a repo, not identical to it.
- **Epic**: a unit of work inside a Project, a bundle of issues. In a GitHub-backed Project an Epic is
  a forge epic issue with sub-issues. This is the operator's daily unit.
- **Agent**: a first-class teammate, independent of any one Project. It joins a Project through a
  membership with a role and a reporting line, and it can work across repos.
- **Role**: `ada_agent` (does the work), `division_lead` (manages Epics), `project_lead` (meta, tends
  the Project and its docs), `agent` (generic). A Project can define its own.

## 0. Install

```bash
cd ~/Projects/pam-framework
pip install -e .            # puts the `pam` command on your PATH
pam --version
```
(Or run without installing: `python3 -m pam.cli …` in place of `pam …`.)

## 1. Initialize a Project

`pam init` is like `git init`. Run it in a repo. It creates `.pam/` (the shared config), infers the
issue tracker from the origin remote, and registers the Project in your `~/.pam`. If `.pam/` already
exists, `pam` just loads it. It also seeds the standalone-readable standards: `.pam/roles.md` (the role
catalog), a `.pam/kb/` knowledge base (Obsidian-style, with rules), and a `.pam/agents/` directory that
`pam onboard` fills. Those read on their own, so a teammate who never runs pam still gets the
standardized roles, the ADA process, and the KB from the repo.

```bash
cd ~/Projects/openlibrary
pam init
pam project config openlibrary     # show the authored config (read live, never cached)
```
Commit the `.pam/` directory with your code. It is the shared Project config.

## 1b. Activate (per developer, like a virtualenv)

`pam activate` sets who you are for this Project on this machine. It records your per-developer
settings under `~/.pam/projects/<project>/` and never stores credentials: it points `gh` at a
per-Project config dir so you authenticate once, as the Project's bot.

```bash
pam activate openlibrary --as openlibrary-bot
# authenticate once, as prompted:
GH_CONFIG_DIR=~/.pam/projects/openlibrary/gh gh auth login
# optional virtualenv-style shell activation:
eval "$(pam activate openlibrary --export)"
```
While active, forge and git actions run as the Project's identity. `pam status` shows the active
Project; `pam deactivate` clears it.

The knowledge base is not a separate step: `pam init` already scaffolded `.pam/kb/` (Obsidian-style,
with rules). Add notes there as `.md` files linked with `[[wikilinks]]`; it is committed and reads on
its own.

## 2. Build the team

```bash
# The Project Lead (meta: tends the Project and its docs):
pam agent onboard ada --project openlibrary --role project_lead

# A Division Lead, reporting to the Project Lead, allowed to onboard others, with marching orders:
pam agent onboard imports-lead --project openlibrary --type division_lead --reports-to ada \
  --can-onboard=true --orders ./orders/imports.md

# An ADA worker, optionally with its resume coordinates if it already exists:
pam agent onboard pr-13163-tags --project openlibrary --type ada_agent \
  --reports-to imports-lead \
  --session-id <claude-session-uuid> --cwd ~/Projects/openlibrary-13163-tags
```
`--type` and `--role` are the same flag; `--reports-to` takes an agent name or uuid. Each onboard
writes a committed definition to `.pam/agents/<name>/`: an `agent.toml` (name, stable uuid, type,
reporting line, `can_onboard`) and a vanilla `identity.md` that `@link`s the type's manual shipped with
the pam package; `--orders <file>` is copied in as `orders.md`. Commit `.pam/agents/` with your code;
it is the shared, standalone-readable team definition. The runtime home is provisioned later by cmux at
spawn, not by onboard, so onboard never writes to `~/.pam`.

Onboarding a name that is already live is refused (reusing a name must never merge two agents'
histories). Free a name first with `pam agent retire <name>`.

## 2b. Spawn an agent

Bring an onboarded agent up through cmux. `pam spawn` seeds the agent's cmux homedir with a bootstrap
`AGENTS.md` (pointing at its `.pam/agents/<name>/` definition and the repo), then runs `cmux up` from
that homedir so the agent boots clean and reads its own identity. It is dry-run by default:

```bash
pam spawn pr-13163-tags --project openlibrary          # dry run: prints the plan, launches nothing
pam spawn pr-13163-tags --project openlibrary --go     # actually launch via cmux
```
At boot there is no worktree: an ADA creates its own as its first act, while a Division Lead just works
the forge. cmux owns the homedir and the session; the active Project's env (from `pam activate`) is
applied so the agent acts as the Project identity.

## 3. Add Epics and staff them

```bash
# An Epic, owned by a Division Lead (in GitHub, projected onto an epic issue):
pam epic add "Tags" --project openlibrary --lead imports-lead --epic 13755 --year 2026

# Put an ADA agent on one of its sub-issues:
pam epic assign "Tags" --agent pr-13163-tags --sub 13163 --by imports-lead
```

## 4. See it

```bash
pam projects                        # list your Projects (active one marked *)
pam team --project openlibrary      # reporting tree of agents and their statuses
pam status                          # your Projects, their leads, counts
pam project show openlibrary        # repos, members, epics
pam epic ls --project openlibrary
pam epic state "Tags"               # the epic rollup and each agent's state
pam agent state pr-13163-tags       # computed work state from PR and CI signals
pam agent ledger pr-13163-tags      # per-requirement ledger: done / stale / asserted / open vs HEAD
pam agent resolve pr-13163-tags     # id + session-id + cwd (what a resume needs)
```

## Teams (optional grouping)

```bash
pam team add frontend --project openlibrary
pam membership add fran --project openlibrary --role ada_agent --team frontend
pam membership ls --project openlibrary
```

## An agent across Projects

An agent is a teammate, not a Project's property. Add the same agent to another Project with a
different role:

```bash
pam membership add ada --project lenny --role project_lead
```

---

Not here yet (tracked on the [issues](https://github.com/mekarpeles/PAM/issues)): the Runtime poll
loop and live dispatch (#21), the kanban and dashboard, and the forge-plugin registry. This quickstart
covers everything needed to stand up and see a team today.
