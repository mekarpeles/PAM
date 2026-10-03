"""Action manifests — declarative Runtime plugins (issue #29).

An action is a `.toml` file in a Program bundle's `actions/` (generic ones ship with PAM). It wires a
trigger to a handler:

    [trigger]                      # exactly one of event | schedule
    event = "issue.assigned"       #   or: schedule = "0 9 * * *"
    match = { label = "Type: Subtask", assignee = "{gh_account}" }

    [handler]                      # exactly one of deliver | spawn | run_skill | run_script
    spawn = { role = "ada_agent", oracle_bundle = "oracle.pr.yml" }

    [guard]
    requires = ["no_running_session"]

    cooldown_h = 4                 # optional; per-action (spawn should not cooldown-suppress)

Pure parsing/loading only — no network, no tmux, no dispatch. The content_hash feeds the Runtime
dedup key so an *edited* action re-fires (review #35).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

HANDLERS = ("deliver", "spawn", "run_skill", "run_script")
DEFAULT_COOLDOWN_H = 4.0


class ActionError(Exception):
    pass


@dataclass
class Action:
    id: str
    trigger_type: str            # 'event' | 'schedule'
    event: str | None
    schedule: str | None
    match: dict
    handler_type: str            # one of HANDLERS
    handler_params: dict
    requires: list
    cooldown_h: float
    content_hash: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def parse_action(data: dict, action_id: str, raw_text: str) -> Action:
    trig = data.get("trigger") or {}
    has_event, has_sched = "event" in trig, "schedule" in trig
    if has_event == has_sched:  # both or neither
        raise ActionError(f"{action_id}: [trigger] must have exactly one of event | schedule")

    handler = data.get("handler") or {}
    hkeys = [k for k in HANDLERS if k in handler]
    if len(hkeys) != 1:
        raise ActionError(
            f"{action_id}: [handler] must have exactly one of {', '.join(HANDLERS)}")
    htype = hkeys[0]
    params = handler.get(htype)
    if not isinstance(params, dict):
        params = {}

    guard = data.get("guard") or {}
    try:
        cooldown = float(data.get("cooldown_h", DEFAULT_COOLDOWN_H))
    except (TypeError, ValueError):
        raise ActionError(f"{action_id}: cooldown_h must be a number")

    return Action(
        id=action_id,
        trigger_type="event" if has_event else "schedule",
        event=trig.get("event"),
        schedule=trig.get("schedule"),
        match=dict(trig.get("match") or {}),
        handler_type=htype,
        handler_params=dict(params),
        requires=list(guard.get("requires") or []),
        cooldown_h=cooldown,
        content_hash=_hash(raw_text),
    )


def load_dir(path) -> dict[str, Action]:
    if tomllib is None:
        raise RuntimeError("tomllib unavailable (needs Python 3.11+)")
    out: dict[str, Action] = {}
    p = Path(path)
    if not p.exists():
        return out
    for f in sorted(p.glob("*.toml")):
        raw = f.read_text()
        try:
            data = tomllib.loads(raw)
        except tomllib.TOMLDecodeError as e:
            raise ActionError(f"{f.stem}: invalid TOML — {e}")
        out[f.stem] = parse_action(data, f.stem, raw)
    return out


def load_actions(bundle_actions_dir, generic_dir=None) -> list[Action]:
    """Load generic actions then bundle actions; a bundle action overrides a generic one by id."""
    merged: dict[str, Action] = {}
    if generic_dir:
        merged.update(load_dir(generic_dir))
    merged.update(load_dir(bundle_actions_dir))
    return list(merged.values())
