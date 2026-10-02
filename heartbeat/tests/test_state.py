"""Unit tests for state.py's idle-intuition / don't-re-ask machine.

Uses a throwaway tmp path for the state file every test -- never touches the real
heartbeat state.json, and never could touch a real agent (this module has no cmux/gh access
at all).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import state as state_mod  # noqa: E402


def fresh_state(tmp_path):
    return state_mod.HeartbeatState(path=str(tmp_path / 'state.json'))


def test_first_sighting_of_nudge_worthy_category_is_new(tmp_path):
    hs = fresh_state(tmp_path)
    t = hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean, idle 48h')
    assert t == 'new'


def test_not_nudge_worthy_category_is_recorded_but_not_surfaced(tmp_path):
    hs = fresh_state(tmp_path)
    t = hs.evaluate('agent-a', 'active', 'still working')
    assert t == 'not_nudge_worthy'


def test_repeat_of_same_category_and_reason_is_quiet(tmp_path):
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean, idle 48h', now=now)
    t = hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean, idle 49h',
                     now=now + timedelta(minutes=5))
    # Reason text differs only in the volatile hour-count -- should hash the same.
    assert t == 'repeat'


def test_category_change_is_surfaced_as_changed(tmp_path):
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean, idle 48h', now=now)
    t = hs.evaluate('agent-a', 'open_architectural_question', 'asked which design to pick',
                     now=now + timedelta(minutes=5))
    assert t == 'changed'


def test_needs_testing_is_not_nudge_worthy_even_as_details_change(tmp_path):
    """needs_testing means the AGENT has more work, not the Operator -- it should never surface as a
    thing the Operator needs to react to, no matter how the specific failure changes. Ada should not
    ping the Operator about an agent still iterating on its own CI."""
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'needs_testing', 'real CI failure(s): python_tests', now=now)
    t = hs.evaluate('agent-a', 'needs_testing', 'real CI failure(s): eslint',
                     now=now + timedelta(minutes=5))
    assert t == 'not_nudge_worthy'


def test_does_not_resurface_within_cooldown(tmp_path):
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean', now=now, cooldown_h=24.0)
    t = hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean',
                     now=now + timedelta(hours=1), cooldown_h=24.0)
    assert t == 'repeat'


def test_resurfaces_after_cooldown_elapses(tmp_path):
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean', now=now, cooldown_h=24.0)
    t = hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean',
                     now=now + timedelta(hours=25), cooldown_h=24.0)
    assert t == 'cooldown'


def test_transition_into_nudge_worthy_from_quiet_history_is_new(tmp_path):
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'active', 'working', now=now)
    t = hs.evaluate('agent-a', 'blocked_on_human', 'now clean and idle',
                     now=now + timedelta(hours=5))
    assert t == 'new'


def test_acknowledge_resets_surface_clock_without_changing_hash(tmp_path):
    hs = fresh_state(tmp_path)
    now = datetime.now(timezone.utc)
    hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean', now=now, cooldown_h=24.0)
    hs.acknowledge('agent-a')
    t = hs.evaluate('agent-a', 'blocked_on_human', 'PR is clean',
                     now=now + timedelta(hours=1), cooldown_h=24.0)
    # Acknowledged recently -> still within (reset) cooldown -> quiet.
    assert t == 'repeat'


def test_persistence_round_trip(tmp_path):
    path = str(tmp_path / 'state.json')
    hs1 = state_mod.HeartbeatState(path=path)
    hs1.evaluate('agent-a', 'blocked_on_human', 'PR is clean')
    hs1.save()

    hs2 = state_mod.HeartbeatState(path=path)
    assert hs2.get('agent-a') is not None
    assert hs2.get('agent-a').category == 'blocked_on_human'
    # Loaded state should immediately read as a repeat, not a fresh 'new'.
    t = hs2.evaluate('agent-a', 'blocked_on_human', 'PR is clean')
    assert t == 'repeat'


def test_missing_state_file_starts_empty_not_error(tmp_path):
    hs = state_mod.HeartbeatState(path=str(tmp_path / 'does-not-exist.json'))
    assert hs.get('any-agent') is None


def test_corrupt_state_file_starts_empty_not_crash(tmp_path):
    p = tmp_path / 'state.json'
    p.write_text('{not valid json')
    hs = state_mod.HeartbeatState(path=str(p))
    assert hs.get('any-agent') is None


def test_save_is_atomic_no_tmp_file_left_behind(tmp_path):
    path = str(tmp_path / 'state.json')
    hs = state_mod.HeartbeatState(path=path)
    hs.evaluate('agent-a', 'blocked_on_human', 'x')
    hs.save()
    assert os.path.exists(path)
    assert not os.path.exists(path + '.tmp')


def test_signal_hash_stable_across_volatile_numbers():
    h1 = state_mod.signal_hash('blocked_on_human', 'idle 4.3h')
    h2 = state_mod.signal_hash('blocked_on_human', 'idle 9.9h')
    assert h1 == h2


def test_signal_hash_differs_on_real_content_change():
    h1 = state_mod.signal_hash('needs_testing', 'real CI failure(s): python_tests')
    h2 = state_mod.signal_hash('needs_testing', 'real CI failure(s): eslint')
    assert h1 != h2
