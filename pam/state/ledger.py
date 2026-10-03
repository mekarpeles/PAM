"""PAM-internal ledger renderer — the `where_are_we` pattern, ported slim from ADA.

A ledger is a list of requirement/finding entries kept in a PR comment:
    - [tested@a1b2c3d] empty feed renders | tests/test_feed.py::test_empty | alice
    - [open] handle pagination
Each entry is `[status]` or `[status@sha]` then `desc | evidence | owner` (evidence/owner optional).

Classification buckets an entry against the PR's live HEAD sha — and is deliberately NON-MONOTONIC:
a rebase un-does `tested`. We never print "done", only "done AS OF <sha>".
    - open     : status is not terminal (still owed)
    - asserted : terminal status but NO evidence (claimed; the world backs nothing) — highest cost
    - stale    : terminal + evidence, but asserted against a non-HEAD commit (unverified, not wrong)
    - done     : terminal + evidence + asserted against HEAD

Pure functions only (parse/classify/summarize) — fully unit-testable, no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

DEFAULT_MARKER = "<!-- ada-ledger -->"
TERMINAL = {"tested", "fixed", "accepted", "done", "verified", "passed"}

_ENTRY = re.compile(
    r"^\s*-\s*\[(?P<status>[a-z]+)(?:@(?P<sha>[0-9a-fA-F]{7,40}))?\]\s*(?P<rest>.+?)\s*$"
)


@dataclass
class Entry:
    status: str
    sha: Optional[str]
    desc: str
    evidence: Optional[str]
    owner: Optional[str]

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


def parse(text: str) -> list[Entry]:
    entries: list[Entry] = []
    for line in (text or "").splitlines():
        m = _ENTRY.match(line)
        if not m:
            continue
        parts = [p.strip() for p in m.group("rest").split("|")]
        desc = parts[0] if parts else ""
        evidence = parts[1] if len(parts) > 1 and parts[1] else None
        owner = parts[2] if len(parts) > 2 and parts[2] else None
        entries.append(Entry(m.group("status"), m.group("sha"), desc, evidence, owner))
    return entries


def stale_against(sha: Optional[str], head: Optional[str]) -> bool:
    """Prefix-compare a stored sha against live HEAD (handles short shas). No sha => never stale."""
    if not sha or not head:
        return False
    n = min(len(sha), len(head))
    return sha[:n].lower() != head[:n].lower()


def bucket(entry: Entry, head: Optional[str]) -> str:
    if not entry.terminal:
        return "open"
    if not entry.evidence:
        return "asserted"
    if entry.sha and stale_against(entry.sha, head):
        return "stale"
    return "done"


def classify(entries: list[Entry], head: Optional[str]) -> dict[str, list[Entry]]:
    out: dict[str, list[Entry]] = {"done": [], "stale": [], "asserted": [], "open": []}
    for e in entries:
        out[bucket(e, head)].append(e)
    return out


def summarize(text: str, head: Optional[str], marker: str = DEFAULT_MARKER) -> dict:
    entries = parse(text)
    b = classify(entries, head)
    counts = {k: len(v) for k, v in b.items()}
    owed = counts["open"] + counts["asserted"] + counts["stale"]
    return {
        "head": head,
        "counts": counts,
        "buckets": b,
        "owed": owed,
        "clean": owed == 0 and counts["done"] > 0,
    }


def extract_ledger(comments, marker: str = DEFAULT_MARKER) -> str:
    """Return the body of the LAST PR comment containing the ledger marker, or ''."""
    found = ""
    for c in comments or []:
        body = c.get("body") if isinstance(c, dict) else str(c)
        if body and marker in body:
            found = body
    return found
