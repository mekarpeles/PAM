"""Integration test: runs the real pipeline against real (live) fleet data.

SAFE BY CONSTRUCTION: every function this touches (adadash's collect.py, `cmux ls`, `gh --json`
reads) is read-only -- see collect.py's own module docstring and its "STRICTLY READ-ONLY BY
CONSTRUCTION" guarantee, which this test does not re-verify (that's collect.py's own test
surface, owned by AdaDash) but relies on.

This test uses its own tmp state.json (never the real one at heartbeat/state.json), so running
it repeatedly does not interfere with the real dry-run history a human might be reading.

It does NOT assert exact category values for specific real agents -- that would make the test
brittle against real-world state changing between test runs (an agent finishing its PR, the Operator
merging something). Instead it asserts STRUCTURAL properties that must hold regardless of the
fleet's exact current state.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import heartbeat  # noqa: E402
import state as state_mod  # noqa: E402
import taxonomy  # noqa: E402


def test_known_efforts_file_loads_and_is_well_formed():
    efforts = heartbeat.load_known_efforts()
    assert len(efforts) > 0
    for e in efforts:
        assert 'name' in e and 'repo' in e and 'ref' in e and 'agents' in e
        assert isinstance(e['agents'], list)
        assert '/' in e['repo']


def test_full_pipeline_runs_against_live_fleet_readonly(tmp_path, monkeypatch):
    """The real end-to-end path: collect -> categorize -> state machine, against real cmux/gh.

    Redirects state.py's default path to a tmp file first, so this never touches the real
    heartbeat/state.json (which a human may be reading as the actual dry-run log)."""
    tmp_state = str(tmp_path / 'state.json')
    monkeypatch.setattr(state_mod, 'DEFAULT_STATE_PATH', tmp_state)

    # heartbeat.run() constructs HeartbeatState() with no path arg, so it reads the module
    # attribute at call time -- patch the class default via the module-level constant it reads.
    orig_init = state_mod.HeartbeatState.__init__

    def patched_init(self, path=tmp_state):
        orig_init(self, path=path)

    monkeypatch.setattr(state_mod.HeartbeatState, '__init__', patched_init)

    d = heartbeat.run()
    assert not os.path.exists(os.path.join(os.path.dirname(__file__), '..', 'REAL_STATE_TOUCHED'))
    assert os.path.exists(tmp_state), 'state should have been written to the tmp path'

    results = d['results']
    assert len(results) > 0, 'expected at least one known effort to produce a result'

    valid_categories = {
        'no_agent_assigned', 'needs_testing', 'needs_review', 'open_architectural_question',
        'blocked_on_human', 'exhausted_own_progress', 'needs_splitting', 'merged_needs_cleanup',
        'active', 'unregistered_agent',
        # added 2026-09-21 -- see tests/test_taxonomy.py's no_resolvable_worktree block
        'no_resolvable_worktree', 'effort_closed',
    }
    valid_transitions = {'new', 'repeat', 'changed', 'cooldown', 'not_nudge_worthy'}
    for r in results:
        assert r['category'] in valid_categories, f"unknown category: {r['category']}"
        assert r['transition'] in valid_transitions, f"unknown transition: {r['transition']}"
        assert r['confidence'] in ('high', 'ambiguous')
        # Every result must be attributable to a real effort name -- no orphan results.
        assert r['effort']

    # Every effort with an empty agents list must appear as a no_agent_assigned result exactly
    # once (this is the case-(a) Amazon-outage scenario made general).
    efforts = heartbeat.load_known_efforts()
    unassigned_names = {e['name'] for e in efforts if not e['agents']}
    surfaced_unassigned = {r['effort'] for r in results if r['category'] == 'no_agent_assigned'}
    assert unassigned_names <= surfaced_unassigned, (
        'every effort with zero agents must be categorized no_agent_assigned -- '
        f'missing: {unassigned_names - surfaced_unassigned}'
    )


def test_second_run_against_same_state_is_quiet(tmp_path, monkeypatch):
    """The core "don't re-ask" promise, proven against real data: running twice back-to-back
    with no real-world change must produce zero 'new' surfacings on the second pass."""
    tmp_state = str(tmp_path / 'state.json')
    monkeypatch.setattr(state_mod, 'DEFAULT_STATE_PATH', tmp_state)
    orig_init = state_mod.HeartbeatState.__init__

    def patched_init(self, path=tmp_state):
        orig_init(self, path=path)
    monkeypatch.setattr(state_mod.HeartbeatState, '__init__', patched_init)

    d1 = heartbeat.run()
    surfaced_first = {(r['agent'], r['category']) for r in d1['results']
                       if r['transition'] in heartbeat.SURFACE_TRANSITIONS}

    d2 = heartbeat.run()
    surfaced_second = {(r['agent'], r['category']) for r in d2['results']
                        if r['transition'] in heartbeat.SURFACE_TRANSITIONS}

    assert surfaced_second == set(), (
        f'second run must be quiet (nothing new) when nothing changed, but surfaced: '
        f'{surfaced_second}'
    )
    # Sanity: the first run actually surfaced something, or this test would pass trivially
    # against a fleet with no findings at all.
    if not surfaced_first:
        import warnings
        warnings.warn('First run surfaced nothing -- either the fleet is fully quiet right '
                       'now or find_unassigned_efforts/categorize regressed. Check manually.')


def test_render_produces_valid_markdown_structure():
    fake = {
        'generated': '2026-08-09T00:00:00+00:00',
        'results': [
            {'effort': 'Test Effort', 'case_study': 'a', 'agent': 'test-agent', 'up': True,
             'category': 'blocked_on_human', 'reason': 'clean, idle', 'confidence': 'high',
             'transition': 'new'},
            {'effort': 'Quiet Effort', 'case_study': None, 'agent': 'quiet-agent', 'up': True,
             'category': 'active', 'reason': 'working', 'confidence': 'high',
             'transition': 'not_nudge_worthy'},
        ],
    }
    out = heartbeat.render(fake)
    assert 'test-agent' in out
    assert 'blocked_on_human' in out
    assert 'Would surface now (1)' in out
    assert 'quiet-agent' in out
    assert 'not sent to any agent or human' in out.lower() or 'Nothing below was sent' in out


def test_dispatch_flag_is_explicitly_unimplemented():
    """The safety boundary itself is tested -- if someone accidentally implements --dispatch
    without updating this test, that's a deliberate speed bump, not an accident."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), '..',
                                                       'heartbeat.py'), '--dispatch'],
                        capture_output=True, text=True)
    assert r.returncode != 0
    assert 'NotImplementedError' in r.stderr or 'not implemented' in r.stderr.lower()
