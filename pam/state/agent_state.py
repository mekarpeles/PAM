"""Compute an agent's work state and a project's rollup from forge signals.

Scope (issue #11): a principled, ordered classifier over the forge PR signals the adapter already
gathers (state, CI, review decision, draft). This is the cheap "where are we" — deliberately NOT a
monotonic "% done". The richer picture (current Oracle stage + ledger buckets) layers on later; this
module is forge-signals-only and says so.

The classifier is a pure function (classify_pr) so every branch is unit-testable without network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .. import db, program_config


@dataclass
class Verdict:
    category: str
    reason: str


# category -> (status label, color). Colors follow Mek's Monitor scheme.
_STATUS = {
    "merged_needs_cleanup": ("merged", "purple"),
    "closed":               ("spun_down", "red"),
    "needs_testing":        ("blocked", "orange"),
    "changes_requested":    ("blocked", "orange"),
    "needs_review":         ("active", "green"),
    "approved":             ("active", "green"),
    "active":               ("active", "green"),
    "unassigned":           ("idle", "grey"),
    "no_ref":               ("idle", "grey"),
}


def status_of(category: str) -> tuple[str, str]:
    return _STATUS.get(category, ("active", "green"))


def classify_pr(pr: dict) -> Verdict:
    """Ordered priority cascade over forge PR signals. Each branch is a real, checkable signal."""
    state = (pr.get("state") or "").upper()
    if state == "MERGED":
        return Verdict("merged_needs_cleanup", "PR merged — teardown")
    if state == "CLOSED":
        return Verdict("closed", "PR closed")
    # state OPEN below
    ci = pr.get("ci")                                   # failing | pending | passing | none
    review = (pr.get("review_decision") or "").upper()  # '', APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED
    if ci == "failing":
        return Verdict("needs_testing", "CI failing")
    if review == "CHANGES_REQUESTED":
        return Verdict("changes_requested", "review requested changes")
    if ci == "pending":
        return Verdict("active", "CI running")
    if pr.get("is_draft"):
        return Verdict("active", "draft in progress")
    if review == "APPROVED":
        return Verdict("approved", "approved — awaiting merge")
    if review in ("", "REVIEW_REQUIRED"):
        return Verdict("needs_review", "ready — awaiting review")
    return Verdict("active", "in progress")


def _render(category, reason, agent_status=None):
    if agent_status == "retired":
        label, color = "spun_down", "red"
    else:
        label, color = status_of(category)
    return {"category": category, "reason": reason, "status": label, "color": color}


def for_agent(forge, agent: dict) -> list[dict]:
    """Return one state entry per active piece of work the agent owns (via project_members)."""
    work = db.agent_work(agent["id"])
    if not work:
        return [{"project": None, "repo": None, "ref": None,
                 **_render("unassigned", "no active assignment", agent["status"])}]
    out = []
    for w in work:
        ref, repo_url = w["sub_ref"], w["repo_url"]
        if not ref or not repo_url:
            v = Verdict("no_ref", "assigned, no PR ref")
        else:
            v = classify_pr(forge.pr(repo_url, ref))
        out.append({"project": w["title"], "repo": w["repo_name"], "ref": ref,
                    **_render(v.category, v.reason, agent["status"])})
    return out


def for_project(forge, project: dict) -> dict:
    """Project rollup: the epic's kanban state (labels->state) + each member agent's state."""
    members = db.list_project_members(project["id"])
    repo = db.get_repo(project["repo_id"]) if project.get("repo_id") else None
    kanban = None
    if repo and project.get("forge_ref"):
        mapping = _label_state_map(project["program_id"])
        from ..forge.github import kanban_state
        labels = forge.issue_labels(repo["repo_url"], project["forge_ref"])
        kanban = kanban_state(labels, mapping)
    agents = []
    for m in members:
        if m["sub_ref"] and repo:
            v = classify_pr(forge.pr(repo["repo_url"], m["sub_ref"]))
        else:
            v = Verdict("no_ref", "no PR ref")
        agents.append({"agent": m["agent_name"], "ref": m["sub_ref"],
                       **_render(v.category, v.reason, m["agent_status"])})
    return {"project": project["title"], "forge_ref": project.get("forge_ref"),
            "kanban": kanban, "agents": agents}


def _label_state_map(program_id) -> dict:
    """Read the Program's authored label->state map at call time (never cached)."""
    prog = db.get_program(program_id)
    if not prog or not prog.get("config_path"):
        return {}
    cfg = program_config.load(prog["config_path"])
    if not cfg:
        return {}
    return (cfg.get("labels", {}) or {}).get("state", {}) or {}
