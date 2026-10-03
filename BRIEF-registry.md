# PAM brief — the registry, and PAM as the layer cmux sits on

You own PAM's development, the way Oracle owns Oracle's. Ada (ada-8f) is your Program Lead
and process documenter; consult Ada when you need a decision routed or a doc gap recorded.
You are not Open-Library-specific — PAM is project-agnostic infrastructure.

Mek's direction, settled in conversation on 2026-10-02. Treat these as decided unless you find a
concrete reason one is wrong, in which case raise it with Ada rather than quietly departing.

## What PAM becomes
A standalone, SQLite-backed system that registers **projects, teams, agents, and their
relationships** — the durable identity and policy layer. cmux is reduced to what only it can do:
tmux, claudio, workspaces, attaching Claude sessions, sockets, daemons.

## The invariant that keeps the layers from re-merging
**`pip install pam && pam project add ...` must work on a machine with no tmux.** If PAM imports
cmux anywhere, it is broken. cmux importing PAM is fine. cmux uses PAM, never the reverse. Write a
test that asserts this and keep it green.

## Authored vs recorded — never cache the authored half
- **Authored** (project definition, team roster, capability bindings, doc chain): **files in the
  project repo.** PAM reads them at call time and never caches them. The cache is how cmux's
  hardcoded role dict rotted to 11-of-14-dead; do not rebuild it.
- **Recorded** (which agents exist, parentage, who staffed whom and when, current assignment, last
  known phase): **SQLite in `~/.pam/`.** SQLite because 38 concurrent agent writers race a JSON
  read-modify-write.

## Agent directories live in PAM-land; cmux links to them
`~/.pam/agents/<id>/` is the home. cmux points at it as the agent homedir. Split by lifetime:
- **Durable -> PAM**: identity, brief, `.cq/`, received messages, notes, ledger, **last-session-id**
  (resume needs the id + the same cwd it started in — both PAM facts; an agent must be resumable
  with no cmux).
- **Ephemeral -> cmux**: socket, daemon pid/log, tmux target. These already sit beside the dir today,
  not inside it.

## Four hard requirements
1. **Stable agent id separate from display name.** Names get reused; `cmux up` with a reused name
   resumes a stored session. Reuse must never merge two agents' histories. The id is the primary
   key; the name is a label.
2. **`pam onboard <name> --project <p> --role <r> [--session-id <id>]`** — session-id is an optional
   param. Onboards a session PAM did not start (e.g. a plain `claude` in a terminal, or a
   registered-but-not-started coordinator). Without this, the registry is only ever as complete as
   the spawner — which is the hole the fleet is in now.
3. **A registration is a bound path.** `pam project add` verifies the path's `origin` remote against
   `--repo` and refuses on mismatch; re-check at spawn, because a path can be re-pointed. (A binding
   pointed `~/Projects/openlibrary-ada` at a different repo of the same name last night.)
4. **Asserted state carries the commit and time it was asserted at**, and renders as "ready as of
   <sha>, still HEAD" — never bare "ready". `where_are_we.py` in ADA already does this; reuse the
   pattern, do not reinvent a bare status field that goes stale silently.

## Migration — the fleet is live
38 daemons hold absolute socket paths open. **You cannot move a running agent's directory.** New
agents go to PAM-land; existing ones get symlinked in place; the cmux dir empties by attrition. Do
not attempt a single-pass move with the fleet up.

## Hierarchy
project -> workspaces -> agents. A project owns several repos (the assignment names which `$REPO`).
A project record is pointers only: name, repo, path, framework. Everything else is read from the
authored files. Projects are optional (a personal tutor agent has none); ADA-shaped commands require
one.

## Relationship to ADA and Oracle
PAM installs them; it does not vendor them. Fetch pinned, upgradeable separately — a project taking a
fixed Oracle check must not be forced onto a new terminal tool. ADA names a dependency (`$MUX`, a
harness check); PAM satisfies it. The harness-category checks from ada-oracle (`whereis.sh`,
`spawn.py`, `scheduled_wakeups.py`) belong here.

## Where things stand
- `mekarpeles/PAM` has two open PRs: #1 (event loops / idleness) and #2 (heartbeat lifecycle). This
  repo is `~/Projects/pam-framework`. Mek has NOT granted merge permission on PAM — open PRs, let
  Ada route merges.
- cmux source is `~/Projects/cmux`; its registry is `~/.cmux/sessions.json` (38 agents, 11 fields,
  no `role`); its stale role dict is `cli.py` lines 21-34.

## First deliverable
A written design, as a PR to `mekarpeles/PAM`: the SQLite schema (with the stable-id decision made),
the PAM/cmux authority boundary, the command surface, and the migration plan. **Design before code.**
Do not modify cmux or touch any live agent's directory in this first unit of work.
