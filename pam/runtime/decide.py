"""Runtime decision core (issue #28) — match actions to subjects, compute a dry-run plan.

Pure and side-effect-free: it reads action manifests + subject signals + the last-fire record and
returns a plan (the fires it WOULD dispatch). It never dispatches and never writes — recording a fire
is the dispatcher's job (the live, gated path), so two dry-runs are identical.

Dedup (review #35): an action fires only when its signature is new or changed, or its per-action
cooldown has elapsed (verdicts new/changed/repeat/cooldown, from the heartbeat model). The signature
covers the subject's material state AND the action's content_hash, so an edited action re-fires.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

# subject signals that count as "material state" for dedup (plus labels, plus the action version)
_SIG_FIELDS = ("event", "state", "category", "review_decision", "ci")


@dataclass
class Fire:
    action_id: str
    subject_ref: str
    handler_type: str
    handler_params: dict
    verdict: str          # 'new' | 'changed' | 'repeat'
    signature: str


def _parse_ts(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _subject_ref(subject: dict) -> str:
    for k in ("subject_ref", "ref", "number"):
        if subject.get(k) is not None:
            return str(subject[k])
    return ""


def matches(action, subject: dict) -> bool:
    """Does the action's trigger apply to this subject? Pure."""
    if action.trigger_type == "event" and action.event:
        ev = subject.get("event")
        if ev is not None and ev != action.event:
            return False
    for k, v in action.match.items():
        if k == "label":  # singular key means "has this label"
            if v not in (subject.get("labels") or []):
                return False
        else:
            sv = subject.get(k)
            if isinstance(sv, (list, tuple, set)):
                if v not in sv:
                    return False
            elif sv != v:
                return False
    return True


def signature(action, subject: dict) -> str:
    """Stable hash of the subject's material state + the action's content_hash."""
    rel = {k: subject.get(k) for k in _SIG_FIELDS if k in subject}
    if "labels" in subject:
        rel["labels"] = sorted(subject["labels"])
    payload = json.dumps([sorted(rel.items()), action.content_hash], default=str, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def decide(action, sig: str, last: Optional[dict], now: datetime) -> tuple[bool, str]:
    """-> (fire?, verdict). new/changed fire; same-sig fires only once the cooldown has elapsed."""
    if last is None:
        return True, "new"
    if last.get("signature") != sig:
        return True, "changed"
    fired = _parse_ts(last.get("last_fired_at"))
    if fired is None:
        return True, "repeat"
    elapsed_h = (now - fired).total_seconds() / 3600.0
    if elapsed_h >= action.cooldown_h:
        return True, "repeat"
    return False, "cooldown"


def plan(actions, subjects, last_fire: Callable[[str, str], Optional[dict]],
         now: Optional[datetime] = None) -> list[Fire]:
    """Compute the dry-run plan: the fires that WOULD dispatch. No writes, no dispatch."""
    now = now or datetime.now(timezone.utc)
    fires: list[Fire] = []
    for action in actions:
        for subject in subjects:
            if not matches(action, subject):
                continue
            ref = _subject_ref(subject)
            sig = signature(action, subject)
            do_fire, verdict = decide(action, sig, last_fire(action.id, ref), now)
            if do_fire:
                fires.append(Fire(action.id, ref, action.handler_type,
                                  dict(action.handler_params), verdict, sig))
    return fires
