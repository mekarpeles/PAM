"""`pam init` core: make a repo agent-workable, the way `git init` makes it versioned.

Run in a repo, it creates `.pam/` in that repo (the authored Project config, committed and shared),
registers the Project in the per-developer Store (~/.pam), infers the issue tracker from the origin
remote, and binds the repo. If `.pam/` and the Project already exist, it loads them. The authored
config lives in the repo; the recorded state lives in ~/.pam.
"""
from __future__ import annotations

import os

from . import db, gitutil, project_config

PAM_DIR = ".pam"
CONFIG = "project.toml"


def init_project(cwd: str, name: str | None = None) -> dict:
    cwd = os.path.abspath(cwd)
    origin = gitutil.origin(cwd)
    if origin is None:
        raise ValueError(f"not a git repo with an 'origin' remote: {cwd}")

    pam_dir = os.path.join(cwd, PAM_DIR)
    cfg_path = os.path.join(pam_dir, CONFIG)

    # Already bound to a Project by path? Load it (idempotent `pam init`).
    existing_repo = db.get_repo_by_path(cwd)
    if existing_repo:
        prog = db.get_project(existing_repo["project_id"])
        os.makedirs(pam_dir, exist_ok=True)
        project_config.scaffold(cfg_path, name=prog["name"], framework=prog["framework"] or "ada")
        if prog.get("config_path") != cfg_path:
            db.set_project_config_path(prog["id"], cfg_path)
        return {"project": prog, "pam_dir": pam_dir, "loaded": True}

    # Fresh init.
    pname = name or gitutil.normalize(origin).split("/")[-1]
    tracker = "github" if "github.com" in origin.lower() else "git"
    branch = gitutil.current_branch(cwd)
    os.makedirs(pam_dir, exist_ok=True)
    project_config.scaffold(cfg_path, name=pname, framework="ada")
    prog = db.add_project(name=pname, framework="ada", tracker=tracker, config_path=cfg_path)
    short = gitutil.normalize(origin).split("/")[-1]
    db.add_repo(prog["id"], name=short, repo_url=origin, path=cwd, origin=origin,
                default_branch=branch)
    return {"project": prog, "pam_dir": pam_dir, "loaded": False}
