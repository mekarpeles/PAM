"""Phase 2: projects, memberships, teams, and the authored Program config."""
import importlib

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


def _program_with_lead(db):
    prog = db.add_program("demo", framework="ada")
    lead_role = db.get_role(prog["id"], "division_lead")
    lead = db.add_agent("lenny-lead")
    db.add_membership(lead["id"], prog["id"], lead_role["id"])
    return prog, lead


def test_project_add_assign_and_members(pam_db):
    prog, lead = _program_with_lead(pam_db)
    lm = pam_db.membership_of("lenny-lead", prog["id"])
    proj = pam_db.add_project(prog["id"], "Tags epic", forge_ref="13755",
                              owner_id=lm["id"], year=2026)
    worker = pam_db.add_agent("pr-13163-tags")
    pam_db.add_project_member(proj["id"], worker["id"], sub_ref="13163", staffed_by=lead["id"])

    members = pam_db.list_project_members(proj["id"])
    assert [m["agent_name"] for m in members] == ["pr-13163-tags"]
    assert members[0]["sub_ref"] == "13163"
    assert pam_db.get_project("Tags epic", program_id=prog["id"])["id"] == proj["id"]
    assert pam_db.list_projects(program_id=prog["id"], year=2026)


def test_teams(pam_db):
    prog = pam_db.add_program("demo")
    t = pam_db.add_team(prog["id"], "frontend")
    assert pam_db.get_team(prog["id"], "frontend")["id"] == t["id"]
    assert [x["name"] for x in pam_db.list_teams(prog["id"])] == ["frontend"]


def test_reporting_edge(pam_db):
    prog = pam_db.add_program("demo")
    pl = pam_db.add_agent("pam")
    pl_role = pam_db.get_role(prog["id"], "program_lead")
    pam_db.add_membership(pl["id"], prog["id"], pl_role["id"])
    boss = pam_db.membership_of("pam", prog["id"])

    dl = pam_db.add_agent("dash-lead")
    dl_role = pam_db.get_role(prog["id"], "division_lead")
    m = pam_db.add_membership(dl["id"], prog["id"], dl_role["id"], reports_to_id=boss["id"])
    assert m["reports_to_id"] == boss["id"]


def test_role_permits(pam_db):
    prog = pam_db.add_program("demo")
    assert pam_db.role_permits(pam_db.get_role(prog["id"], "program_lead"), "manage_program")
    assert not pam_db.role_permits(pam_db.get_role(prog["id"], "ada_agent"), "manage_program")


def test_program_config_scaffold_and_load(tmp_path):
    import pam.program_config as pc
    path = tmp_path / "pam.program.toml"
    p, created = pc.scaffold(path, name="demo", framework="ada")
    assert created and p.exists()
    # idempotent
    _, created2 = pc.scaffold(path, name="demo")
    assert not created2
    cfg = pc.load(path)
    assert cfg["program"]["name"] == "demo"
    assert cfg["labels"]["state"]["State: Done"] == "done"
