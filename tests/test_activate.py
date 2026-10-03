"""pam activate: per-dev, per-Project identity + env (virtualenv model), no credentials stored."""
import importlib
import subprocess

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "home" / ".pam"))
    # keep the host's env clean of these during the test
    for k in ("GH_CONFIG_DIR", "GIT_AUTHOR_NAME", "PAM_ACTIVE_PROJECT"):
        monkeypatch.delenv(k, raising=False)
    import pam.config as config
    import pam.db as db
    import pam.activate as activate
    import pam.initializer as initializer
    import pam.cli as cli
    for m in (config, db, activate, initializer, cli):
        importlib.reload(m)
    db.init()
    return config, db, activate, initializer, cli


def _git_repo(path, origin="https://github.com/acme/myrepo.git"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


# --- pure module ---

def test_settings_roundtrip_and_merge(mods):
    _, _, activate, _, _ = mods
    activate.save_settings("demo", {"gh_account": "ol-bot"})
    activate.save_settings("demo", {"git_email": "bot@acme.dev"})   # merge, not clobber
    ident = activate.load_settings("demo")["identity"]
    assert ident["gh_account"] == "ol-bot"
    assert ident["git_email"] == "bot@acme.dev"


def test_env_for_points_gh_config_dir_no_tokens(mods):
    config, _, activate, _, _ = mods
    activate.save_settings("demo", {"git_name": "OL Bot", "git_email": "bot@acme.dev"})
    env = activate.env_for("demo")
    assert env["PAM_ACTIVE_PROJECT"] == "demo"
    assert env["GH_CONFIG_DIR"].endswith("/projects/demo/gh")
    assert env["GIT_AUTHOR_NAME"] == "OL Bot" and env["GIT_COMMITTER_EMAIL"] == "bot@acme.dev"
    # no credential/token is ever written into settings
    assert "token" not in activate.settings_path("demo").read_text().lower()


def test_active_marker_set_get_clear(mods):
    _, _, activate, _, _ = mods
    assert activate.get_active() is None
    activate.set_active("demo")
    assert activate.get_active() == "demo"
    activate.clear_active()
    assert activate.get_active() is None


def test_export_lines_are_shell_exports(mods):
    _, _, activate, _, _ = mods
    activate.save_settings("demo", {})
    out = activate.export_lines("demo")
    assert out.startswith("export ")
    assert 'export GH_CONFIG_DIR="' in out


# --- CLI wiring ---

def test_cli_activate_sets_active_and_writes_settings(mods, tmp_path):
    config, db, activate, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))

    rc = cli.main(["activate", "myrepo", "--as", "ol-bot"])
    assert rc == 0
    assert activate.get_active() == "myrepo"
    assert activate.load_settings("myrepo")["identity"]["gh_account"] == "ol-bot"


def test_cli_activate_export_prints_only_exports(mods, tmp_path, capsys):
    config, db, activate, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))

    cli.main(["activate", "myrepo", "--export"])
    out = capsys.readouterr().out
    assert out.strip()
    for line in out.strip().splitlines():
        assert line.startswith("export ")      # nothing but exports on stdout


def test_cli_deactivate_clears(mods, tmp_path):
    config, db, activate, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))
    cli.main(["activate", "myrepo"])
    cli.main(["deactivate"])
    assert activate.get_active() is None
