# Conventions

Rules for anyone, human or agent, working on PAM.

## Docs and code stay in sync

1. **Docs align first, then code follows to match.** Docs drift out of sync before code does, so when
   the direction changes, reconcile the plan and the docs first. Do not start coding against a new
   direction before the docs say what that direction is.
2. **Docs do not change in a PR separate from the code.** If a PR changes docs, the code must match the
   docs before that PR merges. A docs-only change that claims behavior the code does not have does not
   merge.
3. **When code and docs disagree, that is a defect.** Fix it, either by bringing the code to the docs
   or by correcting the docs in the same change. Do not leave the mismatch. Treat the docs as the
   stated intent.

The reason is concrete. Out-of-sync docs are the main source of agents acting wrongly: an agent reads
the stale half and acts on it. Two real examples this project is correcting are a hardcoded role table
that rotted to mostly-dead, and a reporting target that stayed in the docs for months after it went
dormant, so messages to it failed silently.

## Writing style

No em-dashes. No AI-slop constructs: avoid "not just X, but Y", reflexive rule-of-three lists, and
filler words (delve, leverage, robust, seamless, crucial, testament, landscape, tapestry). Write
plain, direct, declarative prose. A short clear sentence beats a dramatic one. This applies to replies,
commit messages, docs, issues, and every agent brief.
