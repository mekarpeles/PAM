"""The PAM Runtime — the event->action execution layer (see docs/runtime-design.md).

The decision core here is pure and tmux-free: it loads actions, matches triggers, and produces a
plan. Dry-run by default; real dispatch is an injected DispatchAdapter at the cmux seam, built later
and gated behind --dispatch (and the #39-#42 blockers). This package never imports cmux.
"""
from .actions import Action, ActionError, DEFAULT_COOLDOWN_H, load_actions  # noqa: F401
from .decide import Fire, decide, matches, plan, signature  # noqa: F401
from .dispatch import DispatchAdapter, Intent, NoopDispatcher, resolve_dispatch  # noqa: F401

__all__ = [
    "Action", "ActionError", "DEFAULT_COOLDOWN_H", "load_actions",
    "Fire", "plan", "matches", "signature", "decide",
    "DispatchAdapter", "Intent", "NoopDispatcher", "resolve_dispatch",
]
