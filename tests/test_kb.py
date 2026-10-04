"""pam kb: the Project's knowledge base pointer in .pam/kb.toml, obsidian-style, standalone-valuable."""
import importlib
import subprocess

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "home" / ".pam"))
    import pam.config as config
    import pam.db as db
    import pam.kb as kb
    import pam.initializer as initializer
    import pam.cli as cli
    for m in (config, db, kb, initializer, cli):
        importlib.reload(m)
    db.init()
    return config, db, kb, initializer, cli


def _git_repo(path, origin="https://github.com/acme/myrepo.git"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


# --- pure module ---

def test_default_location_scaffolds_local_kb(mods, tmp_path):
    _, _, kb, _, _ = mods
    pam_dir = tmp_path / "repo" / ".pam"
    pam_dir.mkdir(parents=True)
    path, scaffolded = kb.set_location(pam_dir)   # default .pam/kb
    assert scaffolded is True
    assert kb.load(pam_dir)["kb"]["location"] == ".pam/kb"
    kbdir = tmp_path / "repo" / ".pam" / "kb"
    assert (kbdir / "README.md").exists()
    assert "[[wikilinks]]" in (kbdir / "README.md").read_text()


def test_external_url_sets_pointer_without_scaffolding(mods, tmp_path):
    _, _, kb, _, _ = mods
    pam_dir = tmp_path / "repo" / ".pam"
    pam_dir.mkdir(parents=True)
    path, scaffolded = kb.set_location(pam_dir, "https://github.com/acme/kb.git")
    assert scaffolded is False
    assert kb.load(pam_dir)["kb"]["location"] == "https://github.com/acme/kb.git"
    assert not (tmp_path / "repo" / ".pam" / "kb").exists()


def test_is_local_classification(mods):
    _, _, kb, _, _ = mods
    assert kb.is_local(".pam/kb") and kb.is_local("/abs/path")
    assert not kb.is_local("https://x/y.git")
    assert not kb.is_local("git@github.com:a/b.git")


# --- CLI wiring ---

def test_cli_kb_set_and_show(mods, tmp_path):
    config, db, kb, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))

    assert cli.main(["kb", "set", "--project", "myrepo"]) == 0
    assert (repo / ".pam" / "kb.toml").exists()
    assert (repo / ".pam" / "kb" / "README.md").exists()
    assert cli.main(["kb", "show", "--project", "myrepo"]) == 0
