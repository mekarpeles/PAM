"""Unit tests for taxonomy.py -- all synthetic fixtures, no real agent touched."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import taxonomy  # noqa: E402


def make_cq(self_h=None, any_h=None, open_=1, total=1, has_queue=True):
    return {'has_queue': has_queue, 'self_h': self_h, 'any_h': any_h,
            'open': open_, 'total': total, 'last_self': None}


def make_detail(last_msg_text=None, last_msg_age_h=1.0):
    d = {'queue': [], 'done': [], 'working': None, 'blocked': [], 'last_msg': None,
         'labels_used': False}
    if last_msg_text is not None:
        d['last_msg'] = {'text': last_msg_text, 'age_h': last_msg_age_h, 'num': 1, 'title': 'x'}
    return d


def make_pr(state='OPEN', draft=False, add=10, del_=5, nfiles=2, ntests=1,
            failing_names=(), review=''):
    return {
        'repo': 'internetarchive/APP_REPO', 'number': 999, 'title': 't', 'state': state,
        'draft': draft, 'add': add, 'del': del_, 'nfiles': nfiles, 'ntests': ntests,
        'playwright': False, 'failing': len(failing_names), 'failing_names': list(failing_names),
        'checks_ok': 3, 'review': review,
    }


# ---------------------------------------------------------------- question detection

def test_question_detection_positive():
    assert taxonomy.looks_like_open_question('Which option do you want, A or B?')
    assert taxonomy.looks_like_open_question('Want me to proceed with the rebase?')
    assert taxonomy.looks_like_open_question('Need a decision on the staging DB approach')
    assert taxonomy.looks_like_open_question('Should I merge this now')


def test_question_detection_negative_routine_log():
    assert not taxonomy.looks_like_open_question(
        'Pushed commit abc123, all tests green, 42 passed.')
    assert not taxonomy.looks_like_open_question(
        'Done: docs updated, worktree cleaned up.')


def test_question_detection_empty():
    assert not taxonomy.looks_like_open_question('')
    assert not taxonomy.looks_like_open_question(None)


# ---------------------------------------------------------------- categorize()

def test_merged_needs_cleanup_wins_over_everything():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=1),
                             detail=make_detail('all done, ready to merge'),
                             pr=make_pr(state='MERGED'))
    assert v.category == 'merged_needs_cleanup'


def test_merged_but_agent_already_down_is_not_cleanup_flagged():
    # If the agent's already down, there's nothing to clean up via this path.
    v = taxonomy.categorize(agent='a', up=False, cq=make_cq(self_h=1),
                             detail=make_detail(), pr=make_pr(state='MERGED'))
    assert v.category != 'merged_needs_cleanup'


def test_open_question_wins_over_clean_pr_shape():
    v = taxonomy.categorize(
        agent='a', up=True, cq=make_cq(self_h=0.5),
        detail=make_detail('Want me to proceed with option B or hold for your call?'),
        pr=make_pr(state='OPEN', failing_names=()))
    assert v.category == 'open_architectural_question'


def test_never_self_reported_is_ambiguous_exhausted():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=None),
                             detail=make_detail(), pr=None)
    assert v.category == 'exhausted_own_progress'
    assert v.confidence == 'ambiguous'


def test_real_ci_failure_is_needs_testing():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=10),
                             detail=make_detail('pushed a fix, waiting on CI'),
                             pr=make_pr(state='OPEN', failing_names=('python_tests',)))
    assert v.category == 'needs_testing'
    assert 'python_tests' in v.reason


def test_only_known_infra_check_failing_is_not_needs_testing():
    v = taxonomy.categorize(
        agent='a', up=True, cq=make_cq(self_h=10),
        detail=make_detail('nothing left to do, waiting on review'),
        pr=make_pr(state='OPEN', failing_names=('assign',), review=''))
    assert v.category != 'needs_testing'
    # Should fall through to blocked_on_human since it's genuinely clean modulo known infra.
    assert v.category == 'blocked_on_human'


def test_no_tests_on_large_diff_is_needs_testing():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=1),
                             detail=make_detail('opened the PR'),
                             pr=make_pr(state='OPEN', add=300, del_=50, ntests=0))
    assert v.category == 'needs_testing'


def test_changes_requested_is_needs_review_not_blocked_on_human():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=10),
                             detail=make_detail('addressing feedback'),
                             pr=make_pr(state='OPEN', review='CHANGES_REQUESTED'))
    assert v.category == 'needs_review'


def test_clean_pr_recently_active_is_active_not_blocked():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=0.2),
                             detail=make_detail('just pushed'),
                             pr=make_pr(state='OPEN'))
    assert v.category == 'active'


def test_review_required_is_blocked_on_human():
    """Real bug found against bookreader#1581, not caught by earlier synthetic fixtures:
    GitHub's reviewDecision can be 'REVIEW_REQUIRED' (requested, not yet decided) -- this must
    be treated the same as no-review-yet, not fall through to the generic fallback."""
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=48),
                             detail=make_detail('done, tests passing'),
                             pr=make_pr(state='OPEN', review='REVIEW_REQUIRED'))
    assert v.category == 'blocked_on_human'


def test_clean_pr_idle_is_blocked_on_human():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=48),
                             detail=make_detail('done, 27 tests passing, CI green'),
                             pr=make_pr(state='OPEN'))
    assert v.category == 'blocked_on_human'


def test_large_stale_draft_low_tests_is_needs_splitting():
    v = taxonomy.categorize(
        agent='a', up=True, cq=make_cq(self_h=20),
        detail=make_detail('still working through it'),
        pr=make_pr(state='OPEN', draft=True, add=1800, del_=400, ntests=1, nfiles=30))
    assert v.category == 'needs_splitting'


def test_no_pr_yet_but_recently_active_is_active():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=1),
                             detail=make_detail('doing discovery'), pr=None)
    assert v.category == 'active'


def test_no_pr_yet_and_idle_is_ambiguous_exhausted():
    v = taxonomy.categorize(agent='a', up=True, cq=make_cq(self_h=10),
                             detail=make_detail('doing discovery'), pr=None)
    assert v.category == 'exhausted_own_progress'
    assert v.confidence == 'ambiguous'


# ---------------------------------------------------------------- find_unassigned_efforts

def test_find_unassigned_efforts():
    efforts = [
        {'name': 'A', 'agents': []},
        {'name': 'B', 'agents': ['some-agent']},
        {'name': 'C', 'agents': []},
    ]
    unassigned = taxonomy.find_unassigned_efforts(efforts, running_agents={'some-agent'})
    assert {e['name'] for e in unassigned} == {'A', 'C'}


# ---------------------------------------------------------------- find_unregistered_agents

def test_finds_agent_running_but_not_in_any_effort():
    efforts = [{'name': 'A', 'agents': ['known-agent']}]
    result = taxonomy.find_unregistered_agents(efforts, running_agents={'known-agent', 'rogue'})
    assert result == ['rogue']


def test_standing_specialists_never_flagged_as_unregistered():
    efforts = []
    result = taxonomy.find_unregistered_agents(
        efforts, running_agents=set(taxonomy.STANDING_SPECIALISTS))
    assert result == []


def test_personal_agents_never_flagged_as_unregistered():
    efforts = []
    result = taxonomy.find_unregistered_agents(
        efforts, running_agents={'mekauth', 'mekwiki', 'mektodos'})
    assert result == []


def test_registered_agent_not_flagged_even_if_also_matches_no_prefix_pattern():
    efforts = [{'name': 'A', 'agents': ['weirdname']}]
    result = taxonomy.find_unregistered_agents(efforts, running_agents={'weirdname'})
    assert result == []


def test_is_personal_agent():
    assert taxonomy.is_personal_agent('mekauth')
    assert taxonomy.is_personal_agent('mektodos')
    assert not taxonomy.is_personal_agent('pr-12689-availability-in-solr')
    assert not taxonomy.is_personal_agent('adadash')  # standing specialist exception, not personal


# ---------------------------------------------------------------- cross-check against adadash

def test_infra_checks_match_adadash():
    """taxonomy.py deliberately duplicates KNOWN_INFRA_CHECKS instead of importing (see module
    docstring) -- this test is the tripwire that catches the two drifting apart."""
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    collect_path = os.path.join(os.path.dirname(here), 'adadash', 'collect.py')
    spec = importlib.util.spec_from_file_location('adadash_collect', collect_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert taxonomy.KNOWN_INFRA_CHECKS == mod.KNOWN_INFRA_CHECKS


# --- no_resolvable_worktree ---------------------------------------------
# Added 2026-09-21 by oracle-dev. Measured on the live fleet: 19 of 36
# registered agents had a recorded cwd that was not a git worktree, six of
# them PR-shaped -- and FOUR of those six were sitting in
# `exhausted_own_progress` ("doesn't cleanly fit a known category, needs a
# human look"). They were not ambiguous; they had one boring mechanical cause
# nobody had named.

def test_unresolvable_worktree_is_named_rather_than_ambiguous():
    """The point of the category: these agents were being reported as needing
    a human look, when the cause is a `git rev-parse` away and the remedy is
    specific."""
    v = taxonomy.categorize(agent='pr-11956-core-vitals-retention', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(),
                            pr=None, worktree_ok=False)
    assert v.category == 'no_resolvable_worktree'
    assert v.confidence == 'high'
    assert 'relaunch' in v.reason.lower()


def test_unknown_worktree_is_not_treated_as_broken():
    """None means we could not look. A category that fires on absence of
    evidence is the confident negative this fleet keeps getting wrong, and it
    is why every existing fixture still passes untouched."""
    v = taxonomy.categorize(agent='pr-11956-core-vitals-retention', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(),
                            pr=None, worktree_ok=None)
    assert v.category == 'exhausted_own_progress'


def test_a_specialist_agent_outside_a_worktree_is_not_broken():
    """`adadash` living in ~/Projects/ada is correct. Scoped to PR-shaped
    agents precisely so this stays true."""
    v = taxonomy.categorize(agent='adadash', up=True, cq=make_cq(self_h=None),
                            detail=make_detail(), pr=None, worktree_ok=False)
    assert v.category != 'no_resolvable_worktree'


def test_a_personal_agent_outside_a_worktree_is_not_broken():
    v = taxonomy.categorize(agent='mekroots', up=True, cq=make_cq(self_h=None),
                            detail=make_detail(), pr=None, worktree_ok=False)
    assert v.category != 'no_resolvable_worktree'


def test_merged_cleanup_still_wins_over_an_unresolvable_worktree():
    """An agent still running against merged work is waste regardless of
    where it thinks it lives -- and cleanup is actionable where relaunching
    is not."""
    v = taxonomy.categorize(agent='pr-13395-x', up=True, cq=make_cq(self_h=1.0),
                            detail=make_detail(), pr=make_pr(state='MERGED'),
                            worktree_ok=False)
    assert v.category == 'merged_needs_cleanup'


def test_worktree_resolves_says_none_when_there_is_nothing_to_judge():
    assert taxonomy.worktree_resolves('') is None
    assert taxonomy.worktree_resolves(None) is None


def test_worktree_resolves_says_false_for_a_plain_directory():
    assert taxonomy.worktree_resolves('/tmp') is False


# --- effort_closed ------------------------------------------------------
# ada's finding, verified independently before building: of five agents with
# an unresolvable worktree, OL#13261 (closed 2026-08-20) and
# ArchiveLabs/lenny#194 (closed 2026-09-04) are genuinely closed, while
# OL#11956 and BR#1580 are OPEN and merely stale. "Untouched since July" is
# not "closed", and the two must not collapse into one category.

def test_effort_closed_outranks_a_broken_worktree():
    """Decisive beats diagnostic. Relaunching an agent into the right
    directory to work an issue that closed a month ago is careful work aimed
    at nothing."""
    v = taxonomy.categorize(agent='pr-13261-preserve-intent', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(), pr=None,
                            worktree_ok=False, effort_closed=True)
    assert v.category == 'effort_closed'


def test_merged_cleanup_still_outranks_effort_closed():
    """merged_needs_cleanup owns the closed-PR case and owns it more
    precisely -- it knows the PR number and the remedy is the same."""
    v = taxonomy.categorize(agent='pr-13395-x', up=True, cq=make_cq(self_h=1.0),
                            detail=make_detail(), pr=make_pr(state='MERGED'),
                            effort_closed=True)
    assert v.category == 'merged_needs_cleanup'


def test_an_open_but_stale_effort_is_not_closed():
    """The correction to the original five-row generalisation: two of them
    were open and stale, which is what exhausted_own_progress is already
    for."""
    v = taxonomy.categorize(agent='br-1580-audioreader', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(), pr=None,
                            effort_closed=False)
    assert v.category != 'effort_closed'


def test_unknown_closure_never_fires():
    """An agent torn down on a bad lookup is unrecoverable. None means we
    could not tell, and the recurring bug in this fleet is the confident
    negative."""
    v = taxonomy.categorize(agent='pr-13261-preserve-intent', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(), pr=None,
                            effort_closed=None)
    assert v.category != 'effort_closed'


def test_the_remedy_names_the_risk_in_terms_a_reader_can_act_on():
    """Originally asserted the word "unpushed", from when this was a courtesy
    check. The wording changed when it became a gate: "commits that exist on
    no remote" says what is actually at stake, where "unpushed" reads as a
    routine git state. Assertion retargeted to the intent, not relaxed --
    the refusal behaviour itself is pinned by
    test_unpushed_work_refuses_teardown_rather_than_warning_about_it."""
    v = taxonomy.categorize(agent='pr-13261-preserve-intent', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(), pr=None,
                            effort_closed=True, unpushed=3)
    assert 'no remote' in v.reason.lower()
    assert '3 commit' in v.reason


def test_effort_is_closed_returns_none_without_a_parseable_number():
    assert taxonomy.effort_is_closed('adadash', 'internetarchive/APP_REPO') is None
    assert taxonomy.effort_is_closed('pr-13261-x', None) is None


def test_a_down_agent_gets_cleanup_advice_not_shutdown_advice():
    """merged_needs_cleanup requires `up` by design -- its concern is an agent
    still burning against finished work. So once a session goes DOWN, nothing
    reported that its worktree, cmux registration and docker volumes remain.
    That is how 150 orphaned volumes and 178 dead containers accumulated."""
    v = taxonomy.categorize(agent='lenny-194-opds-perf', up=False,
                            cq=make_cq(self_h=None), detail=make_detail(), pr=None,
                            effort_closed=True, unpushed=0)
    assert v.category == 'effort_closed'
    assert 'already down' in v.reason
    assert 'volumes' in v.reason


def test_a_running_agent_is_told_to_shut_down_instead():
    v = taxonomy.categorize(agent='lenny-194-opds-perf', up=True,
                            cq=make_cq(self_h=None), detail=make_detail(), pr=None,
                            effort_closed=True, unpushed=0)
    assert 'still running' in v.reason


def test_ref_is_preferred_over_the_number_in_the_agent_name():
    """They are different objects on purpose: the name carries the
    investigation issue, `ref` carries the PR that fixes it. I originally
    derived from the name after querying for `issue`/`pr` keys that are not in
    the schema, getting None for every effort, and concluding the registry
    "never knew" -- when `ref` is populated 10 of 10. An absent key is not an
    absent fact; it can be a key you guessed."""
    called = {}

    def fake_run(cmd, **kw):
        called['number'] = cmd[3]
        class R:
            returncode, stdout, stderr = 0, 'OPEN', ''
        return R()

    orig = taxonomy.subprocess.run
    taxonomy.subprocess.run = fake_run
    try:
        taxonomy.effort_is_closed('pr-13261-preserve-intent', 'internetarchive/APP_REPO',
                                  ref=13264)
    finally:
        taxonomy.subprocess.run = orig
    assert called['number'] == '13264', 'must query ref, not the 13261 in the agent name'


def test_a_merged_pr_counts_as_a_closed_effort():
    """`gh issue view` resolves PR numbers and reports MERGED as CLOSED for an
    issue query -- merged and closed are both "this effort is over"."""
    def fake_run(cmd, **kw):
        class R:
            returncode, stdout, stderr = 0, 'MERGED', ''
        return R()
    orig = taxonomy.subprocess.run
    taxonomy.subprocess.run = fake_run
    try:
        assert taxonomy.effort_is_closed('x-1-y', 'r/r', ref=195) is True
    finally:
        taxonomy.subprocess.run = orig


# --- the unpushed-work gate ---------------------------------------------
# A survey of ~/Projects found 51 worktrees holding commits that exist on no
# remote at all -- `ada` at 125 and `ada-oracle` at 25, neither with a remote
# configured to push TO, and APP_REPO-core-vitals-retention-scores at 16,
# which is on the teardown list this category generates. So a routine cleanup
# instruction would have destroyed sixteen commits that exist nowhere else.

def test_unpushed_work_refuses_teardown_rather_than_warning_about_it():
    """ada's point: a lead reading "clean this up, but check first" under time
    pressure does the first half. So the verdict must not mention teardown."""
    v = taxonomy.categorize(agent='x-1-y', up=False, cq=make_cq(self_h=None),
                            detail=make_detail(), pr=None, effort_closed=True,
                            unpushed=16)
    assert v.category == 'effort_closed'
    assert 'do not tear it down' in v.reason.lower()
    assert 'finding, not cleanup' in v.reason.lower()


def test_an_unknown_count_refuses_too():
    """None is not zero. Volumes are regenerable by construction, which is
    what made the prune safe to recommend; commits on no remote are
    regenerable by nothing, so the asymmetry of being wrong is total."""
    v = taxonomy.categorize(agent='x-1-y', up=False, cq=make_cq(self_h=None),
                            detail=make_detail(), pr=None, effort_closed=True,
                            unpushed=None)
    assert 'do not tear it down' in v.reason.lower()
    # intent: an unknown count must refuse AND say the measurement failed --
    # wording widened when the message gained the reason it could not run.
    assert 'unknown number' in v.reason.lower()
    assert 'could not run' in v.reason.lower()


def test_a_clean_worktree_still_gets_cleanup_advice():
    v = taxonomy.categorize(agent='x-1-y', up=False, cq=make_cq(self_h=None),
                            detail=make_detail(), pr=None, effort_closed=True,
                            unpushed=0)
    assert 'volumes' in v.reason
    assert 'do not tear it down' not in v.reason.lower()


def test_unpushed_commits_returns_none_when_it_cannot_look():
    assert taxonomy.unpushed_commits(None) is None
    assert taxonomy.unpushed_commits('/nonexistent-path-xyz') is None


# --- what teardown actually destroys ------------------------------------
# ada made two counting errors in one survey and asked whether the gate had
# them. It had neither, and a third that was mine.

def test_a_linked_worktree_counts_only_its_own_branch(tmp_path):
    """Removing a linked worktree deletes a working directory; every branch
    survives in the common dir. Counting the whole store reported 304 for a
    worktree whose own branch was fully pushed -- a refusal on 265 unrelated
    branches, which would fire on every APP_REPO worktree and train a lead
    to click past it. A gate that always fires is not a gate."""
    import subprocess as sp
    main = tmp_path / 'main'
    main.mkdir()
    sp.run(['git', 'init', '-q', '-b', 'master', str(main)], check=True)
    sp.run(['git', '-C', str(main), 'config', 'user.email', 't@t'], check=True)
    sp.run(['git', '-C', str(main), 'config', 'user.name', 't'], check=True)
    (main / 'f').write_text('1')
    sp.run(['git', '-C', str(main), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(main), 'commit', '-qm', 'base'], check=True)
    # a branch that is NOT checked out in the worktree, with unique commits
    sp.run(['git', '-C', str(main), 'branch', 'other'], check=True)
    sp.run(['git', '-C', str(main), 'checkout', '-q', 'other'], check=True)
    (main / 'g').write_text('2')
    sp.run(['git', '-C', str(main), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(main), 'commit', '-qm', 'only-on-other'], check=True)
    # main STAYS on `other` -- git refuses to check out a branch that is
    # already checked out elsewhere, so the linked worktree takes `master`.
    wt = tmp_path / 'linked'
    sp.run(['git', '-C', str(main), 'worktree', 'add', '-q', str(wt), 'master'], check=True)

    # No remotes at all, so every commit is "on no remote". The linked
    # worktree must still report only what ITS removal would destroy.
    assert taxonomy.unpushed_commits(str(wt)) == 1, 'should count master only, not other'
    # The 'standalone counts every branch' assertion that used to sit here
    # called `main` standalone, but the worktree add three lines up stopped
    # that being true. Moved to its own fixture rather than relaxed -- the
    # claim is worth keeping, it just needed a repo it actually describes.
    assert taxonomy.unpushed_commits(str(main)) is None, (
        'the primary checkout of a repo that has linked worktrees is the '
        'shared root, not any agent private tree')


def test_a_genuinely_standalone_clone_counts_every_branch(tmp_path):
    """No linked worktrees: removal destroys everything reachable, so the
    store-wide figure IS this directory's teardown risk."""
    import subprocess as sp
    r = tmp_path / 'solo'
    r.mkdir()
    sp.run(['git', 'init', '-q', '-b', 'master', str(r)], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.email', 't@t'], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.name', 't'], check=True)
    (r / 'f').write_text('1')
    sp.run(['git', '-C', str(r), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(r), 'commit', '-qm', 'base'], check=True)
    sp.run(['git', '-C', str(r), 'checkout', '-q', '-b', 'other'], check=True)
    (r / 'g').write_text('2')
    sp.run(['git', '-C', str(r), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(r), 'commit', '-qm', 'only-on-other'], check=True)
    assert taxonomy.unpushed_commits(str(r)) == 2, 'standalone counts every branch'


def test_a_store_another_agent_also_sits_in_is_unknowable(tmp_path):
    """14 agents recorded ~/Projects/APP_REPO as their cwd. Attributing
    that repo's unpushed commits to any one of them is the same number
    claimed fourteen times."""
    import subprocess as sp
    r = tmp_path / 'shared'
    r.mkdir()
    sp.run(['git', 'init', '-q', '-b', 'master', str(r)], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.email', 't@t'], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.name', 't'], check=True)
    (r / 'f').write_text('1')
    sp.run(['git', '-C', str(r), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(r), 'commit', '-qm', 'base'], check=True)
    assert taxonomy.unpushed_commits(str(r)) == 1
    assert taxonomy.unpushed_commits(str(r), shared=True) is None


def test_a_standalone_clone_counts_every_branch_not_just_head():
    """ada found a repo reporting 7 from its checked-out branch while
    carrying 304 across 266 branches, including a backup/ and a security/
    branch that existed nowhere else. HEAD is the wrong query for a
    standalone repo because removing it destroys the whole object store."""
    # APP_REPO-core-vitals-retention-scores is the live instance: a
    # standalone clone, 16 commits on no remote, on the teardown list.
    n = taxonomy.unpushed_commits('/Users/mek/Projects/APP_REPO-core-vitals-retention-scores')
    assert n is None or n >= 16


def test_the_unknown_branch_names_the_cause_it_actually_hit():
    """The refusal text used to say "not a worktree of its own" for every
    unknown. That survived a change of precondition and became false for the
    commonest case -- 14 agents share one repo and their directories are fine.
    Sending them to hunt a worktree problem they do not have invites them to
    discount a verdict that, for the no-remote repos, they must not."""
    shared = {'/Users/mek/Projects/APP_REPO/.git'}

    why = taxonomy.why_unmeasurable('/Users/mek/Projects/APP_REPO',
                                    '/Users/mek/Projects/APP_REPO/.git', shared)
    assert 'other agents are working in the same repository' in why
    assert 'not a git repository' not in why
    assert 'worktree of its own' not in why, 'the stale rationale must not reappear'

    why = taxonomy.why_unmeasurable('/Users/mek', None, shared)
    assert 'not a git repository' in why
    assert 'launched from the wrong place' in why

    assert 'no working directory is recorded' in taxonomy.why_unmeasurable(
        None, None, shared)


def test_an_unknown_count_still_refuses_teardown():
    """Suppressing the NUMBER must not suppress the WARNING -- the whole
    design rests on None still firing, since you cannot safely tear down what
    you could not measure."""
    v = taxonomy.categorize(
        agent='a', up=False, cq={}, detail={}, pr=None, effort_closed=True,
        unpushed=None,
        unpushed_unknown_why='other agents are working in the same repository')
    assert v.category == 'effort_closed'
    assert 'do not tear it down' in v.reason.lower()
    assert 'other agents are working in the same repository' in v.reason


def test_a_standalone_repo_counts_refs_that_are_on_no_branch(tmp_path):
    """The gate that licenses teardown must not use a ref set narrower than
    what teardown destroys. With --branches it reported 0 for three live
    no-remote repos holding stashed WIP and filter-branch backups, and 0 does
    not fire the warning."""
    import subprocess as sp
    r = tmp_path / 'solo'
    r.mkdir()
    sp.run(['git', 'init', '-q', '-b', 'master', str(r)], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.email', 't@t'], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.name', 't'], check=True)
    (r / 'f').write_text('1')
    sp.run(['git', '-C', str(r), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(r), 'commit', '-qm', 'base'], check=True)
    baseline = taxonomy.unpushed_commits(str(r))

    (r / 'f').write_text('uncommitted work someone would lose')
    sp.run(['git', '-C', str(r), 'stash', '-q'], check=True)
    assert taxonomy.unpushed_commits(str(r)) > baseline, (
        'a stash is work that exists nowhere else and dies with the repo')


def test_a_linked_worktree_ignores_the_shared_stash(tmp_path):
    """Verified against git rather than assumed: refs/stash lives in the
    common dir, so it survives `worktree remove` and is not this worktree's
    teardown risk. A detached-HEAD commit is, and HEAD reaches it."""
    import subprocess as sp
    main = tmp_path / 'main'
    main.mkdir()
    sp.run(['git', 'init', '-q', '-b', 'main', str(main)], check=True)
    sp.run(['git', '-C', str(main), 'config', 'user.email', 't@t'], check=True)
    sp.run(['git', '-C', str(main), 'config', 'user.name', 't'], check=True)
    (main / 'f').write_text('1')
    sp.run(['git', '-C', str(main), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(main), 'commit', '-qm', 'base'], check=True)
    wt = tmp_path / 'linked'
    sp.run(['git', '-C', str(main), 'worktree', 'add', '-q', str(wt), '-b', 'side'],
           check=True)

    before = taxonomy.unpushed_commits(str(wt))
    (wt / 'f').write_text('dirty')
    sp.run(['git', '-C', str(wt), 'stash', '-q'], check=True)
    assert taxonomy.unpushed_commits(str(wt)) == before, (
        'the stash is shared through the common dir and survives removal')


def test_a_clean_commit_count_does_not_license_deleting_uncommitted_work(tmp_path):
    """The one value that reaches teardown is unpushed==0, and mekquintet
    reached it while holding 232 KB of untracked writing. No ref set sees an
    unadded file, and removal destroys it completely."""
    import subprocess as sp
    r = tmp_path / 'repo'
    r.mkdir()
    sp.run(['git', 'init', '-q', '-b', 'main', str(r)], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.email', 't@t'], check=True)
    sp.run(['git', '-C', str(r), 'config', 'user.name', 't'], check=True)
    (r / 'committed').write_text('1')
    sp.run(['git', '-C', str(r), 'add', '-A'], check=True)
    sp.run(['git', '-C', str(r), 'commit', '-qm', 'base'], check=True)

    assert taxonomy.uncommitted(str(r)) == (0, 0)
    clean = taxonomy.categorize(agent='a', up=False, cq={}, detail={}, pr=None,
                                effort_closed=True, unpushed=0,
                                working_tree=taxonomy.uncommitted(str(r)))
    assert 'do not tear it down' not in clean.reason.lower(), (
        'a genuinely clean tree must still be collectable -- a gate that '
        'always fires is not a gate'
    )

    (r / 'prologue.org').write_text('work that was never added')
    assert taxonomy.uncommitted(str(r)) == (0, 1)
    v = taxonomy.categorize(agent='a', up=False, cq={}, detail={}, pr=None,
                            effort_closed=True, unpushed=0,
                            working_tree=taxonomy.uncommitted(str(r)))
    assert 'do not tear it down' in v.reason.lower()
    assert 'untracked' in v.reason
