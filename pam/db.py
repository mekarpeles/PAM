"""PAM registry — SQLite storage for *recorded* state only.

Generalizes cmux's agents.db (WAL, per-key upserts). Holds who exists, memberships, parentage,
projects, assignments, asserted phase. Never stores the authored config bundle (that is read live
from the Program's repo). This module MUST NOT import cmux.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from . import config
from .ids import ulid


class ActiveNameExists(Exception):
    """Raised when onboarding a name that already belongs to a live (active) agent."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS programs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    framework   TEXT,
    tracker     TEXT NOT NULL DEFAULT 'github',
    gh_account  TEXT,
    config_path TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repos (
    id             TEXT PRIMARY KEY,
    program_id     TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    repo_url       TEXT NOT NULL,
    path           TEXT NOT NULL,
    origin         TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    created_at     TEXT NOT NULL,
    UNIQUE(program_id, name)
);

CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    cwd             TEXT,
    last_session_id TEXT,
    identity_path   TEXT,
    home_path       TEXT,
    no_inject       INTEGER NOT NULL DEFAULT 0,
    unblock         INTEGER NOT NULL DEFAULT 0,
    allowed_tools   TEXT,
    launch_spec     TEXT,                 -- JSON: full relaunch spec (model, mcp-config, settings,
                                          --   add-dir, permission-mode, agent, …). `claude --resume`
                                          --   does NOT restore these unless re-passed; id+cwd alone
                                          --   brings an agent back subtly different.
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL,
    retired_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_agent_per_name
    ON agents(name) WHERE status='active';

CREATE TABLE IF NOT EXISTS teams (
    id          TEXT PRIMARY KEY,
    program_id  TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(program_id, name)
);

CREATE TABLE IF NOT EXISTS roles (
    id          TEXT PRIMARY KEY,
    program_id  TEXT NOT NULL DEFAULT '',   -- '' = built-in seed role (not program-scoped)
    key         TEXT NOT NULL,
    title       TEXT,
    description TEXT,
    permissions TEXT NOT NULL DEFAULT '[]', -- JSON array
    config      TEXT NOT NULL DEFAULT '{}', -- JSON object
    created_at  TEXT NOT NULL,
    UNIQUE(program_id, key)
);

CREATE TABLE IF NOT EXISTS memberships (
    id            TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    program_id    TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    role_id       TEXT NOT NULL REFERENCES roles(id),
    team_id       TEXT REFERENCES teams(id),
    reports_to_id TEXT REFERENCES memberships(id),
    config        TEXT NOT NULL DEFAULT '{}',
    joined_at     TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    UNIQUE(agent_id, program_id)
);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    program_id  TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    repo_id     TEXT REFERENCES repos(id),
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'epic',
    forge_ref   TEXT,
    owner_id    TEXT REFERENCES memberships(id),
    year        INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_members (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id    TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    sub_ref     TEXT,
    staffed_by  TEXT REFERENCES agents(id),
    staffed_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, agent_id)
);

CREATE TABLE IF NOT EXISTS phase_assertions (
    id           TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    project_id   TEXT REFERENCES projects(id),
    repo_id      TEXT REFERENCES repos(id),
    phase        TEXT NOT NULL,
    asserted_sha TEXT,
    asserted_at  TEXT NOT NULL,
    evidence     TEXT,
    created_at   TEXT NOT NULL
);

-- Runtime dedup/cooldown: one row per (action, subject). An action fires only when the signature
-- is new or changed, or the per-action cooldown has elapsed (see docs/runtime-design.md).
CREATE TABLE IF NOT EXISTS runtime_fires (
    action_id     TEXT NOT NULL,
    subject_ref   TEXT NOT NULL,
    signature     TEXT,
    last_fired_at TEXT,
    fire_count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (action_id, subject_ref)
);
"""

# key, title, description, permissions, config
SEED_ROLES = [
    ("program_lead", "Program Lead",
     "Owns the Program: settings, docs, configuration; allocates reviewers; settles inter-lead disputes.",
     ["manage_program", "manage_projects", "onboard_agents", "allocate_reviewers"], {}),
    ("division_lead", "Division / Project Lead",
     "Domain expert and project manager for a set of Projects; unblocks agents as a consultant.",
     ["manage_projects", "onboard_agents"], {}),
    ("ada_agent", "ADA agent",
     "Atomic agent that owns one PR end to end (issue -> PR -> review -> merge -> cleanup).",
     [], {"oracle_bundle": "oracle.yml", "onboarding_recipe": "ada"}),
    ("agent", "Agent",
     "A general-purpose team member that is not the atomic development agent.",
     [], {}),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(r: sqlite3.Row | None) -> Optional[dict]:
    return dict(r) if r is not None else None


def connect() -> sqlite3.Connection:
    p = config.db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn) -> None:
    """Additive, never-reorder column migrations for existing DBs (the cmux agents.db pattern)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
    if "launch_spec" not in cols:
        conn.execute("ALTER TABLE agents ADD COLUMN launch_spec TEXT")


def init() -> None:
    """Create the schema (idempotent), migrate, and seed the built-in roles."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        for key, title, desc, perms, cfg in SEED_ROLES:
            if not conn.execute(
                "SELECT 1 FROM roles WHERE program_id='' AND key=?", (key,)
            ).fetchone():
                conn.execute(
                    "INSERT INTO roles(id,program_id,key,title,description,permissions,config,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (ulid(), "", key, title, desc, json.dumps(perms), json.dumps(cfg), _now()),
                )
        conn.commit()
    finally:
        conn.close()


# ---- programs & repos -------------------------------------------------------

def add_program(name, framework=None, tracker="github", gh_account=None, config_path=None) -> dict:
    conn = connect()
    try:
        pid = ulid()
        conn.execute(
            "INSERT INTO programs(id,name,framework,tracker,gh_account,config_path,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (pid, name, framework, tracker, gh_account, config_path, _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM programs WHERE id=?", (pid,)).fetchone())
    finally:
        conn.close()


def get_program(ref) -> Optional[dict]:
    conn = connect()
    try:
        return _row(conn.execute(
            "SELECT * FROM programs WHERE id=? OR name=?", (ref, ref)
        ).fetchone())
    finally:
        conn.close()


def list_programs() -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM programs ORDER BY created_at"
        ).fetchall()]
    finally:
        conn.close()


def add_repo(program_id, name, repo_url, path, origin, default_branch="main") -> dict:
    conn = connect()
    try:
        rid = ulid()
        conn.execute(
            "INSERT INTO repos(id,program_id,name,repo_url,path,origin,default_branch,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (rid, program_id, name, repo_url, path, origin, default_branch, _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone())
    finally:
        conn.close()


def list_repos(program_id) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM repos WHERE program_id=? ORDER BY name", (program_id,)
        ).fetchall()]
    finally:
        conn.close()


def get_repo(repo_id) -> Optional[dict]:
    conn = connect()
    try:
        return _row(conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone())
    finally:
        conn.close()


def get_repo_by_path(path) -> Optional[dict]:
    conn = connect()
    try:
        return _row(conn.execute("SELECT * FROM repos WHERE path=?", (path,)).fetchone())
    finally:
        conn.close()


# ---- roles ------------------------------------------------------------------

def get_role(program_id, key) -> Optional[dict]:
    """Program-scoped role wins over a built-in seed role of the same key."""
    conn = connect()
    try:
        r = conn.execute(
            "SELECT * FROM roles WHERE program_id=? AND key=?", (program_id, key)
        ).fetchone()
        if r is None:
            r = conn.execute(
                "SELECT * FROM roles WHERE program_id='' AND key=?", (key,)
            ).fetchone()
        return _row(r)
    finally:
        conn.close()


def add_role(program_id, key, title=None, description=None,
             permissions=None, config=None) -> dict:
    """Create a program-scoped role (program_id='' would be a built-in seed)."""
    conn = connect()
    try:
        if isinstance(permissions, (list, dict)):
            permissions = json.dumps(permissions)
        if isinstance(config, (list, dict)):
            config = json.dumps(config)
        rid = ulid()
        conn.execute(
            "INSERT INTO roles(id,program_id,key,title,description,permissions,config,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (rid, program_id, key, title, description,
             permissions or "[]", config or "{}", _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM roles WHERE id=?", (rid,)).fetchone())
    finally:
        conn.close()


def list_roles(program_id=None) -> list[dict]:
    conn = connect()
    try:
        if program_id:
            rows = conn.execute(
                "SELECT * FROM roles WHERE program_id IN ('', ?) ORDER BY program_id, key",
                (program_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM roles ORDER BY program_id, key").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---- agents -----------------------------------------------------------------

def add_agent(name, cwd=None, last_session_id=None, identity_path=None,
              home_path=None, no_inject=0, unblock=0, allowed_tools=None,
              launch_spec=None) -> dict:
    conn = connect()
    try:
        if conn.execute(
            "SELECT 1 FROM agents WHERE name=? AND status='active'", (name,)
        ).fetchone():
            raise ActiveNameExists(name)
        aid = ulid()
        if home_path is None:
            home_path = str(config.agents_dir() / aid)
        if launch_spec is not None and not isinstance(launch_spec, str):
            launch_spec = json.dumps(launch_spec)
        conn.execute(
            "INSERT INTO agents(id,name,cwd,last_session_id,identity_path,home_path,"
            "no_inject,unblock,allowed_tools,launch_spec,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?, 'active', ?)",
            (aid, name, cwd, last_session_id, identity_path, home_path,
             int(no_inject), int(unblock), allowed_tools, launch_spec, _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM agents WHERE id=?", (aid,)).fetchone())
    finally:
        conn.close()


def get_agent(ref, active_only=False) -> Optional[dict]:
    conn = connect()
    try:
        if active_only:
            r = conn.execute(
                "SELECT * FROM agents WHERE (id=? OR name=?) AND status='active'", (ref, ref)
            ).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM agents WHERE id=? OR name=? ORDER BY created_at DESC", (ref, ref)
            ).fetchone()
        return _row(r)
    finally:
        conn.close()


def resolve_agent(name) -> Optional[dict]:
    """Name -> the one ACTIVE agent (id + resume coordinates). The name->id seam PAM owns."""
    conn = connect()
    try:
        return _row(conn.execute(
            "SELECT id, name, last_session_id, cwd, home_path FROM agents"
            " WHERE name=? AND status='active'", (name,)
        ).fetchone())
    finally:
        conn.close()


def list_agents(active_only=True) -> list[dict]:
    conn = connect()
    try:
        q = "SELECT * FROM agents"
        if active_only:
            q += " WHERE status='active'"
        q += " ORDER BY created_at"
        return [dict(r) for r in conn.execute(q).fetchall()]
    finally:
        conn.close()


def retire_agent(ref) -> Optional[dict]:
    conn = connect()
    try:
        a = conn.execute(
            "SELECT * FROM agents WHERE (id=? OR name=?) AND status='active'", (ref, ref)
        ).fetchone()
        if a is None:
            return None
        conn.execute(
            "UPDATE agents SET status='retired', retired_at=? WHERE id=?", (_now(), a["id"])
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM agents WHERE id=?", (a["id"],)).fetchone())
    finally:
        conn.close()


# ---- memberships ------------------------------------------------------------

def add_membership(agent_id, program_id, role_id, team_id=None,
                   reports_to_id=None, config_json=None) -> dict:
    conn = connect()
    try:
        mid = ulid()
        conn.execute(
            "INSERT INTO memberships(id,agent_id,program_id,role_id,team_id,reports_to_id,"
            "config,joined_at,active) VALUES(?,?,?,?,?,?,?,?,1)",
            (mid, agent_id, program_id, role_id, team_id, reports_to_id,
             config_json or "{}", _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM memberships WHERE id=?", (mid,)).fetchone())
    finally:
        conn.close()


def membership_of(agent_ref, program_id) -> Optional[dict]:
    conn = connect()
    try:
        return _row(conn.execute(
            "SELECT m.* FROM memberships m JOIN agents a ON a.id=m.agent_id"
            " WHERE (a.id=? OR a.name=?) AND m.program_id=? AND m.active=1",
            (agent_ref, agent_ref, program_id),
        ).fetchone())
    finally:
        conn.close()


def list_memberships(program_id) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT m.*, a.name AS agent_name, r.key AS role_key, r.title AS role_title"
            " FROM memberships m"
            " JOIN agents a ON a.id=m.agent_id"
            " JOIN roles  r ON r.id=m.role_id"
            " WHERE m.program_id=? AND m.active=1 AND a.status='active'"
            " ORDER BY r.key, a.name",
            (program_id,),
        ).fetchall()]
    finally:
        conn.close()


# ---- projects ---------------------------------------------------------------

def add_project(program_id, title, repo_id=None, kind="epic",
                forge_ref=None, owner_id=None, year=None) -> dict:
    conn = connect()
    try:
        pid = ulid()
        conn.execute(
            "INSERT INTO projects(id,program_id,repo_id,title,kind,forge_ref,owner_id,year,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (pid, program_id, repo_id, title, kind, forge_ref, owner_id, year, _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    finally:
        conn.close()


def list_projects(program_id=None, year=None) -> list[dict]:
    conn = connect()
    try:
        q, params = "SELECT * FROM projects", []
        clauses = []
        if program_id:
            clauses.append("program_id=?"); params.append(program_id)
        if year:
            clauses.append("year=?"); params.append(year)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at"
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def get_project(ref, program_id=None) -> Optional[dict]:
    conn = connect()
    try:
        if program_id:
            r = conn.execute(
                "SELECT * FROM projects WHERE (id=? OR title=?) AND program_id=?",
                (ref, ref, program_id),
            ).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM projects WHERE id=? OR title=?", (ref, ref)
            ).fetchone()
        return _row(r)
    finally:
        conn.close()


def add_project_member(project_id, agent_id, sub_ref=None, staffed_by=None) -> dict:
    conn = connect()
    try:
        mid = ulid()
        conn.execute(
            "INSERT INTO project_members(id,project_id,agent_id,sub_ref,staffed_by,staffed_at,active)"
            " VALUES(?,?,?,?,?,?,1)",
            (mid, project_id, agent_id, sub_ref, staffed_by, _now()),
        )
        conn.commit()
        return _row(conn.execute(
            "SELECT * FROM project_members WHERE id=?", (mid,)).fetchone())
    finally:
        conn.close()


def list_project_members(project_id) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT pm.*, a.name AS agent_name, a.status AS agent_status"
            " FROM project_members pm JOIN agents a ON a.id=pm.agent_id"
            " WHERE pm.project_id=? AND pm.active=1 ORDER BY a.name",
            (project_id,),
        ).fetchall()]
    finally:
        conn.close()


def agent_work(agent_id) -> list[dict]:
    """Active work an agent owns: each project_member joined to its project + repo."""
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT pm.sub_ref, p.id AS project_id, p.title, p.forge_ref, p.program_id,"
            " r.name AS repo_name, r.repo_url"
            " FROM project_members pm"
            " JOIN projects p ON p.id=pm.project_id"
            " LEFT JOIN repos r ON r.id=p.repo_id"
            " WHERE pm.agent_id=? AND pm.active=1",
            (agent_id,),
        ).fetchall()]
    finally:
        conn.close()


# ---- teams ------------------------------------------------------------------

def add_team(program_id, name) -> dict:
    conn = connect()
    try:
        tid = ulid()
        conn.execute(
            "INSERT INTO teams(id,program_id,name,created_at) VALUES(?,?,?,?)",
            (tid, program_id, name, _now()),
        )
        conn.commit()
        return _row(conn.execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone())
    finally:
        conn.close()


def get_team(program_id, name) -> Optional[dict]:
    conn = connect()
    try:
        return _row(conn.execute(
            "SELECT * FROM teams WHERE program_id=? AND (id=? OR name=?)",
            (program_id, name, name),
        ).fetchone())
    finally:
        conn.close()


def list_teams(program_id) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM teams WHERE program_id=? ORDER BY name", (program_id,)
        ).fetchall()]
    finally:
        conn.close()


# ---- misc -------------------------------------------------------------------

def set_program_config_path(program_id, config_path) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE programs SET config_path=? WHERE id=?", (config_path, program_id))
        conn.commit()
    finally:
        conn.close()


def role_permits(role: dict, permission: str) -> bool:
    """Advisory permission check. Roles carry a JSON array of permissions."""
    try:
        perms = json.loads(role.get("permissions") or "[]")
    except (ValueError, TypeError):
        perms = []
    return permission in perms


# ---- runtime dedup ----------------------------------------------------------

def get_fire(action_id, subject_ref) -> Optional[dict]:
    conn = connect()
    try:
        return _row(conn.execute(
            "SELECT * FROM runtime_fires WHERE action_id=? AND subject_ref=?",
            (action_id, subject_ref),
        ).fetchone())
    finally:
        conn.close()


def record_fire(action_id, subject_ref, signature) -> None:
    """Record that an action fired for a subject (dispatch-time; not called during dry-run)."""
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO runtime_fires(action_id, subject_ref, signature, last_fired_at, fire_count)"
            " VALUES(?,?,?,?,1)"
            " ON CONFLICT(action_id, subject_ref) DO UPDATE SET"
            " signature=excluded.signature, last_fired_at=excluded.last_fired_at,"
            " fire_count=runtime_fires.fire_count+1",
            (action_id, subject_ref, signature, _now()),
        )
        conn.commit()
    finally:
        conn.close()
