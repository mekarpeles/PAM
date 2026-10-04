"""pam spawn: seed the cmux homedir, then `cmux up` from it; dry-run by default, agent self-worktrees."""
import importlib
import subprocess

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "home" / ".pam"))
    monkeypatch.setenv("CMUX_STATE_DIR", str(tmp_path / "cmux"))
    import pam.config as config
    import pam.db as db
    import pam.activate as activate
    import pam.spawn as spawn
    import pam.initializer as initializer
    import pam.cli as cli
    for m in (config, db, activate, spawn, initializer, cli):
        importlib.reload(m)
    db.init()
    return config, db, activate, spawn, initializer, cli


def _git_repo(path, origin="https://github.com/acme/myrepo.git"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


def _project_with_agent(cli, initializer, repo, name="worker", role="ada_agent"):
    initializer.init_project(str(repo))
    cli.main(["agent", "onboard", name, "--project", "myrepo", "--role", role])


# --- pure module ---

def test_seed_home_writes_bootstrap_and_refs(mods, tmp_path):
    _, _, _, spawn, _, _ = mods
    defn = tmp_path / "repo" / ".pam" / "agents" / "worker"
    defn.mkdir(parents=True)
    (defn / "identity.md").write_text("# worker\n")
    home = spawn.seed_home("worker", type_key="ada_agent", project="myrepo",
                           repo_path=str(tmp_path / "repo"),
                           pam_dir=str(tmp_path / "repo" / ".pam"), defn_dir=str(defn),
                           issue="123")
    boot = (home / "AGENTS.md").read_text()
    assert "worker" in boot and "ada_agent" in boot
    assert "worktree" in boot.lower()           # ADA told to make its own worktree
    assert "#123" in boot
    assert (home / "refs.toml").exists()
    assert (home / "identity.md").exists()       # symlinked


def test_non_ada_bootstrap_has_no_worktree_instruction(mods, tmp_path):
    _, _, _, spawn, _, _ = mods
    defn = tmp_path / "r" / ".pam" / "agents" / "lead"
    defn.mkdir(parents=True)
    home = spawn.seed_home("lead", type_key="division_lead", project="p",
                           repo_path=str(tmp_path / "r"), pam_dir=str(tmp_path / "r" / ".pam"),
                           defn_dir=str(defn))
    assert "worktree" not in (home / "AGENTS.md").read_text().lower()


def test_cmux_up_cmd_is_clean_detached(mods):
    _, _, _, spawn, _, _ = mods
    assert spawn.cmux_up_cmd("worker") == ["cmux", "up", "worker", "--no-inject", "-d"]


def test_launch_runs_from_homedir_with_env(mods, tmp_path):
    _, _, activate, spawn, _, _ = mods
    calls = {}

    def fake_runner(cmd, cwd=None, env=None):
        calls["cmd"], calls["cwd"], calls["env"] = cmd, cwd, env
        return subprocess.CompletedProcess(cmd, 0)

    activate.save_settings("myrepo", {"gh_account": "ol-bot"})
    res = spawn.launch("worker", env=activate.env_for("myrepo"), runner=fake_runner)
    assert res.returncode == 0
    assert calls["cmd"][:2] == ["cmux", "up"]
    assert calls["cwd"].endswith("/cmux/worker")          # from the homedir
    assert calls["env"]["GH_CONFIG_DIR"].endswith("/projects/myrepo/gh")


# --- CLI wiring ---

def test_cli_spawn_dry_run_seeds_but_does_not_launch(mods, tmp_path, capsys):
    config, db, activate, spawn, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    _project_with_agent(cli, initializer, repo)

    # guard: if anything tries to launch, blow up
    monkey_called = {"n": 0}
    orig = spawn.launch
    spawn.launch = lambda *a, **k: monkey_called.__setitem__("n", monkey_called["n"] + 1)
    try:
        rc = cli.main(["spawn", "worker", "--project", "myrepo"])
    finally:
        spawn.launch = orig
    assert rc == 0
    assert monkey_called["n"] == 0                          # dry-run never launches
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert (tmp_path / "cmux" / "worker" / "AGENTS.md").exists()


def test_cli_spawn_requires_known_agent(mods, tmp_path):
    config, db, activate, spawn, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))
    with pytest.raises(SystemExit):
        cli.main(["spawn", "ghost", "--project", "myrepo"])
