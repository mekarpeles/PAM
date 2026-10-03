"""Dispatch interface and the liveness decision (pure part of issue #30).

The decision core produces a plan (fires). Turning a fire into a real effect goes through a
DispatchAdapter, injected at the cmux seam. This module defines that interface, a dry-run no-op
adapter (so the Runtime runs fully without tmux), and the pure liveness rule that decides, per agent
health, whether to deliver, respawn-then-deliver, or refuse-and-surface.

It performs no real dispatch. The live execution path (calling adapter.deliver/spawn, recording the
fire) is gated behind --dispatch and the blockers B1 to B4 (#39 to #42). This module never imports cmux.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

# agent health values a DispatchAdapter may report
ALIVE, IDLE, DEAD, UNKNOWN = "alive", "idle", "dead", "unknown"


@runtime_checkable
class DispatchAdapter(Protocol):
    def health(self, agent_id: str) -> str: ...
    def deliver(self, agent_id: str, message: str) -> None: ...
    def spawn(self, agent_id: str, launch_spec: dict) -> str: ...


@dataclass
class Intent:
    """What a fire resolves to once the target agent's health is known. No execution here."""
    action: str   # 'deliver' | 'spawn_then_deliver' | 'refuse'
    reason: str


def resolve_dispatch(health: str) -> Intent:
    """The liveness rule from the design: deliver when live, respawn when dead, refuse when unknown."""
    if health in (ALIVE, IDLE):
        return Intent("deliver", f"agent {health}")
    if health == DEAD:
        return Intent("spawn_then_deliver", "agent dead; respawn and rehydrate from launch_spec")
    return Intent("refuse", f"health '{health}'; refuse and surface (never silently void)")


class NoopDispatcher:
    """Dry-run adapter: records intended calls, performs nothing. Keeps the Runtime tmux-free.

    `health_map` lets a caller simulate agent health in tests and dry-runs; unknown by default so the
    safe path (refuse and surface) is the default rather than a silent delivery.
    """

    def __init__(self, health_map: Optional[dict] = None):
        self.health_map = dict(health_map or {})
        self.calls: list[tuple] = []

    def health(self, agent_id: str) -> str:
        return self.health_map.get(agent_id, UNKNOWN)

    def deliver(self, agent_id: str, message: str) -> None:
        self.calls.append(("deliver", agent_id, message))

    def spawn(self, agent_id: str, launch_spec: dict) -> str:
        self.calls.append(("spawn", agent_id))
        return "noop-session"
