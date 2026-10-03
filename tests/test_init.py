"""pam init: create .pam/ in a repo, register the Program, bind the repo, load if present."""
import importlib
import subprocess

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "home" / ".pam"))
    import pam.config as config
    import pam.db as db
    import pam.initializer as initializer
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(initializer)
    db.init()
    return db, initializer


def _git_repo(path, origin="https://github.com/acme/myrepo.git"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


def test_init_creates_program_and_binds_repo(mods, tmp_path):
    db, initializer = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)

    r = initializer.init_program(str(repo))
    assert r["loaded"] is False
    assert (repo / ".pam" / "program.toml").exists()

    prog = db.get_program("myrepo")
    assert prog is not None and prog["tracker"] == "github"
    assert prog["config_path"].endswith(".pam/program.toml")
    repos = db.list_repos(prog["id"])
    assert len(repos) == 1 and repos[0]["path"] == str(repo.resolve())
    assert repos[0]["origin"] == "https://github.com/acme/myrepo.git"


def test_init_is_idempotent_loads_existing(mods, tmp_path):
    db, initializer = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)

    first = initializer.init_program(str(repo))
    second = initializer.init_program(str(repo))
    assert second["loaded"] is True
    assert second["program"]["id"] == first["program"]["id"]
    # no duplicate Program or repo rows
    assert len([p for p in db.list_programs() if p["name"] == "myrepo"]) == 1
    assert len(db.list_repos(first["program"]["id"])) == 1


def test_init_refuses_non_repo(mods, tmp_path):
    db, initializer = mods
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ValueError, match="not a git repo"):
        initializer.init_program(str(plain))


def test_generic_agent_role_seeded(mods):
    db, _ = mods
    assert any(r["key"] == "agent" for r in db.list_roles())
