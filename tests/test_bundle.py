"""Program publish/install: authored config is shared, recorded state is not."""
import importlib

import pytest


@pytest.fixture()
def pam(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "pam"))
    import pam.config as config
    import pam.db as db
    import pam.bundle as bundle
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(bundle)
    db.init()
    return db, bundle, tmp_path


def _seed(db):
    prog = db.add_program("demo", framework="ada", gh_account="demo-bot")
    db.add_repo(prog["id"], name="demo", repo_url="acme/demo", path="/local/demo",
                origin="acme/demo", default_branch="main")
    db.add_role(prog["id"], "reviewer", title="Reviewer", description="independent review",
                permissions=["review"], config={})
    # recorded state that must NOT be published:
    agent = db.add_agent("worker-1", last_session_id="sess-xyz")
    role = db.get_role(prog["id"], "ada_agent")
    db.add_membership(agent["id"], prog["id"], role["id"])
    return prog


def test_publish_excludes_recorded_state(pam):
    db, bundle, tmp = pam
    _seed(db)
    out = bundle.publish("demo", out_dir=str(tmp / "pam-demo"))
    text = (out / bundle.MANIFEST).read_text()
    assert "[program]" in text and 'name = "demo"' in text
    assert "acme/demo" in text          # repo url shared
    assert "reviewer" in text           # program-scoped role shared
    # recorded state must be absent:
    assert "worker-1" not in text
    assert "sess-xyz" not in text
    assert "/local/demo" not in text    # local path is a binding, not shared
    m = bundle.build_manifest("demo")
    assert "agents" not in m and "memberships" not in m


def test_install_roundtrip_creates_fresh_program(pam):
    db, bundle, tmp = pam
    _seed(db)
    out = bundle.publish("demo", out_dir=str(tmp / "pam-demo"))

    before = len(db.list_agents())
    prog2 = bundle.install(str(out), name="demo2",
                           repo_paths={"demo": "/elsewhere/demo"}, gh_account="my-bot")
    assert db.get_program("demo2")["id"] == prog2["id"]
    assert [r["name"] for r in db.list_repos(prog2["id"])] == ["demo"]
    assert db.list_repos(prog2["id"])[0]["path"] == "/elsewhere/demo"  # bound locally
    assert any(r["key"] == "reviewer" for r in db.list_roles(prog2["id"]))
    # install creates NO agents/memberships — you staff your own
    assert len(db.list_agents()) == before
    assert db.list_memberships(prog2["id"]) == []


def test_install_requires_repo_paths(pam):
    db, bundle, tmp = pam
    _seed(db)
    out = bundle.publish("demo", out_dir=str(tmp / "pam-demo"))
    with pytest.raises(ValueError, match="missing --repo-path"):
        bundle.install(str(out), name="demo3")


def test_install_refuses_duplicate_name(pam):
    db, bundle, tmp = pam
    _seed(db)
    out = bundle.publish("demo", out_dir=str(tmp / "pam-demo"))
    with pytest.raises(ValueError, match="already exists"):
        bundle.install(str(out), repo_paths={"demo": "/x"})
