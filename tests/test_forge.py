"""Forge adapter: pure signal parsing + an injected gh runner (no network)."""
import json

from pam.forge import get_forge
from pam.forge.github import classify_ci, kanban_state, normalize_pr


def test_classify_ci_states():
    assert classify_ci(None) == "none"
    assert classify_ci([]) == "none"
    assert classify_ci([{"name": "ci", "conclusion": "SUCCESS"}]) == "passing"
    assert classify_ci([{"name": "ci", "conclusion": "FAILURE"}]) == "failing"
    assert classify_ci([{"name": "ci", "status": "IN_PROGRESS"}]) == "pending"
    # a real failure dominates a pass
    assert classify_ci([{"name": "a", "conclusion": "SUCCESS"},
                        {"name": "b", "conclusion": "ERROR"}]) == "failing"
    # cancelled/neutral is not a failure
    assert classify_ci([{"name": "a", "conclusion": "CANCELLED"},
                        {"name": "b", "conclusion": "SUCCESS"}]) == "passing"
    # infra checks are excluded from the verdict
    assert classify_ci([{"name": "assign", "conclusion": "FAILURE"},
                        {"name": "ci", "conclusion": "SUCCESS"}]) == "passing"
    # StatusContext style (state field)
    assert classify_ci([{"context": "legacy", "state": "FAILURE"}]) == "failing"


def test_normalize_pr():
    raw = {
        "number": 42, "title": "Fix", "state": "OPEN", "isDraft": True,
        "reviewDecision": "CHANGES_REQUESTED",
        "statusCheckRollup": [{"name": "ci", "conclusion": "SUCCESS"}],
        "additions": 10, "deletions": 2, "files": [{"path": "a"}, {"path": "b"}],
        "headRefOid": "abc123", "labels": [{"name": "Type: Subtask"}], "mergeable": "MERGEABLE",
    }
    pr = normalize_pr(raw)
    assert pr["state"] == "OPEN" and pr["is_draft"] is True
    assert pr["ci"] == "passing"
    assert pr["review_decision"] == "CHANGES_REQUESTED"
    assert pr["files"] == 2
    assert pr["labels"] == ["Type: Subtask"]
    assert pr["head_sha"] == "abc123"


def test_kanban_state():
    mapping = {"State: Done": "done", "State: Blocked": "blocked"}
    assert kanban_state(["State: Blocked", "x"], mapping) == "blocked"
    assert kanban_state(["x"], mapping) is None


def test_github_forge_with_injected_runner():
    calls = []

    def fake_run(args):
        calls.append(args)
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({
                "number": 7, "state": "OPEN", "isDraft": False,
                "reviewDecision": "APPROVED",
                "statusCheckRollup": [{"name": "ci", "conclusion": "SUCCESS"}],
                "labels": [], "files": [], "headRefOid": "deadbeef", "title": "t",
            }), ""
        return 1, "", "unexpected"

    forge = get_forge("github", run=fake_run)
    pr = forge.pr("owner/repo", 7)
    assert pr["number"] == 7 and pr["ci"] == "passing" and pr["review_decision"] == "APPROVED"
    assert calls[0][0:3] == ["pr", "view", "7"]
    assert "--repo" in calls[0] and "owner/repo" in calls[0]


def test_unsupported_tracker():
    import pytest
    with pytest.raises(ValueError):
        get_forge("jira")
