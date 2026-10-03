# Quickstart — set up your team with PAM

This walks you from nothing to a running team you can see. Every command is copy-paste runnable.
PAM stores its state in `~/.pam/` (override with `PAM_HOME`); nothing here needs tmux.

## Concepts (30 seconds)

- **Program** — one project/instance you manage (Open Library, Lenny, Petabox… or PAM itself). It
  owns one or more **repos** and a **config bundle** (an authored file in the repo).
- **Agent** — a teammate. First-class and Program-independent: the same agent can belong to several
  Programs. It has a stable id and a reusable display name.
- **Role** — what an agent *is* in a Program. PAM ships `program_lead`, `division_lead`, and
  `ada_agent`; a Program can define its own. Roles carry permissions.
- **Membership** — an agent joining a Program with a role and a "reports to" line.
- **Project** — a unit of work, usually a forge **epic** (a GitHub issue). Owned by a Division Lead;
  worked by ADA agents on its sub-issues.

## 0. Install

```bash
cd ~/Projects/pam-framework
pip install -e .            # puts the `pam` command on your PATH
pam --version
```
(Or run without installing: `python3 -m pam.cli …` in place of `pam …`.)

## 1. Register a Program

`program add` records the Program and its first repo, and **verifies** that the local checkout's
`git origin` matches the repo you declare (it refuses on mismatch — pass `--force` to override).

```bash
pam program add OpenLibrary \
  --repo internetarchive/openlibrary \
  --path ~/Projects/openlibrary \
  --framework ada \
  --gh-account openlibrary-bot

# A Program can own several repos, each with its own default branch:
pam program add-repo OpenLibrary --repo internetarchive/olsystem    --path ~/Projects/olsystem    --default-branch master
pam program add-repo OpenLibrary --repo internetarchive/openlibrary-i18n --path ~/Projects/openlibrary-i18n --default-branch main
```

## 2. Scaffold the config bundle

```bash
pam program init OpenLibrary      # writes pam.program.toml into the repo
pam program config OpenLibrary    # shows it (read live, never cached)
```
Edit `pam.program.toml` in the repo to set the label→state map, Oracle defaults, program-specific
roles, and PM-source pointers. Commit it — it's authored config, version-controlled with your code.

## 3. Build the team

```bash
# The Program Lead (you):
pam agent onboard ada --program OpenLibrary --role program_lead

# Division Leads, reporting to the Program Lead:
pam agent onboard imports-lead --program OpenLibrary --role division_lead --reports-to ada
pam agent onboard i18n-lead    --program OpenLibrary --role division_lead --reports-to ada

# An ADA worker agent (optionally with its resume coordinates if it already exists):
pam agent onboard pr-13163-tags --program OpenLibrary --role ada_agent \
  --reports-to imports-lead \
  --session-id <claude-session-uuid> --cwd ~/Projects/openlibrary-13163-tags
```
Onboarding a name that's already live is refused (reusing a name must never merge two agents'
histories). Free a name first with `pam agent retire <name>`.

## 4. Add Projects (epics) and staff them

```bash
# A Project = a forge epic, owned by a Division Lead:
pam project add "Tags epic" --program OpenLibrary --lead imports-lead --epic 13755 --repo openlibrary --year 2026

# Put an ADA agent on one of its sub-issues:
pam project assign "Tags epic" --agent pr-13163-tags --sub 13163 --by imports-lead
```

## 5. See it

```bash
pam status                        # your Programs, their leads, counts
pam program show OpenLibrary      # repos, members, projects
pam project ls --program OpenLibrary
pam project show "Tags epic"      # the agents on the epic
pam agent resolve pr-13163-tags   # id + session-id + cwd (what a resume needs)
```

## Teams (optional grouping)

```bash
pam team add frontend --program OpenLibrary
pam membership add fran --program OpenLibrary --role ada_agent --team frontend
pam membership ls --program OpenLibrary
```

## Reusing an agent across Programs

An agent is a teammate, not a Program's property. Add the same agent to another Program with a
different role:

```bash
pam membership add ada --program Lenny --role program_lead
```

---

**What's not here yet** (tracked as issues on `mekarpeles/PAM`): computed agent state / "what is it
stuck on" (`pam agent state`, #11), the forge adapter (#10), the kanban (#12), and the dashboard
(#15). This quickstart covers everything you need to stand up and see a team today.
