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
exists, `pam` just loads it.

```bash
cd ~/Projects/openlibrary
pam init
pam project config openlibrary     # show the authored config (read live, never cached)
```
Commit the `.pam/` directory with your code. It is the shared Project config.

## 2. Build the team

```bash
# The Project Lead (meta: tends the Project and its docs):
pam agent onboard ada --project openlibrary --role project_lead

# A Division Lead, reporting to the Project Lead:
pam agent onboard imports-lead --project openlibrary --role division_lead --reports-to ada

# An ADA worker, optionally with its resume coordinates if it already exists:
pam agent onboard pr-13163-tags --project openlibrary --role ada_agent \
  --reports-to imports-lead \
  --session-id <claude-session-uuid> --cwd ~/Projects/openlibrary-13163-tags
```
Onboarding a name that is already live is refused (reusing a name must never merge two agents'
histories). Free a name first with `pam agent retire <name>`.

## 3. Add Epics and staff them

```bash
# An Epic, owned by a Division Lead (in GitHub, projected onto an epic issue):
pam epic add "Tags" --project openlibrary --lead imports-lead --epic 13755 --year 2026

# Put an ADA agent on one of its sub-issues:
pam epic assign "Tags" --agent pr-13163-tags --sub 13163 --by imports-lead
```

## 4. See it

```bash
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
