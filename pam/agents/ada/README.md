# ADA, PAM's built-in Atomic Development Agent

ADA is a single agent that owns one unit of work end to end, from an issue to a pull request, and
then stops. It is PAM's default agent type. It lives here because ADA only means anything inside a
Program that binds its placeholders, so it ships with PAM rather than as a separate tool.

## What is here

- `AGENTS.md`: the ADA manual. Short on purpose. It is project agnostic: every project name is a
  placeholder a Program binds (see the placeholders skill, pending, below). A Program's `.pam/` binds
  those placeholders; a bare agent reads this file to know the job.
- `oracle.yml`: the generic Oracle definition: the checks true of any issue-to-PR unit of work,
  ordered by cost of being wrong, not by phase. It declares `requires_optional: MUX` for checks that
  need the multiplexer, which PAM supplies and a Program composes in by id. It carries no
  project-specific checks.

## The engine

- `ledger.py` and `where_are_we.py` are ADA's self-assessment engine, adopted from the proven
  ada-framework versions that this manual references. `where_are_we.py` reports a position as done
  as of a sha, stale, asserted, or open, and is non-monotonic by design (a rebase un-does `tested`).
  `ledger.py` also validates escalations (an `escalated` entry must name its kind and what it
  searched). `pam agent ledger` renders the same buckets for an operator.
- A Program's own Oracle checks (for example how to run that project's app) live in the Program's
  `.pam/`, not here. Generic ADA stays project agnostic.

## Not yet curated (tracked)

The full process, skills, and doctrine from the old ADA working tree are deliberately not dumped in
here. That material was the "100 pages an agent will not read" failure. Curating it into a short
process doc, a small set of generic skills, and doctrine compressed to one-line principles (or an
on-demand knowledge base, not a startup load) is a tracked task, and the project-specific parts move
to the Program bundle. See the ADA-curation issue on mekarpeles/PAM.

## Provenance

Folded in from the `ada-framework` repo (the clean 5KB manual plus the generic Oracle), which is being
dissolved into PAM. The tangled `~/Projects/ada` working tree (the 116KB monolith) is retired from the
spawn path, not moved here.
