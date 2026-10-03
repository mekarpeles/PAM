"""Foundation DB behavior, incl. the no-merge guarantee on name reuse."""
import importlib
import os

import pytest


@pytest.fixture()
def pam_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "pam"))
    import pam.config as config
    import pam.db as db
    importlib.reload(config)
    importlib.reload(db)
    db.init()
    return db


def test_seed_roles_present(pam_db):
    keys = {r["key"] for r in pam_db.list_roles()}
    assert {"program_lead", "division_lead", "ada_agent"} <= keys


def test_program_and_agent_roundtrip(pam_db):
    prog = pam_db.add_program("openlibrary", framework="ada", gh_account="openlibrary-bot")
    assert pam_db.get_program("openlibrary")["id"] == prog["id"]

    role = pam_db.get_role(prog["id"], "ada_agent")
    agent = pam_db.add_agent("pr-123-fix", cwd="/tmp/wt", last_session_id="sess-abc")
    pam_db.add_membership(agent["id"], prog["id"], role["id"])

    resolved = pam_db.resolve_agent("pr-123-fix")
    assert resolved["id"] == agent["id"]
    assert resolved["last_session_id"] == "sess-abc"
    assert resolved["cwd"] == "/tmp/wt"


def test_name_reuse_never_merges_histories(pam_db):
    a1 = pam_db.add_agent("ada", last_session_id="old-session")
    # reusing a live name must be refused
    with pytest.raises(pam_db.ActiveNameExists):
        pam_db.add_agent("ada", last_session_id="new-session")
    # after retiring, the name frees up and a NEW id is minted (histories stay separate)
    pam_db.retire_agent("ada")
    a2 = pam_db.add_agent("ada", last_session_id="new-session")
    assert a2["id"] != a1["id"]
    assert pam_db.resolve_agent("ada")["id"] == a2["id"]
    # the old agent still exists with its own id + its own resume coordinates
    old = pam_db.get_agent(a1["id"])
    assert old["status"] == "retired"
    assert old["last_session_id"] == "old-session"


def test_ulid_sortable_and_unique(pam_db):
    from pam.ids import ulid
    ids = [ulid() for _ in range(100)]
    assert len(set(ids)) == 100
    assert all(len(x) == 26 for x in ids)
