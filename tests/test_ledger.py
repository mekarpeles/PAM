"""ADA's ledger engine (adopted proven version) — parse, classify, escalation validation."""
from pam.agents.ada import ledger as L
from pam.agents.ada import where_are_we as W

M = L.MARKER


def test_parse_uses_last_block_only():
    text = f"""
    stray chatter, not a ledger
    {M}
    - [open] from an older ledger block
    <!-- some other comment -->
    {M}
    - [tested@a1b2c3d4] empty feed renders | tests/test_feed.py::test_empty | alice
    - [open] handle pagination
    """
    entries = L.parse(text)
    assert [e.status for e in entries] == ["tested", "open"]   # only the last block
    assert entries[0].sha == "a1b2c3d4"
    assert entries[0].evidence == "tests/test_feed.py::test_empty"
    assert entries[0].owner == "alice"


def test_no_marker_is_empty():
    assert L.parse("there is no ledger here") == []


def test_stale_against_prefix():
    e = L.Entry(status="tested", description="x", evidence="ev", owner="", line_no=1, sha="a1b2c3d")
    assert e.stale_against("a1b2c3d4e5") is False
    assert e.stale_against("ffffffff") is True
    req = L.Entry(status="open", description="x", evidence="", owner="", line_no=1, sha="")
    assert req.stale_against("abc") is False   # no sha, a requirement is never stale


def test_classify_four_buckets():
    head = "a1b2c3d4"
    entries = L.parse(f"""{M}
    - [tested@a1b2c3d4] a | ev
    - [tested@deadbee] b | ev
    - [accepted] c
    - [open] d
    """)
    b = W.classify(entries, head)
    assert [e.description for e in b["done"]] == ["a"]
    assert [e.description for e in b["stale"]] == ["b"]        # evidence, but non-HEAD sha
    assert [e.description for e in b["asserted"]] == ["c"]     # terminal, no evidence
    assert [e.description for e in b["open"]] == ["d"]


def test_escalation_validation():
    bad = L.parse(f"{M}\n- [escalated] need a human call |")
    assert bad[0].escalation_problem                           # missing kind/searched
    ok = L.parse(f"{M}\n- [escalated] harden now? | kind:decision searched:issues,docs | mek")
    assert ok[0].escalation_problem == ""
    unfinished = L.parse(f"{M}\n- [escalated] x | kind:unfinished searched:docs")
    assert "not an escalation" in unfinished[0].escalation_problem


def test_undischarged():
    entries = L.parse(f"""{M}
    - [tested] a | ev
    - [tested] b
    - [open] c
    """)
    assert [e.description for e in L.undischarged(entries)] == ["b", "c"]
