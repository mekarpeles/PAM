"""Blocker categorization for atomic Ada agents.
Takes the read-only signals adadash/collect.py already gathers (cq state, PR state, CI,
review decision) and assigns exactly one category from the Operator's own taxonomy. Mechanical-first:
every branch below is a real, checkable signal, not a guess. The one genuinely fuzzy piece
(does this cq comment contain an open question for the Operator?) has a heuristic first pass and an
explicit `ambiguous` escape hatch rather than a confident wrong answer.

Categories (see README.md for the full table with live examples):
  no_agent_assigned        -- a known effort has zero running agents
  needs_testing             -- CI genuinely failing (not known fork-infra breakage), or
                                no tests on a non-trivial diff
  needs_review              -- PR ready, but reviewDecision is unset and nobody's looked
  open_architectural_question -- agent's last word is a real question, unanswered
  blocked_on_human          -- PR clean and ready, nothing left for the agent to do but wait
  exhausted_own_progress    -- idle a long time, no PR, not clearly waiting on one specific thing
  needs_splitting           -- draft, long-lived, diff sprawling relative to test coverage
  merged_needs_cleanup      -- PR is merged/closed but the agent is still up
  active                    -- genuinely still working, nothing to categorize yet
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

# Known fork-PR infra breakage (see adadash/collect.py KNOWN_INFRA_CHECKS) -- a failure here
# says nothing about the PR's own code. Duplicated here rather than imported so this module
# has no hard dependency on adadash's collect.py location; kept in sync by the test that
# cross-checks both constants match (test_taxonomy.py::test_infra_checks_match_adadash).
KNOWN_INFRA_CHECKS = {'assign', 'respond', 'changes_requested'}

# Hours since the agent's own last cq write, past which "idle" starts meaning something rather
# than just "between turns". Matches adadash's ACTIVE_H -- see README Open Decision #2 for why
# a slower default (hours not minutes) is right for this system.
STUCK_AFTER_H = 4.0

# A conservative question-detector: real decision requests, not every "?" (a code comment
# containing a literal question mark inside a quoted string is not a question to the Operator).
# False negatives (missing a real question) are safer here than false positives (nudging
# about something already answered) -- see README's "don't re-ask" requirement.
_QUESTION_PHRASES = re.compile(
    r'(\?\s*$'
    r'|\bwhich (option|approach|design)\b'
    r'|\bwant me to\b'
    r'|\bneed(s|ed)? (a |your )?(decision|call|sign-?off|go-?ahead)\b'
    r'|\bcan you confirm\b'
    r'|\bshould (i|we)\b)',
    re.IGNORECASE,
)


@dataclass
class Verdict:
    category: str
    reason: str
    confidence: str = 'high'  # 'high' | 'ambiguous' -- see module docstring


def looks_like_open_question(text: str) -> bool:
    """Heuristic only. See _QUESTION_PHRASES docstring for the false-negative-safe bias."""
    if not text:
        return False
    return bool(_QUESTION_PHRASES.search(text.strip()))


def worktree_resolves(cwd: Optional[str]) -> Optional[bool]:
    """Is this agent's recorded working directory actually a git worktree with
    a GitHub origin? True / False / None when there is nothing to judge.

    cmux records the INVOKER's cwd on first start and reuses it forever, so an
    agent launched from the wrong directory has its git, docker and file edits
    all defaulting to the wrong repository, with the tmux header as the only
    outward sign. `spawn.py` guards against this now; the agents that show it
    are the ones launched before the guard existed.

    None rather than False when no cwd is recorded: unknown is not broken, and
    a category that fires on absence of evidence would be the confident
    negative this fleet keeps getting wrong.
    """
    if not cwd:
        return None
    try:
        top = subprocess.run(['git', '-C', cwd, 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, timeout=10)
        if top.returncode != 0:
            return False
        origin = subprocess.run(['git', '-C', cwd, 'remote', 'get-url', 'origin'],
                                capture_output=True, text=True, timeout=10)
        return origin.returncode == 0 and 'github.com' in origin.stdout
    except (OSError, subprocess.SubprocessError):
        return None  # could not look; say so rather than guess


_AGENT_NUM = re.compile(r'^(?:pr|br|lenny)-(\d+)-')


def effort_is_closed(agent: str, repo: Optional[str], ref: Optional[int] = None) -> Optional[bool]:
    """Is the issue this agent is named for already closed? True/False/None.

    ada found three of five agents with an unresolvable worktree were working
    on something already closed -- one idle 1285 hours on an issue closed a
    month ago. That is not "needs a human look" and not "wrong directory": it
    is moot, and the remedy is shut it down, not relaunch it.

    The number comes from the agent name because `known_efforts.json` records
    `issue: None` for every one of these -- the registry never knew. A name is
    weaker evidence than a registry field, which is exactly why an
    inconclusive lookup returns None: an agent torn down on a bad parse is
    unrecoverable, and this fleet's recurring bug is the confident negative.

    A closed PR is NOT this category -- `merged_needs_cleanup` already owns
    that and owns it more precisely.
    """
    # `ref` from known_efforts.json, NOT the number in the agent's name. They
    # are different objects on purpose: the name carries the investigation
    # issue, `ref` carries the PR that fixes it (see the per-effort
    # _ref_note entries). I originally derived from the name after querying
    # for `issue`/`pr` keys that do not exist in the schema, getting None for
    # every effort, and concluding the registry "never knew" -- when `ref` is
    # populated 10 of 10. An absent key is not an absent fact; it can be a key
    # you guessed. Prefer the authority another process cannot silently change.
    number = ref
    if not number:
        m = _AGENT_NUM.match(agent or '')
        number = m.group(1) if m else None
    if not number or not repo:
        return None
    try:
        r = subprocess.run(
            ['gh', 'issue', 'view', str(number), '--repo', repo, '--json', 'state',
             '--jq', '.state'],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None  # could not look -- say so rather than guess
    state = r.stdout.strip()
    # `gh issue view` resolves PR numbers too, and reports a MERGED pr as
    # CLOSED -- which is what we want: merged and closed are both "this
    # effort is over".
    return True if state in ('CLOSED', 'MERGED') else (False if state == 'OPEN' else None)


def store_of(cwd: Optional[str]) -> Optional[str]:
    """The object store behind a directory, or None if it is not in a repo."""
    if not cwd:
        return None
    try:
        r = subprocess.run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute',
                            '--git-common-dir'], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def stores_with_multiple_agents(agents) -> set:
    """Stores that two or more agents record as their cwd.

    Not a hypothetical. On this machine: 14 agents in ~/Projects/APP_REPO,
    6 in ~/Projects/mek, 2 each in ~/Projects/pm and ~/Projects/ada. Any
    per-agent number drawn from one of these describes the repository and
    gets repeated once per agent sharing it.
    """
    import collections
    counts: dict = collections.Counter()
    for a in agents:
        path = os.path.join(os.path.expanduser('~/.cmux'), a, 'cwd')
        if not os.path.exists(path):
            continue
        with open(path) as f:
            if store := store_of(f.read().strip()):
                counts[store] += 1
    return {s for s, n in counts.items() if n > 1}


def uncommitted(cwd: Optional[str]) -> Optional[tuple]:
    """(modified, untracked) in the working directory, or None if unaskable.

    NO REF SET SEES THIS, however wide. Widening the teardown count from
    --branches to --all catches a stash and a backup ref, because those are
    objects in the store; it cannot catch a file that was never added. And
    `worktree remove` deletes the working directory, so those files are the
    most completely destroyed thing teardown touches.

    The live case: ~/Projects/quintet, cwd of `mekquintet`, holds
    prologue.org, bible.org, scenes/, storyboard.org -- 232 KB of writing,
    untracked, in a repo with no .gitignore whose last commit is from
    2025-08-07. Every commit is safely on origin, so the commit-based gate
    returned 0, which does not fire the warning, which reads as "clean, tear
    it down".

    Untracked counts. The instinct is to discount it as build noise, and in a
    repo with a .gitignore that would be fair; here the untracked files ARE
    the work. Deciding that for the reader is how this class of check goes
    wrong -- report both numbers and let the verdict say what they are.
    """
    if not cwd:
        return None
    try:
        r = subprocess.run(['git', '-C', cwd, 'status', '--porcelain',
                            '--untracked-files=normal'],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    return (sum(1 for x in lines if not x.startswith('??')),
            sum(1 for x in lines if x.startswith('??')))


def why_unmeasurable(cwd, store, shared_stores) -> Optional[str]:
    """Plain-language reason a teardown count could not be attributed, so the
    verdict explains the cause it actually hit rather than a stale one."""
    if not cwd:
        return "no working directory is recorded for it"
    if not store:
        return (f"its recorded working directory ({cwd}) is not a git repository "
                f"at all -- cmux records the invoker's cwd at first start, so it "
                f"was launched from the wrong place and has no worktree")
    if store in shared_stores:
        return (f"other agents are working in the same repository ({store}), so "
                f"its unpushed commits belong to the repository and cannot be "
                f"attributed to this agent. See durability.py for the repo-level "
                f"figure, which is where that risk is actionable")
    return "the measurement failed"


def unpushed_commits(cwd: Optional[str], shared: bool = False) -> Optional[int]:
    """Commits that TEARING THIS DOWN would destroy. None if unknowable.

    Not "commits on no remote in this directory" -- that is a different
    number, and using it makes the gate wrong in both directions.

    A LINKED worktree shares its object store with the main checkout, so
    removing it deletes a working directory and some admin files while every
    branch survives in the common dir. Only its checked-out branch is at
    risk. Counting the whole store here reported 304 for a worktree whose own
    branch was fully pushed -- a refusal on 265 unrelated branches, which
    would fire on every APP_REPO worktree and train a lead to click past
    it. A gate that always fires is not a gate.

    A STANDALONE clone has nowhere else for its objects to live, so removing
    it destroys everything reachable from any branch. `--branches --not
    --remotes`, not HEAD: ada found a repo reporting 7 from its checked-out
    branch while carrying 304 across 266 branches, including a
    `backup/acquisitions-v1-prerebase` and a `security/scott-audit-2026-05`
    that existed nowhere else.

    The store-wide number is still a real finding -- it is just a finding
    about a REPOSITORY, not about an agent, and reporting it per-agent
    multiplies it by however many worktrees share the store. ada's survey hit
    exactly that and summed to 41,728 for 824 real commits. It belongs at
    fleet level, deduplicated by git-common-dir.
    """
    if not cwd:
        return None
    if shared:
        # THE DISCRIMINATOR IS NOT A PROPERTY OF THE DIRECTORY. It is whether
        # anyone else claims it. Measured across the fleet: 14 agents record
        # /Users/mek/Projects/APP_REPO as their cwd, 6 record
        # ~/Projects/mek, 2 record ~/Projects/ada. Every one of those 14 was
        # being told the repository's whole unpushed figure as though it were
        # its own teardown risk -- the same commits counted fourteen times,
        # and a refusal to tear down fired on each.
        #
        # No git property separates these from a private clone: ~/Projects/ada
        # is an ordinary standalone repo with no linked worktrees. It is not
        # pr-12844's tree, it is the infrastructure repo the agent happened to
        # be launched from, and adadash is sitting in it too.
        return None
    try:
        gd = subprocess.run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute',
                             '--git-dir'], capture_output=True, text=True, timeout=20)
        cdir = subprocess.run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute',
                               '--git-common-dir'], capture_output=True, text=True, timeout=20)
        if gd.returncode != 0 or cdir.returncode != 0:
            return None
        linked = gd.stdout.strip() != cdir.stdout.strip()
        if not linked:
            others = subprocess.run(['git', '-C', cwd, 'worktree', 'list'],
                                    capture_output=True, text=True, timeout=20)
            if others.returncode == 0 and len(others.stdout.strip().splitlines()) > 1:
                # The PRIMARY checkout of a repo that has linked worktrees is
                # not any agent's private tree -- it is the shared one. Saying
                # 416 about it is true of the repository and meaningless as a
                # teardown risk for an agent. pr-13277's recorded cwd is
                # ~/Projects/APP_REPO with HEAD on an unrelated a11y branch;
                # it was being quoted the whole repo's figure as its own.
                return None
        # STANDALONE TAKES --all, NOT --branches. This branch licenses
        # deletion, so its ref set has to be at least as wide as what the
        # deletion destroys -- narrower means a confident "nothing at risk"
        # on work that is about to be lost, and a 0 does not fire the
        # warning at all (see the `unpushed > 0` test below).
        #
        # Three live false-safes when this said --branches:
        #   lennyforlibraries.org  0 by --branches,  2 by --all  (refs/stash, WIP)
        #   APP_REPO-i18n       0 by --branches,  3 by --all  (refs/stash, WIP)
        #   APP_REPO-pam        0 by --branches, 10 by --all  (refs/original/)
        # All three are repos with NO REMOTE, so the loss would be total. The
        # shared-store fix made this worse before it made it better: agents
        # that still get a number are now almost exclusively the standalone
        # no-remote repos, so the narrow ref set had concentrated onto the
        # highest-risk population.
        #
        # HEAD stays right for a LINKED worktree, and this was checked rather
        # than assumed. refs/stash lives in the COMMON dir -- a stash pushed
        # from a linked worktree is visible from the main checkout and
        # survives `worktree remove`, so it is not this worktree's teardown
        # risk. A detached-HEAD commit, which is, is reachable from HEAD.
        rev = ['HEAD'] if linked else ['--all']
        r = subprocess.run(['git', '-C', cwd, 'rev-list', '--count', *rev,
                            '--not', '--remotes'],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip())
    except ValueError:
        return None


def categorize(
    *,
    agent: str,
    up: bool,
    cq: dict,
    detail: dict,
    pr: Optional[dict],
    stuck_after_h: float = STUCK_AFTER_H,
    worktree_ok: Optional[bool] = None,
    effort_closed: Optional[bool] = None,
    unpushed: Optional[int] = None,
    unpushed_unknown_why: Optional[str] = None,
    working_tree: Optional[tuple] = None,
) -> Verdict:
    """Categorize one atomic agent. All inputs are the plain dicts collect.py already produces.

    `pr` is the fetch_pr() result for this agent's tracked PR, or None if no PR exists yet
    (still in Discovery/Scope, or investigation-only).
    """
    self_h = cq.get('self_h')

    # merged_needs_cleanup takes priority over everything else -- an agent still running
    # against closed work is pure waste, regardless of what its cq queue says.
    if pr and pr.get('state') in ('MERGED', 'CLOSED') and up:
        return Verdict('merged_needs_cleanup',
                        f"PR #{pr['number']} is {pr['state']} but the agent is still up")

    # Above the worktree check, and ada is right about why: a closed effort is
    # DECISIVE where a broken worktree is merely diagnostic. Relaunching an
    # agent into the right directory to work an issue that closed a month ago
    # is careful work aimed at nothing. Below merged_needs_cleanup, which owns
    # the closed-PR case and owns it better.
    if effort_closed is True:
        # HARD GATE, not a courtesy check. ada's point and it is right: a lead
        # reading "clean this up, but check first" under time pressure does
        # the first half. So when there is unpushed work -- or when we could
        # not tell -- this stops being a teardown instruction and becomes a
        # finding, and it does not mention teardown at all.
        #
        # Unknown refuses too. Volumes are regenerable by construction, which
        # is what made the prune safe to recommend; commits on no remote are
        # regenerable by nothing, so the asymmetry of being wrong is total.
        mod, unt = working_tree or (0, 0)
        # A dirty tree refuses on its own. unpushed==0 is the ONLY value that
        # reaches teardown, and it was reached by mekquintet while holding
        # 232 KB of untracked writing -- the commit count was honest and
        # answered a question nobody was asking.
        if unpushed is None or unpushed > 0 or mod or unt:
            # NAME THE ACTUAL REASON. This text used to say the cwd "is not
            # a worktree of its own" for every unknown, which survived a
            # change of precondition and is now false for the commonest case:
            # 14 agents share ~/Projects/APP_REPO, and their directories
            # are perfectly good repos. An agent sent to look for a worktree
            # problem it does not have will discount the rest of the verdict
            # -- and the ones in ~/Projects/{ada,mek,pm}, where teardown is
            # unrecoverable, are precisely the ones that must not.
            if unpushed:
                found = f"{unpushed} commit(s) that exist on no remote"
            elif unpushed is None:
                found = (f"an unknown number of commits -- "
                         f"{unpushed_unknown_why or 'the check could not run'}")
            else:
                found = "no unpushed commits"
            if mod or unt:
                found += (f", AND {mod} modified + {unt} untracked file(s) in the "
                          f"working directory, which no commit count can see and "
                          f"which removal destroys completely")
            return Verdict('effort_closed',
                            f"the effort this agent tracks is closed or merged, BUT this "
                            f"agent's working directory holds {found}. Do not tear it down. "
                            # Keyed on `unpushed is None`, not on falsiness. An
                            # earlier version used `if unpushed else`, so a
                            # known 0-with-a-dirty-tree was told "nothing can
                            # be concluded" when in fact everything was known.
                            # Same shape as the rationale that outlived its
                            # precondition -- advice has to track the branch
                            # that produced it, or it decays into decoration.
                            + (f"Nothing can be concluded about what removal would "
                               f"destroy, and unknown is not zero. Do not read the "
                               f"repo-level figure as this agent's -- that is the "
                               f"mistake this branch exists to stop."
                               if unpushed is None else
                               f"Get the work onto a remote first -- this is a finding, "
                               f"not cleanup, and nothing else in the fleet is watching "
                               f"it. Check EVERY branch it has a claim on, not just the "
                               f"one checked out: a sample of two branches was once "
                               f"reported here as \"contributes zero\" when five carried "
                               f"24 commits."
                               if unpushed else
                               f"The commits are safe; the working directory is not, and "
                               f"it is the part removal deletes outright. Commit, stash "
                               f"or copy those files somewhere durable first. Do not "
                               f"assume untracked means disposable -- check what they "
                               f"are, since in the case that produced this branch the "
                               f"untracked files were the entire work.")
                            + f" And ask whether anyone is waiting on this environment: "
                              f"git safety cannot see a lead holding a stack for a "
                              f"verification that has not run yet.")
        if up:
            what = ("the agent is still running against it, which is pure waste. Check "
                    "for unpushed commits, then shut it down.")
        else:
            # merged_needs_cleanup requires `up`, deliberately -- its concern is
            # an agent still burning against finished work. So once a session
            # goes DOWN nothing reports that its worktree, cmux registration
            # and docker volumes are still there. That is how 150 orphaned
            # volumes and 178 dead containers accumulated, and it is why this
            # branch exists rather than deferring to that category.
            what = ("the session is already down, but its worktree, cmux registration "
                    "and docker volumes remain -- nothing reports those once an agent "
                    "stops. Check for unpushed commits, then remove them.")
        return Verdict('effort_closed',
                        f"the effort this agent tracks is closed or merged -- {what} "
                        f"Teardown is irreversible and an agent idle for weeks may hold "
                        f"work nobody has seen.")

    # Before anything that reads the agent's own signals: if its recorded cwd
    # is not its worktree, NOTHING about its work is derivable -- not by this
    # script, not by the oracle, not by the agent itself. Measured 2026-09-21:
    # four of the agents sitting in `exhausted_own_progress` ("doesn't cleanly
    # fit a known category, needs a human look") were not ambiguous at all,
    # they were this. A residual bucket is worth checking for one boring cause
    # before it is treated as irreducible judgement.
    #
    # High confidence, not ambiguous: this is a `git rev-parse`, and the
    # remedy is specific -- relaunch from the worktree.
    #
    # Only fires on an explicit False. None means unknown, and unknown is not
    # broken. Scoped to PR-shaped agents because a specialist or personal
    # agent whose cwd is ~/Projects/ada is correct, not broken.
    if (worktree_ok is False
            and agent not in STANDING_SPECIALISTS
            and not is_personal_agent(agent)):
        return Verdict('no_resolvable_worktree',
                        "the agent's recorded cwd is not a git worktree with a GitHub "
                        "origin, so nothing about its work can be derived -- by this "
                        "script, by the oracle, or by the agent itself. Relaunch it "
                        "from its worktree.")

    if self_h is None:
        # Unobservable, in collect.py's terms -- can't categorize what never spoke.
        return Verdict('exhausted_own_progress',
                        'agent has never self-reported to its own cq -- cannot triage further '
                        'without instrumenting it first',
                        confidence='ambiguous')

    last_msg = detail.get('last_msg') or {}
    last_text = last_msg.get('text', '')

    # An open question always wins over PR-shape signals -- if the agent is explicitly asking
    # something, that IS the blocker, regardless of what CI says.
    if looks_like_open_question(last_text) and self_h is not None:
        return Verdict('open_architectural_question',
                        f"agent's last word ({last_msg.get('age_h', 0):.1f}h ago) reads as an "
                        f"open question: \"{last_text[:120]}\"")

    if pr is None:
        # No PR yet. Either still working (fine) or stuck before ever producing one.
        if self_h <= stuck_after_h:
            return Verdict('active', 'no PR yet, but recently active -- still in early phases')
        return Verdict('exhausted_own_progress',
                        f'no PR opened yet and idle {self_h:.1f}h -- worth finding out why',
                        confidence='ambiguous')

    if pr['state'] == 'OPEN':
        # Track "real" (non-fork-infra) failures separately from the raw failing count --
        # a PR whose only red check is a known fork-infra one (see KNOWN_INFRA_CHECKS) is
        # otherwise clean, and must be free to reach the blocked_on_human branch below rather
        # than falling through to the generic fallback (caught by
        # test_only_known_infra_check_failing_is_not_needs_testing).
        non_infra_failing = set(pr['failing_names']) - KNOWN_INFRA_CHECKS
        if non_infra_failing:
            return Verdict('needs_testing',
                            f"real CI failure(s): {', '.join(sorted(non_infra_failing))}")
        if not pr['failing'] and pr['ntests'] == 0 and (pr['add'] + pr['del']) >= 100:
            return Verdict('needs_testing',
                            f"no test files across {pr['nfiles']} changed file(s) on a "
                            f"{pr['add'] + pr['del']}-line diff")

        churn = pr['add'] + pr['del']
        if pr['draft'] and churn > 2000 and pr['ntests'] <= 2 and self_h > stuck_after_h:
            return Verdict('needs_splitting',
                            f"draft, idle {self_h:.1f}h, {churn} lines across {pr['nfiles']} "
                            f"files with only {pr['ntests']} test file(s) -- likely too large "
                            f"for one review pass")

        if pr.get('review') == 'CHANGES_REQUESTED':
            return Verdict('needs_review',  # agent needs to address the review, not the Operator
                            'reviewer requested changes -- ball is in the agent\'s court')

        # Clean modulo known infra breakage, and no review has come back with a change
        # request. `REVIEW_REQUIRED` (GitHub's reviewDecision for "requested, not yet
        # decided") is grouped with the unset case here -- both mean "nothing more for the
        # agent, waiting on a human" -- found via a real PR (bookreader#1581) that my
        # synthetic fixtures never covered; see test_review_required_is_blocked_on_human.
        if pr.get('review') in ('', None, 'REVIEW_REQUIRED'):
            if self_h <= stuck_after_h:
                return Verdict('active', 'still iterating, recently active')
            infra_note = (f" (ignoring known fork-infra failure(s): "
                           f"{', '.join(sorted(set(pr['failing_names'])))})"
                           if pr['failing'] else '')
            return Verdict('blocked_on_human',
                            f"PR #{pr['number']} is clean (CI passing, no open questions) and "
                            f"idle {self_h:.1f}h -- nothing left for the agent to do but wait "
                            f"on review/merge{infra_note}")

    # Fallback: something not cleanly categorized above.
    if self_h <= stuck_after_h:
        return Verdict('active', 'recently active, no clear blocker yet')
    return Verdict('exhausted_own_progress',
                    f"idle {self_h:.1f}h with no clean category match -- needs a human look",
                    confidence='ambiguous')


def find_unassigned_efforts(known_efforts: list[dict], running_agents: set[str]) -> list[dict]:
    """Efforts whose entire `agents` list is empty AND none of its named agents are running.

    An effort with agents=[] and one that's *listed* but currently down are different problems
    (the latter is `merged_needs_cleanup` or `exhausted_own_progress` territory, handled by
    `categorize()`); this function is specifically for "nobody has ever picked this up."
    """
    return [e for e in known_efforts if not e['agents']]


# Standing specialists and coordinators that are never atomic (issue->PR->merge->cleanup)
# agents, so should never be flagged as "untracked" just because they're not in
# known_efforts.json. Kept here rather than imported from adadash/collect.py because this is a
# narrower, heartbeat-specific list (collect.py's PROJECT_EXTRA serves a different purpose --
# deciding what's safe to publish -- and includes things like 'slackbot' that heartbeat.py
# tracks explicitly as an atomic agent in known_efforts.json).
STANDING_SPECIALISTS = {'ada', 'adadash', 'saul', 'lupin', 'lupin-httpproxy', 'adapro', 'cmuxtour'}


def is_personal_agent(name: str, prefix: str = 'operator') -> bool:
    return name.startswith(prefix) and name not in STANDING_SPECIALISTS


def find_unregistered_agents(
    known_efforts: list[dict], running_agents: set[str],
) -> list[str]:
    """Agents that are `up` right now but appear in no known_efforts.json entry at all, and
    aren't a recognized standing specialist or personal agent.

    This is the direct mechanism for "an agent nobody is tracking" -- the accountability gap
    the Operator described, distinct from `find_unassigned_efforts` (a known effort with nobody on it)
    which is the mirror-image problem (someone should exist but doesn't, vs. someone exists but
    nobody's watching).
    """
    registered = {a for e in known_efforts for a in e['agents']}
    return sorted(
        a for a in running_agents
        if a not in registered
        and a not in STANDING_SPECIALISTS
        and not is_personal_agent(a)
    )
