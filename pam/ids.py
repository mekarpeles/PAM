"""ULID generation — stdlib only (no third-party dependency).

A ULID is a 26-char Crockford-base32 string: 48 bits of millisecond timestamp + 80 bits of
randomness. Lexicographically sortable by creation time, collision-free without coordination, and
independent of any display name — which is why PAM uses it as the immutable agent/program id while
the human-facing name stays a reusable label.
"""
from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I, L, O, U)


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


def ulid(now_ms: int | None = None) -> str:
    """Return a new 26-char ULID. `now_ms` overrides the timestamp (for tests)."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    ts = _encode(now_ms, 10)  # 48 bits -> 10 chars
    rand = _encode(int.from_bytes(os.urandom(10), "big"), 16)  # 80 bits -> 16 chars
    return ts + rand
