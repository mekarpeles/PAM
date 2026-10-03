"""PAM-internal ledger renderer — pure parse/classify/summarize (no network)."""
from pam.state import ledger as L


def test_parse_variants():
    text = """
    noise line, ignored
    - [tested@a1b2c3d4] empty feed renders | tests/test_feed.py::test_empty | alice
    - [open] handle pagination
    - [accepted] design approved
    not a bullet
    """
    entries = L.parse(text)
    assert [e.status for e in entries] == ["tested", "open", "accepted"]
    assert entries[0].sha == "a1b2c3d4"
    assert entries[0].evidence == "tests/test_feed.py::test_empty"
    assert entries[0].owner == "alice"
    assert entries[1].sha is None and entries[1].evidence is None


def test_stale_against_prefix():
    assert L.stale_against("a1b2c3d", "a1b2c3d4e5") is False   # prefix match
    assert L.stale_against("a1b2c3d", "ffffffff") is True
    assert L.stale_against(None, "abc") is False               # a requirement is never stale
    assert L.stale_against("abc", None) is False


def test_bucket_each_case():
    head = "a1b2c3d4"
    # terminal + evidence + sha == head -> done
    assert L.bucket(L.Entry("tested", "a1b2c3d4", "x", "ev", None), head) == "done"
    # terminal + evidence + no sha -> done (nothing says it's stale)
    assert L.bucket(L.Entry("tested", None, "x", "ev", None), head) == "done"
    # terminal + evidence + stale sha -> stale
    assert L.bucket(L.Entry("tested", "deadbee", "x", "ev", None), head) == "stale"
    # terminal + NO evidence -> asserted
    assert L.bucket(L.Entry("tested", "a1b2c3d4", "x", None, None), head) == "asserted"
    # non-terminal -> open
    assert L.bucket(L.Entry("open", None, "x", None, None), head) == "open"


def test_summarize_counts_and_clean():
    head = "a1b2c3d4"
    text = "\n".join([
        "- [tested@a1b2c3d4] a | ev",       # done
        "- [tested@deadbee] b | ev",        # stale
        "- [accepted] c",                   # asserted (terminal, no evidence)
        "- [open] d",                       # open
    ])
    s = L.summarize(text, head)
    assert s["counts"] == {"done": 1, "stale": 1, "asserted": 1, "open": 1}
    assert s["owed"] == 3
    assert s["clean"] is False


def test_summarize_clean():
    head = "a1b2c3d4"
    s = L.summarize("- [tested@a1b2c3d4] a | ev", head)
    assert s["clean"] is True and s["owed"] == 0


def test_extract_ledger_picks_last_marked_comment():
    comments = [
        {"body": "just a comment"},
        {"body": L.DEFAULT_MARKER + "\n- [open] old"},
        {"body": L.DEFAULT_MARKER + "\n- [tested@abc1234] new | ev"},
        {"body": "trailing chatter"},
    ]
    text = L.extract_ledger(comments)
    assert "new" in text and "old" not in text
    assert L.extract_ledger([{"body": "no marker"}]) == ""
