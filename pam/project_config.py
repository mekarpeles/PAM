"""The authored Project config bundle.

A Project's config (role overrides, the label->state map, Oracle defaults, onboarding recipes, and
pointers to the Project's PM sources) lives as a TOML file IN THE PROJECT'S REPO, version-controlled,
and is read live at call time (never cached in PAM's DB). `pam project init` scaffolds a starter;
`load()` reads it. SQLite holds only recorded facts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def default_path(repo_path: str | Path) -> Path:
    """Default location for a Project's config bundle inside its repo."""
    return Path(repo_path) / ".pam" / "project.toml"


TEMPLATE = """\
# PAM Project config: authored, version-controlled, read live by PAM (never cached).
# Scaffolded by `pam project init`. Edit freely; PAM reads it at call time.

[project]
name = "{name}"
framework = "{framework}"

# Roles beyond PAM's built-ins (project_lead / division_lead / ada_agent).
# Define project-specific agent types here; each can carry an oracle bundle + onboarding recipe.
# [[roles]]
# key = "reviewer"
# title = "Independent Reviewer"
# permissions = []

# How this Project's forge labels map to kanban states (Monitor-mode colors).
[labels.state]
"State: Icebox"      = "icebox"
"State: In Progress" = "in_progress"
"State: Blocked"     = "blocked"
"State: Done"        = "done"

# Which issue label marks an Epic, and how sub-issues reference it.
[epics]
epic_label = "Type: Epic"
subtask_label = "Type: Subtask"

# Oracle defaults for this Project's ADA agents (per-agent overridable).
[oracle]
default_bundle = "oracle.yml"

# Pointers to this Project's PM sources (read live; never mirrored into PAM).
[pm]
# milestone = "current"
# goals_doc = "docs/goals.md"
# objectives_doc = "docs/objectives-{{year}}.md"
"""


def scaffold(path: str | Path, name: str, framework: str = "") -> tuple[Path, bool]:
    """Write a starter config to `path` if absent. Returns (path, created?)."""
    p = Path(path)
    if p.exists():
        return p, False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(TEMPLATE.format(name=name, framework=framework or ""))
    return p, True


def load(path: str | Path) -> Optional[dict]:
    """Read the authored config at call time. Returns None if missing/unreadable."""
    p = Path(path)
    if not p.exists() or tomllib is None:
        return None
    try:
        with p.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError):
        return None
