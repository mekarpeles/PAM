"""GitHub forge adapter — cheap, read-only signal gathering via the `gh` CLI.

Generalized from openlibrary-pam's new_pr_bot.py. Dependency-free (shells `gh`) and tmux-free. The
command runner is injectable so this is fully testable without network: pass `run=` a callable
`(args) -> (returncode, stdout, stderr)`. Pure helpers (classify_ci, normalize_pr, kanban_state) are
separated so parsing is unit-testable with fixture JSON.
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable, Optional

# CI conclusions that count as a real failure (cancelled/neutral/skipped do NOT).
CI_FAILING = {"FAILURE", "ERROR", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
# Fleet/infra check names that are not real CI (excluded from the CI verdict).
INFRA_CHECKS = {"assign", "respond", "changes_requested"}


class ForgeError(Exception):
    pass


def _default_run(args, timeout: int = 30):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


# ---- pure helpers (unit-testable) -------------------------------------------

def classify_ci(status_check_rollup, infra=INFRA_CHECKS, failing=CI_FAILING) -> str:
    """-> 'failing' | 'pending' | 'passing' | 'none' from a gh statusCheckRollup list."""
    if not status_check_rollup:
        return "none"
    saw_pending = saw_pass = False
    for c in status_check_rollup:
        name = (c.get("name") or c.get("context") or "").strip()
        if name in infra:
            continue
        # CheckRun: status/conclusion; StatusContext: state
        status = (c.get("status") or "").upper()
        conclusion = (c.get("conclusion") or "").upper()
        state = (c.get("state") or "").upper()
        if conclusion in failing or state in ("FAILURE", "ERROR"):
            return "failing"
        if status in ("QUEUED", "IN_PROGRESS", "PENDING", "WAITING") or state == "PENDING":
            saw_pending = True
        elif conclusion in ("SUCCESS",) or state == "SUCCESS":
            saw_pass = True
    if saw_pending:
        return "pending"
    if saw_pass:
        return "passing"
    return "none"


def _label_names(labels) -> list[str]:
    out = []
    for lb in labels or []:
        out.append(lb["name"] if isinstance(lb, dict) else lb)
    return out


def normalize_pr(raw: dict) -> dict:
    """Normalize a `gh pr view --json ...` payload into a stable signal dict."""
    return {
        "number": raw.get("number"),
        "title": raw.get("title"),
        "state": raw.get("state"),            # OPEN | MERGED | CLOSED
        "is_draft": raw.get("isDraft"),
        "review_decision": raw.get("reviewDecision") or None,  # '', APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED
        "ci": classify_ci(raw.get("statusCheckRollup")),
        "additions": raw.get("additions"),
        "deletions": raw.get("deletions"),
        "files": len(raw.get("files") or []) if raw.get("files") is not None else None,
        "head_sha": raw.get("headRefOid"),
        "labels": _label_names(raw.get("labels")),
        "mergeable": raw.get("mergeable"),
    }


def normalize_issue(raw: dict) -> dict:
    return {
        "number": raw.get("number"),
        "title": raw.get("title"),
        "state": raw.get("state"),            # OPEN | CLOSED
        "labels": _label_names(raw.get("labels")),
        "assignees": [a.get("login") if isinstance(a, dict) else a
                      for a in (raw.get("assignees") or [])],
    }


def kanban_state(labels, mapping: dict) -> Optional[str]:
    """Map forge labels -> a Program's kanban state via the Program's label->state map."""
    for lb in labels or []:
        if lb in mapping:
            return mapping[lb]
    return None


# ---- the adapter ------------------------------------------------------------

class GitHubForge:
    tracker = "github"

    def __init__(self, run: Optional[Callable] = None):
        self._run = run or _default_run

    def _json(self, args):
        rc, out, err = self._run(args)
        if rc != 0:
            raise ForgeError((err or "").strip() or f"gh {' '.join(args)} failed ({rc})")
        return json.loads(out) if (out or "").strip() else None

    _PR_FIELDS = ("state,isDraft,reviewDecision,statusCheckRollup,additions,"
                  "deletions,files,headRefOid,labels,title,mergeable,number")
    _ISSUE_FIELDS = "state,labels,title,assignees,number"

    def pr(self, repo: str, number) -> dict:
        d = self._json(["pr", "view", str(number), "--repo", repo, "--json", self._PR_FIELDS])
        return normalize_pr(d or {})

    def issue(self, repo: str, number) -> dict:
        d = self._json(["issue", "view", str(number), "--repo", repo, "--json", self._ISSUE_FIELDS])
        return normalize_issue(d or {})

    def issue_labels(self, repo: str, number) -> list[str]:
        return self.issue(repo, number)["labels"]

    def pr_comments(self, repo: str, number) -> list[dict]:
        d = self._json(["pr", "view", str(number), "--repo", repo, "--json", "comments"])
        return (d or {}).get("comments", [])

    def list_issues(self, repo: str, state: str = "open", limit: int = 50) -> list[dict]:
        d = self._json(["issue", "list", "--repo", repo, "--state", state,
                        "--limit", str(limit), "--json", self._ISSUE_FIELDS])
        return [normalize_issue(x) for x in (d or [])]
