"""Read-only git helpers for verifying that a registered path is bound to the expected repo.

A registration is a bound path: `pam program add` checks the path's `origin` remote against the
declared repo and refuses on mismatch (a binding was silently re-pointed to a different repo of the
same name once). Re-checked at spawn via `pam verify-binding`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def origin(path: str | Path) -> Optional[str]:
    """Return the `origin` remote URL of the git repo at `path`, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def normalize(url: str) -> str:
    """Normalize a git URL to `owner/name`, lowercased, for comparison across https/ssh forms."""
    u = url.strip()
    if u.endswith(".git"):
        u = u[: -len(".git")]
    for prefix in (
        "https://github.com/", "http://github.com/",
        "git@github.com:", "ssh://git@github.com/",
    ):
        if u.startswith(prefix):
            u = u[len(prefix):]
            break
    return u.lower().strip("/")


def same_repo(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


def current_branch(path: str | Path) -> str:
    """Current branch name at `path`, or 'main' if it cannot be read."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "main"
    except Exception:
        return "main"
