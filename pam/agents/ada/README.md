# ADA, PAM's built-in Atomic Development Agent

ADA is a single agent that owns one unit of work end to end, from an issue to a pull request, and
then stops. It is PAM's default agent type. It lives here because ADA only means anything inside a
Project that binds its placeholders, so it ships with PAM rather than as a separate tool.

## What is here

- `AGENTS.md`: the ADA manual. Short on purpose. It is project agnostic: every project name is a
  placeholder a Project binds (see the placeholders skill, pending, below). A Project's `.pam/` binds
  those placeholders; a bare agent reads this file to know the job.
- `oracle.yml`: the generic Oracle definition: the checks true of any issue-to-PR unit of work,
  ordered by cost of being wrong, not by phase. It declares `requires_optional: MUX` for checks that
  need the multiplexer, which PAM supplies and a Project composes in by id. It carries no
  project-specific checks.

## The engine

- `ledger.py` and `where_are_we.py` are ADA's self-assessment engine, adopted from the proven
  ada-framework versions that this manual references. `where_are_we.py` reports a position as done
  as of a sha, stale, asserted, or open, and is non-monotonic by design (a rebase un-does `tested`).
  `ledger.py` also validates escalations (an `escalated` entry must name its kind and what it
  searched). `pam agent ledger` renders the same buckets for an operator.
- A Project's own Oracle checks (for example how to run that project's app) live in the Project's
  `.pam/`, not here. Generic ADA stays project agnostic.

## docs/

The lean, generic docs the manual references, curated from ada-framework (not the old monolith):
- `docs/process.md`: the end-to-end process, plan to handoff.
- `docs/doctrine.md`: the incident lessons, compressed to one principle per line and grouped by when
  each one bites. An on-demand reference, never a startup load.
- `docs/skills/placeholders.md`: the complete list of placeholders a Project binds.
- `docs/skills/worktree-setup.md`: one isolated worktree per issue (generic; project-specific setup
  like submodules, hooks, and a running stack lives in the Project's `.pam/`).
- `docs/skills/adversarial-review.md`: the blind subagent review before a PR is marked ready.

## What stays in a Project's `.pam/`, not here

The fuller ADA working trees carried project-specific skills: how to run a particular stack
(Docker, mypy, the pre-commit hooks), how to drive a particular multiplexer and spawn agents in it,
how to publish to a particular knowledge base, and how to review a PR through a particular bot. Those
are not generic ADA and are deliberately left out. A Project binds them in its own `.pam/`. Generic
ADA stays project agnostic.

## Still deferred (tracked)

Bringing in the Oracle engine (`surface.py`) for the Oracle integration is tracked on the ADA-curation
issue (#44) on mekarpeles/PAM. The doctrine compression that issue also calls for is done: see
`docs/doctrine.md`.

## Provenance

Folded in from the `ada-framework` repo (the clean 5KB manual plus the generic Oracle), which is being
dissolved into PAM. The tangled `~/Projects/ada` working tree (the 116KB monolith) is retired from the
spawn path, not moved here.
