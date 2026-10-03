"""Forge adapters — read a Program's issue tracker/forge (GitHub first).

Cheap `gh`/REST signal gathering (PR state, CI, review decision, labels) behind a small tracker
abstraction keyed off `programs.tracker`. Used to compute project kanban state (labels) and ADA-agent
state. Dependency-free and tmux-free; the command runner is injectable for testing.
"""
from __future__ import annotations

from .github import ForgeError, GitHubForge  # noqa: F401

__all__ = ["get_forge", "GitHubForge", "ForgeError"]


def get_forge(tracker: str = "github", run=None):
    if tracker == "github":
        return GitHubForge(run=run)
    raise ValueError(f"unsupported tracker: {tracker!r}")
