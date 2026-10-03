"""Filesystem locations for PAM's recorded state.

Everything is under PAM_HOME (default ~/.pam). The DB holds recorded facts; agent homes hold the
durable per-agent files. The *authored* Project config bundle does NOT live here; it lives in the
Project's own repo and is read at call time (see config_path on the projects table).
"""
from __future__ import annotations

import os
from pathlib import Path


def pam_home() -> Path:
    return Path(os.environ.get("PAM_HOME", str(Path.home() / ".pam")))


def db_path() -> Path:
    return pam_home() / "pam.db"


def agents_dir() -> Path:
    return pam_home() / "agents"


def projects_dir() -> Path:
    return pam_home() / "projects"


def project_dir(name: str) -> Path:
    """Per-developer, per-Project private settings dir (the virtualenv half)."""
    return projects_dir() / name


def active_marker() -> Path:
    """File holding the name of the currently activated Project (per developer)."""
    return pam_home() / "active"
