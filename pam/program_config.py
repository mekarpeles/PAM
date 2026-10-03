"""The authored Program config bundle.

A Program's config — role overrides, the label->state map, Oracle defaults, onboarding recipes, and
pointers to the Program's PM sources — lives as a TOML file IN THE PROGRAM'S REPO, version-controlled,
and is read live at call time (never cached in PAM's DB). `pam program init` scaffolds a starter;
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
    """Default location for a Program's config bundle inside its repo."""
    return Path(repo_path) / "pam.program.toml"


TEMPLATE = """\
# PAM Program config — authored, version-controlled, read live by PAM (never cached).
# Scaffolded by `pam program init`. Edit freely; PAM reads it at call time.

[program]
name = "{name}"
framework = "{framework}"

# Roles beyond PAM's built-ins (program_lead / division_lead / ada_agent).
# Define program-specific agent types here; each can carry an oracle bundle + onboarding recipe.
# [[roles]]
# key = "reviewer"
# title = "Independent Reviewer"
# permissions = []

# How this Program's forge labels map to kanban states (Monitor-mode colors).
[labels.state]
"State: Icebox"      = "icebox"
"State: In Progress" = "in_progress"
"State: Blocked"     = "blocked"
"State: Done"        = "done"

# Which issue label marks a Project/epic, and how sub-issues reference it.
[projects]
epic_label = "Type: Epic"
subtask_label = "Type: Subtask"

# Oracle defaults for this Program's ADA agents (per-agent overridable).
[oracle]
default_bundle = "oracle.yml"

# Pointers to this Program's PM sources (read live; never mirrored into PAM).
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
