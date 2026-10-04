"""pam projects (list) and pam team (reporting tree with statuses)."""
import importlib
import subprocess

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "home" / ".pam"))
    import pam.config as config
    import pam.db as db
    import pam.activate as activate
    import pam.initializer as initializer
    import pam.cli as cli
    for m in (config, db, activate, initializer, cli):
        importlib.reload(m)
    db.init()
    return config, db, initializer, cli


def _git_repo(path, origin="https://github.com/acme/myrepo.git"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


def test_projects_lists_my_projects(mods, tmp_path, capsys):
    config, db, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))
    assert cli.main(["projects"]) == 0
    assert "myrepo" in capsys.readouterr().out


def test_team_tree_nests_reports_under_their_lead(mods, tmp_path, capsys):
    config, db, initializer, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))
    cli.main(["agent", "onboard", "lead", "--project", "myrepo", "--role", "project_lead"])
    cli.main(["agent", "onboard", "worker", "--project", "myrepo", "--role", "ada_agent",
              "--reports-to", "lead"])

    assert cli.main(["team", "--project", "myrepo"]) == 0
    out = capsys.readouterr().out
    worker_lines = [ln for ln in out.splitlines() if ln.strip().startswith("- worker")]
    lead_lines = [ln for ln in out.splitlines() if ln.strip().startswith("- lead")]
    # worker is nested deeper than its lead
    assert worker_lines and lead_lines
    assert (len(worker_lines[0]) - len(worker_lines[0].lstrip())) > \
           (len(lead_lines[0]) - len(lead_lines[0].lstrip()))
