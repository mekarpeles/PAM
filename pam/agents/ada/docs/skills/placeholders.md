# Placeholders a project must bind

**ADA ships with no project in it.** Every repository, account, host and path is a placeholder. This
file is the complete list, if a document here names something concrete that is not on this list, that
is a leak and a bug.

| Placeholder | What it is | Example binding |
|---|---|---|
| `$REPO` | The forge repository the agent works in, `owner/name` | `acme/webapp` |
| `$ORG` | The owning organisation | `acme` |
| `$REPO_PATH` | Local checkout of `$REPO` | `~/code/webapp` |
| `$WORKTREE_ROOT` | Prefix for per-agent worktrees | `~/code/webapp` → `~/code/webapp-123-slug` |
| `$BOT` | The identity agents author as | `acme-bot` |
| `$OPERATOR` | The human who approves merges | a username |
| `$AGENT_WORKSPACE` | Where atomic agents run | a multiplexer workspace name |
| `$KB_REPO` / `$KB_PATH` | The knowledge base agents write findings to | |
| `$CONFIG_REPO` | A private configuration repository, if one exists | |
| `$FRAMEWORK_PATH` | Local checkout of this framework | |
| `$MUX` | The multiplexer CLI that starts and addresses agents | a command name |
| `$SUBMODULE` | A vendored dependency checked out as a git submodule, if one exists | |
| `$DEFAULT_BRANCH` | The repo's default branch; do not assume master or main | `main` |

## Two ways a placeholder goes wrong, and the second is worse

**A concrete name left in** is the obvious one: `acme/webapp` in a document that claims to ship with no
project in it. A reader sees it and knows it is wrong.

**A prose paraphrase in a command slot** is the dangerous one. Replacing a product name with a
description produces `git submodule update --init vendor/the application framework` and
`~/.the multiplexer/{name}/last-session-id`, **commands that read as English and cannot run.** The
first kind of error announces itself; this kind looks like the document is merely wordy, and an agent
may spend a cycle on the typo rather than on the missing binding. **Found across 21 files on `main`,
after a scrub that was reported clean because it was verified by searching for the old names.**

So: **a command slot takes a placeholder or a literal, never a description.** `tests/test_placeholders.py`
enforces it.

## The one place a concrete name is allowed

**A project name is a leak in a command slot and evidence in a provenance block**, and nothing about
the name itself tells you which. So the difference is declared rather than guessed:

```
PROVENANCE:
  Found when a knowledge-base checkout reported 297 remote branches to
  `--branches` and none to `ls-remote`; the repo had no remote at all.
/PROVENANCE
```

Names inside are exempt from the denylist. The markers are comments in Markdown, Python and shell
alike, and the block must close before the file ends, `tests/test_placeholders.py` checks that the
markers balance, because an unterminated block silences every check below it.

**Use it for the incident, not for convenience.** A rule survives someone who disagrees with it only
when the incident that produced it is still attached; nine specific sentences are worth more than nine
general ones. But an incident is a thing that happened once, in the past tense, with a number in it.
**If the name is there because an agent will need to type it, it is a binding and it is a leak.**

## What ADA does assume

**A forge with issues and pull requests, and a git repository.** The pipeline's shape depends on
those: an issue to claim, a branch to build on, a pull request to review and merge. Examples use the
GitHub CLI because one had to be chosen; **the concepts are not GitHub's.**

## What ADA must never assume

A specific repository, organisation, bot account, human, host, language, framework, test runner,
search engine or deployment target. **If you find one, it came from the implementation this was
extracted from, and it should be replaced with a placeholder or deleted.**
