# Skill: adversarial review by your own subagent

**Required before `gh pr ready`.** You spawn it; it is not done to you.

## Why a subagent

**It inherits none of your context, so it is blind to your intent by construction.** It cannot be
persuaded by what you meant to build. A peer agent has to be briefed *into* blindness; a subagent has
it for free, and costs no session.

## Brief it blind, on failure shapes

Tell it **what changed and where**. Do **not** tell it what you believe is correct.

Name these shapes every time:

- **A fix applied to one of a pair** — two things had to change together and only one did.
- **A test that passes for a reason other than the one it names.**
- **A claim the measurement contradicts** — check the PR body's numbers against the code.
- **A guard that verifies with the thing it guards.**
- **A guard whose removal no test catches** — delete it, run the suite; nothing red is a missing test.
- **`skipped` is not `passed`**, and a green check is a claim about the base it ran against.

**It must verify by running code.** A finding that has not been reproduced is a hypothesis.

## It inherits none of your standing rules either

**This is the half that bites.** The same blindness that makes it honest means it does not know your
environment is shared, that a prune is destructive, or that anything it removes belonged to someone.
**Put the rules in the brief or it does not have them:**

- **Never `docker prune`, `rm`, `rmi`, or remove a volume or network.** Not even "its own" — a builder
  prune clears the **whole host's** cache, not the caller's.
- **Never remove anything it did not create.** "Cleaning up after myself" is how shared state dies.
- **Clean up by not creating:** `--rm`.
- **No merges. No force-pushes. Nothing public without your go.**

A review subagent did exactly this — tidying after two throwaway builds, it cleared the shared build
cache for every session on the machine. The author knew the rule and forgot the subagent could not.

## Resolve, then report

**Every finding is fixed with a red-first test, or rebutted with evidence in the thread.** "I disagree"
is not resolution.

**Post a summary as your project's bot: N findings, N fixed, N rebutted** — so a human can see the
review happened and what it cost.

## What this is worth

Measured, not asserted. Across five reviews: **5 of 5 reviewers found material defects, 13 findings, 0
false positives, and 2 of 2 fixes the author had declared verified were defective.** On a later batch
of six pull requests that were all already marked ready: **47 findings, 41 fixed, 5 rebutted** —
including a malformed header that would have returned 500 on every page in one language, and a gate
that would have read clean while the thing it gated got worse.
