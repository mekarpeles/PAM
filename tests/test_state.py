"""Agent/project state: pure classifier branches + wiring with a fake forge (no network)."""
import importlib

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "pam"))
    import pam.config as config
    import pam.db as db
    import pam.program_config as pc
    import pam.state.agent_state as st
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(pc)
    importlib.reload(st)
    db.init()
    return db, st, pc, tmp_path


class FakeForge:
    def __init__(self, pr=None, labels=None):
        self._pr = pr or {}
        self._labels = labels or []
    def pr(self, repo, ref):
        return dict(self._pr, number=ref)
    def issue_labels(self, repo, ref):
        return list(self._labels)


class BoomForge:
    def pr(self, *a):
        raise AssertionError("forge.pr should not be called")
    def issue_labels(self, *a):
        raise AssertionError("forge.issue_labels should not be called")


# ---- pure classifier --------------------------------------------------------

@pytest.mark.parametrize("pr,expected", [
    ({"state": "MERGED"}, "merged_needs_cleanup"),
    ({"state": "CLOSED"}, "closed"),
    ({"state": "OPEN", "ci": "failing"}, "needs_testing"),
    ({"state": "OPEN", "ci": "passing", "review_decision": "CHANGES_REQUESTED"}, "changes_requested"),
    ({"state": "OPEN", "ci": "pending"}, "active"),
    ({"state": "OPEN", "ci": "passing", "is_draft": True}, "active"),
    ({"state": "OPEN", "ci": "passing", "review_decision": "APPROVED"}, "approved"),
    ({"state": "OPEN", "ci": "passing", "review_decision": "REVIEW_REQUIRED"}, "needs_review"),
    ({"state": "OPEN", "ci": "passing", "review_decision": ""}, "needs_review"),
    ({"state": "OPEN", "ci": "none", "review_decision": "APPROVED"}, "approved"),
])
def test_classify_pr(mods, pr, expected):
    _, st, _, _ = mods
    assert st.classify_pr(pr).category == expected


def test_failing_ci_beats_changes_requested(mods):
    _, st, _, _ = mods
    v = st.classify_pr({"state": "OPEN", "ci": "failing", "review_decision": "CHANGES_REQUESTED"})
    assert v.category == "needs_testing"  # cheapest-to-fix signal first


def test_status_colors(mods):
    _, st, _, _ = mods
    assert st.status_of("merged_needs_cleanup") == ("merged", "purple")
    assert st.status_of("needs_testing") == ("blocked", "orange")
    assert st.status_of("needs_review") == ("active", "green")


# ---- wiring -----------------------------------------------------------------

def _program_with_work(db, sub_ref="42"):
    prog = db.add_program("demo", framework="ada")
    repo = db.add_repo(prog["id"], "demo", "acme/demo", "/x", "acme/demo", "main")
    role = db.get_role(prog["id"], "ada_agent")
    agent = db.add_agent("pr-42-x")
    db.add_membership(agent["id"], prog["id"], role["id"])
    proj = db.add_project(prog["id"], "Epic", repo_id=repo["id"], forge_ref="100")
    if sub_ref is not None:
        db.add_project_member(proj["id"], agent["id"], sub_ref=sub_ref)
    return prog, repo, agent, proj


def test_for_agent_unassigned_does_not_touch_forge(mods):
    db, st, _, _ = mods
    prog = db.add_program("demo")
    agent = db.add_agent("loner")
    states = st.for_agent(BoomForge(), agent)  # must not call forge
    assert states[0]["category"] == "unassigned"
    assert states[0]["ref"] is None


def test_for_agent_classifies_from_forge(mods):
    db, st, _, _ = mods
    _, _, agent, _ = _program_with_work(db)
    forge = FakeForge(pr={"state": "OPEN", "ci": "passing", "review_decision": "REVIEW_REQUIRED"})
    states = st.for_agent(forge, agent)
    assert states[0]["category"] == "needs_review"
    assert states[0]["ref"] == "42" and states[0]["repo"] == "demo"
    assert states[0]["status"] == "active"


def test_for_agent_retired_is_spun_down(mods):
    db, st, _, _ = mods
    _, _, agent, _ = _program_with_work(db)
    db.retire_agent(agent["id"])
    agent = db.get_agent(agent["id"])
    forge = FakeForge(pr={"state": "OPEN", "ci": "passing", "review_decision": "APPROVED"})
    states = st.for_agent(forge, agent)
    assert states[0]["status"] == "spun_down" and states[0]["color"] == "red"


def test_for_project_rollup_with_kanban(mods):
    db, st, pc, tmp = mods
    prog, repo, agent, proj = _program_with_work(db)
    # authored label->state map, read live
    path, _ = pc.scaffold(tmp / "pam.program.toml", name="demo")
    db.set_program_config_path(prog["id"], str(path))
    proj = db.get_project(proj["id"])
    forge = FakeForge(pr={"state": "OPEN", "ci": "passing", "review_decision": "APPROVED"},
                      labels=["State: In Progress"])
    roll = st.for_project(forge, proj)
    assert roll["kanban"] == "in_progress"
    assert roll["agents"][0]["agent"] == "pr-42-x"
    assert roll["agents"][0]["category"] == "approved"
