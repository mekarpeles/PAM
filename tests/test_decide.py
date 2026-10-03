"""Runtime decision core: pure matching/signature/verdict/plan (no network, no tmux)."""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

from pam.runtime.actions import Action
from pam.runtime.decide import decide, matches, plan, signature

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def mkaction(**kw):
    base = dict(id="a", trigger_type="event", event="issue.assigned", schedule=None,
                match={}, handler_type="spawn", handler_params={"role": "ada_agent"},
                requires=[], cooldown_h=4.0, content_hash="h1")
    base.update(kw)
    return Action(**base)


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- matches ----------------------------------------------------------------

def test_match_event_and_mismatch():
    a = mkaction(event="issue.assigned")
    assert matches(a, {"event": "issue.assigned"})
    assert not matches(a, {"event": "pr.opened"})


def test_match_label_and_fields():
    a = mkaction(match={"label": "Type: Subtask"})
    assert matches(a, {"event": "issue.assigned", "labels": ["Type: Subtask", "x"]})
    assert not matches(a, {"event": "issue.assigned", "labels": ["x"]})
    b = mkaction(match={"state": "OPEN"})
    assert matches(b, {"event": "issue.assigned", "state": "OPEN"})
    assert not matches(b, {"event": "issue.assigned", "state": "CLOSED"})


# ---- signature --------------------------------------------------------------

def test_signature_changes_with_state_and_action_version():
    a = mkaction()
    s1 = signature(a, {"state": "OPEN", "ci": "passing"})
    s2 = signature(a, {"state": "OPEN", "ci": "failing"})
    assert s1 != s2                                   # material state change
    a2 = mkaction(content_hash="h2")
    assert signature(a2, {"state": "OPEN", "ci": "passing"}) != s1  # edited action re-fires


# ---- decide -----------------------------------------------------------------

def test_decide_new_changed_cooldown_repeat():
    a = mkaction(cooldown_h=4.0)
    assert decide(a, "sig", None, NOW) == (True, "new")
    assert decide(a, "sig", {"signature": "other", "last_fired_at": _ts(NOW)}, NOW) == (True, "changed")
    recent = {"signature": "sig", "last_fired_at": _ts(NOW - timedelta(hours=1))}
    assert decide(a, "sig", recent, NOW) == (False, "cooldown")
    old = {"signature": "sig", "last_fired_at": _ts(NOW - timedelta(hours=5))}
    assert decide(a, "sig", old, NOW) == (True, "repeat")
    assert decide(a, "sig", {"signature": "sig", "last_fired_at": None}, NOW) == (True, "repeat")


# ---- plan -------------------------------------------------------------------

def test_plan_filters_and_fires_new():
    a = mkaction(match={"label": "Type: Subtask"})
    subjects = [
        {"event": "issue.assigned", "ref": "42", "labels": ["Type: Subtask"], "state": "OPEN"},
        {"event": "issue.assigned", "ref": "43", "labels": ["other"]},
    ]
    fires = plan([a], subjects, last_fire=lambda aid, ref: None, now=NOW)
    assert len(fires) == 1
    assert fires[0].subject_ref == "42" and fires[0].verdict == "new"
    assert fires[0].handler_type == "spawn" and fires[0].handler_params["role"] == "ada_agent"


def test_plan_cooldown_suppresses_repeat():
    a = mkaction(match={"label": "x"}, cooldown_h=4.0)
    subject = {"event": "issue.assigned", "ref": "7", "labels": ["x"], "state": "OPEN"}
    sig = signature(a, subject)
    recent = {"signature": sig, "last_fired_at": _ts(NOW - timedelta(hours=1))}
    fires = plan([a], [subject], last_fire=lambda aid, ref: recent, now=NOW)
    assert fires == []                                # within cooldown, unchanged -> suppressed


def test_plan_dryrun_is_pure():
    a = mkaction(match={})
    calls = []
    def reader(aid, ref):
        calls.append((aid, ref))
        return None
    subjects = [{"event": "issue.assigned", "ref": "1"}]
    plan([a], subjects, last_fire=reader, now=NOW)
    plan([a], subjects, last_fire=reader, now=NOW)
    assert len(calls) == 2                            # reads only; identical across runs, no writes


# ---- db-backed dedup --------------------------------------------------------

def test_plan_with_db_fires_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "pam"))
    import pam.config as config
    import pam.db as db
    importlib.reload(config)
    importlib.reload(db)
    db.init()

    a = mkaction(match={"label": "x"}, cooldown_h=4.0)
    subject = {"event": "issue.assigned", "ref": "99", "labels": ["x"], "state": "OPEN"}
    sig = signature(a, subject)

    # first tick: no record -> fires 'new'
    assert len(plan([a], [subject], db.get_fire, now=datetime.now(timezone.utc))) == 1
    # dispatcher records the fire (stamps real wall-clock time)
    db.record_fire(a.id, "99", sig)
    assert db.get_fire(a.id, "99")["fire_count"] == 1
    real = datetime.now(timezone.utc)
    # next tick within cooldown, unchanged -> suppressed
    assert plan([a], [subject], db.get_fire, now=real + timedelta(minutes=5)) == []
    # past cooldown -> repeat
    assert len(plan([a], [subject], db.get_fire, now=real + timedelta(hours=5))) == 1
