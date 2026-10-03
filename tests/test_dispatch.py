"""Dispatch interface + liveness rule (pure; no network, no tmux)."""
from pam.runtime.dispatch import (
    DispatchAdapter,
    NoopDispatcher,
    resolve_dispatch,
)


def test_resolve_dispatch_liveness_rule():
    assert resolve_dispatch("alive").action == "deliver"
    assert resolve_dispatch("idle").action == "deliver"
    assert resolve_dispatch("dead").action == "spawn_then_deliver"
    assert resolve_dispatch("unknown").action == "refuse"
    # any unrecognized health is treated as unknown: refuse, never silently deliver
    assert resolve_dispatch("weird").action == "refuse"


def test_noop_dispatcher_records_but_does_nothing():
    d = NoopDispatcher(health_map={"a1": "alive"})
    assert d.health("a1") == "alive"
    assert d.health("missing") == "unknown"        # safe default
    d.deliver("a1", "hello")
    sid = d.spawn("a2", {"model": "x"})
    assert sid == "noop-session"
    assert d.calls == [("deliver", "a1", "hello"), ("spawn", "a2")]


def test_noop_dispatcher_satisfies_protocol():
    assert isinstance(NoopDispatcher(), DispatchAdapter)
