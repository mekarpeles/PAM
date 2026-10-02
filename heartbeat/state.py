"""Idle-intuition + "don't re-ask" state machine.

The direct one-level-up analogue of claudio's own `nudges` feature: track *when* a signal last
materially changed, not a poll clock, and never re-surface the same unresolved thing on every
run just because time passed.

Persisted as a small JSON file (see DEFAULT_STATE_PATH) -- deliberately NOT the shared fleet
cq registry, to avoid any risk of this in-development code writing into state AdaDash or
another live agent depends on. Relocating this is an open decision (README #1/#3).

Lifecycle per agent, keyed by (agent, category, signal_hash):
  new       -- first time this exact (category, signal) combination has been seen -> worth
               surfacing once.
  repeat    -- same (category, signal) as last check -- nothing changed, do NOT re-surface.
  changed   -- category or signal changed since last check (e.g. agent replied, or CI flipped)
               -- worth a fresh look, but that is `taxonomy.categorize()`'s job, not this
               module's; this module just says "yes, this is new information."
  cooldown  -- same (category, signal), but enough time has passed that a periodic reminder is
               legitimate (e.g. a `blocked_on_human` PR that's been waiting three days --
               surfacing it again after a real cooldown is not nagging, it's a standup).

This module intentionally has NO opinion on wording or on whether to actually send anything --
see heartbeat.py for the dry-run report, and README's "Explicit safety boundary" for why
dispatch is not implemented in this session.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

DEFAULT_STATE_PATH = os.path.join(os.path.dirname(__file__), 'state.json')

# How long a `new` surfacing must age before it's eligible to be raised again as a `cooldown`
# reminder, if still unresolved. Deliberately much longer than claudio's 900s agent-nudge
# default -- see README Open Decision #2. 24h: roughly "once a day, not once a poll".
DEFAULT_COOLDOWN_H = 24.0

NUDGE_WORTHY = {
    'no_agent_assigned', 'open_architectural_question', 'blocked_on_human',
    'exhausted_own_progress', 'needs_splitting', 'merged_needs_cleanup', 'unregistered_agent',
    # Same shape as merged_needs_cleanup: an operational problem the agent
    # cannot fix for itself, because it cannot see its own worktree. Omitting
    # it would be a regression rather than a no-op -- these agents were
    # previously exhausted_own_progress, which is nudge-worthy, so naming
    # their cause would have made them quieter instead of clearer.
    'no_resolvable_worktree',
    # Decisive rather than diagnostic: an agent working a closed issue is
    # doing nothing, and nobody finds that out unless it is surfaced.
    'effort_closed',
}


def signal_hash(category: str, reason: str) -> str:
    """A short, stable fingerprint of "what's actually being said" -- category alone is not
    enough (two different blocked_on_human reasons on the same agent, minutes apart, are the
    same situation; category plus a truncated, normalized reason distinguishes real changes
    from noise like a changing hour-count in the reason string itself).
    """
    normalized = category + '|' + _strip_volatile_numbers(reason)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _strip_volatile_numbers(text: str) -> str:
    """Reason strings often embed "idle 4.3h" -- strip the number so hash stability doesn't
    depend on catching the collector at the exact same minute twice."""
    import re
    return re.sub(r'\d+(\.\d+)?', '#', text)


@dataclass
class AgentState:
    category: str
    hash: str
    first_seen: str  # ISO
    last_seen: str  # ISO
    last_surfaced: Optional[str] = None  # ISO, None if never surfaced
    surface_count: int = 0

    def to_json(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_json(cls, d: dict) -> 'AgentState':
        return cls(**d)


class HeartbeatState:
    def __init__(self, path: str = DEFAULT_STATE_PATH):
        self.path = path
        self._data: dict[str, AgentState] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}
        self._data = {k: AgentState.from_json(v) for k, v in raw.items()}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({k: v.to_json() for k, v in self._data.items()}, f, indent=2)
        os.replace(tmp, self.path)  # atomic, unlike collect.py's peers-style bare write

    def evaluate(
        self, agent: str, category: str, reason: str, *,
        now: Optional[datetime] = None, cooldown_h: float = DEFAULT_COOLDOWN_H,
    ) -> str:
        """Returns one of: 'new', 'repeat', 'changed', 'cooldown', 'not_nudge_worthy'.

        Updates internal state (call .save() after a batch of evaluate() calls, not per-call,
        so a crash mid-run doesn't leave partial writes -- see heartbeat.py's main loop).
        """
        now = now or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        h = signal_hash(category, reason)
        prior = self._data.get(agent)

        if category not in NUDGE_WORTHY:
            # Still record it (so first_seen survives), but explicitly do NOT set
            # last_surfaced -- an agent that's merely 'active' or mid-'needs_testing' has never
            # actually been surfaced to the Operator, so the *next* nudge-worthy category it enters must
            # read as 'new', not 'changed'. See test_transition_into_nudge_worthy_from_quiet_history_is_new.
            self._data[agent] = AgentState(category=category, hash=h,
                                            first_seen=prior.first_seen if prior else now_iso,
                                            last_seen=now_iso,
                                            last_surfaced=None,
                                            surface_count=prior.surface_count if prior else 0)
            return 'not_nudge_worthy'

        was_surfaced_before = prior is not None and prior.last_surfaced is not None
        if not was_surfaced_before or prior.hash != h:
            self._data[agent] = AgentState(
                category=category, hash=h,
                first_seen=prior.first_seen if prior else now_iso,
                last_seen=now_iso, last_surfaced=now_iso,
                surface_count=(prior.surface_count if prior else 0) + 1)
            return 'changed' if was_surfaced_before else 'new'

        # Same category+hash as last time.
        prior.last_seen = now_iso
        if prior.last_surfaced is None:
            prior.last_surfaced = now_iso
            prior.surface_count += 1
            return 'new'

        last_surfaced_dt = datetime.fromisoformat(prior.last_surfaced)
        age_h = (now - last_surfaced_dt).total_seconds() / 3600.0
        if age_h >= cooldown_h:
            prior.last_surfaced = now_iso
            prior.surface_count += 1
            return 'cooldown'
        return 'repeat'

    def get(self, agent: str) -> Optional[AgentState]:
        return self._data.get(agent)

    def acknowledge(self, agent: str) -> None:
        """the Operator (or Ada, on his explicit word) has seen this and it's handled for now --
        resets last_surfaced to now without changing the hash, so it won't re-surface until
        either something changes or a fresh cooldown elapses."""
        if agent in self._data:
            self._data[agent].last_surfaced = datetime.now(timezone.utc).isoformat()
