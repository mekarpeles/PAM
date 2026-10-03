# Skill: worktree setup

Set up one clean, isolated worktree and branch for a single issue, and tear it down after merge. One
worktree per agent. Parallel agents sharing a checkout corrupt each other, and the corruption is
silent.

## Variables

```bash
ISSUE=<issue number>
SLUG=<short-human-readable-slug>        # e.g. genre-explorer
REPO=$REPO_PATH
WORKTREE=$WORKTREE_ROOT-${ISSUE}-${SLUG}
BRANCH=${ISSUE}/${SLUG}
BASE=origin/$DEFAULT_BRANCH             # your Program binds $DEFAULT_BRANCH; do not assume
                                        # master or main. Branching off the wrong base produces a
                                        # silent empty diff, not an error.
```

## Create

```bash
git -C "$REPO" rev-parse --show-toplevel        # sanity check: is this the repo root
git -C "$REPO" worktree list                    # check for a naming conflict first
git -C "$REPO" fetch origin                      # always `fetch origin`, never `fetch origin <branch>`:
                                                 # the latter updates FETCH_HEAD only, and a stale
                                                 # origin branch silently bases your work on old code
git -C "$REPO" worktree add "$WORKTREE" -b "$BRANCH" "$BASE"
```

## Project-specific setup

A project often needs more here: submodules, commit and push hooks, a running stack. Those steps are
not generic ADA. Your Program supplies them from its `.pam/` (for example an Open Library Program
initializes its submodules, installs pre-commit for both commit and push, and starts its containerized
environment). Do not bake project setup into this generic skill.

## Open a draft PR early

```bash
gh pr create --repo $REPO --base "$DEFAULT_BRANCH" --head "$BRANCH" \
  --draft --title "feat({area}): {short description}" \
  --body "Work in progress. Closes #${ISSUE}."
```

Open it before the work is finished. The PR description is your status side-car.

## Teardown (post-merge only)

Safety checks first, then remove. Never remove a worktree that holds work existing nowhere else.

```bash
STATE=$(gh pr view <PR> --repo $REPO --json state --jq '.state')
[ "$STATE" = "MERGED" ] || [ "$STATE" = "CLOSED" ] || { echo "not merged or closed, abort"; exit 1; }

UNPUSHED=$(git -C "$WORKTREE" log origin/"$BRANCH"..HEAD --oneline | wc -l)
[ "$UNPUSHED" -eq 0 ] || { echo "unpushed commits, abort"; exit 1; }

git -C "$REPO" worktree remove "$WORKTREE" --force
git -C "$REPO" branch -d "$BRANCH"
git -C "$REPO" worktree prune
```
