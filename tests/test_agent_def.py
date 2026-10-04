"""Authored agent definitions: onboard writes a committed .pam/agents/<name>/, not a ~/.pam home."""
import importlib
import subprocess

import pytest


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("PAM_HOME", str(tmp_path / "home" / ".pam"))
    import pam.config as config
    import pam.db as db
    import pam.initializer as initializer
    import pam.agent_def as agent_def
    import pam.cli as cli
    for m in (config, db, initializer, agent_def, cli):
        importlib.reload(m)
    db.init()
    return config, db, initializer, agent_def, cli


def _git_repo(path, origin="https://github.com/acme/myrepo.git"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


# --- pure module ---

def test_scaffold_writes_agent_toml_and_identity(tmp_path):
    import pam.agent_def as agent_def
    d, created = agent_def.scaffold(tmp_path / ".pam", name="coordinator",
                                    uuid="01TESTID", type_key="project_lead",
                                    reports_to="")
    assert created is True
    assert d == tmp_path / ".pam" / "agents" / "coordinator"
    toml = (d / "agent.toml").read_text()
    assert 'name = "coordinator"' in toml
    assert 'uuid = "01TESTID"' in toml
    assert 'type = "project_lead"' in toml
    assert (d / "identity.md").exists()


def test_ada_identity_links_package_manual(tmp_path):
    import pam.agent_def as agent_def
    d, _ = agent_def.scaffold(tmp_path / ".pam", name="ada-1", uuid="01A",
                              type_key="ada_agent")
    body = (d / "identity.md").read_text()
    assert "@link pam/agents/ada/AGENTS.md" in body


def test_type_without_manual_gets_stub_not_link(tmp_path):
    import pam.agent_def as agent_def
    assert agent_def.type_def_link("project_lead") is None
    d, _ = agent_def.scaffold(tmp_path / ".pam", name="lead", uuid="01L",
                              type_key="project_lead")
    body = (d / "identity.md").read_text()
    assert "@link" not in body
    assert "No canonical manual" in body


def test_scaffold_records_can_onboard_and_orders(tmp_path):
    import pam.agent_def as agent_def
    orders = tmp_path / "orders.md"
    orders.write_text("# marching orders\nunblock the import pipeline\n")
    d, _ = agent_def.scaffold(tmp_path / ".pam", name="lenny-lead", uuid="01L",
                              type_key="division_lead", can_onboard=True, orders_src=str(orders))
    toml = (d / "agent.toml").read_text()
    assert "can_onboard = true" in toml
    assert 'orders = "orders.md"' in toml
    assert "unblock the import pipeline" in (d / "orders.md").read_text()


def test_scaffold_defaults_can_onboard_false_no_orders(tmp_path):
    import pam.agent_def as agent_def
    d, _ = agent_def.scaffold(tmp_path / ".pam", name="w", uuid="01W", type_key="ada_agent")
    toml = (d / "agent.toml").read_text()
    assert "can_onboard = false" in toml
    assert "orders" not in toml
    assert not (d / "orders.md").exists()


def test_scaffold_is_idempotent_and_preserves_edits(tmp_path):
    import pam.agent_def as agent_def
    d, _ = agent_def.scaffold(tmp_path / ".pam", name="a", uuid="01A", type_key="agent")
    (d / "identity.md").write_text("# a\n\nhand-edited\n")
    d2, created = agent_def.scaffold(tmp_path / ".pam", name="a", uuid="01A", type_key="agent")
    assert created is False and d2 == d
    assert "hand-edited" in (d / "identity.md").read_text()


# --- onboard wiring (drive the CLI in-process) ---

def test_onboard_writes_definition_and_no_home_dir(mods, tmp_path):
    config, db, initializer, agent_def, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))

    rc = cli.main(["agent", "onboard", "coordinator", "--project", "myrepo",
                   "--role", "project_lead"])
    assert rc == 0

    # committed definition landed in the repo's .pam/
    adef = repo / ".pam" / "agents" / "coordinator" / "agent.toml"
    assert adef.exists()
    agent = db.get_agent("coordinator")
    assert f'uuid = "{agent["id"]}"' in adef.read_text()

    # onboard did NOT create a ~/.pam agent home directory
    assert not (config.agents_dir() / agent["id"]).exists()


def test_cli_onboard_type_alias_and_can_onboard(mods, tmp_path):
    config, db, initializer, agent_def, cli = mods
    repo = tmp_path / "myrepo"
    _git_repo(repo)
    initializer.init_project(str(repo))

    rc = cli.main(["agent", "onboard", "lenny", "--project", "myrepo",
                   "--type", "division_lead", "--can-onboard=true"])
    assert rc == 0
    toml = (repo / ".pam" / "agents" / "lenny" / "agent.toml").read_text()
    assert 'type = "division_lead"' in toml
    assert "can_onboard = true" in toml
