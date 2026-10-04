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


def roles_doc() -> str:
    """Render the seeded role catalog as a human-readable standard for `.pam/roles.md`."""
    lines = [
        "# Team roles",
        "",
        "The standard roles PAM seeds for a Project: the shared vocabulary for who does what.",
        "This file reads on its own; you do not need to run pam or cmux to use it as a team standard.",
        "",
    ]
    for key, title, desc, perms, cfg in db.SEED_ROLES:
        lines += [f"## {key}: {title}", "", desc]
        if perms:
            lines += ["", f"Permissions: {', '.join(perms)}."]
        if cfg.get("onboarding_recipe") == "ada":
            lines += ["", "The ADA process and manual ship with PAM at `pam/agents/ada/` "
                      "(`AGENTS.md`, `docs/process.md`)."]
        lines.append("")
    lines += ["Edit this file to add Project-specific roles or tailor descriptions. PAM reads roles "
              "from the Store; this file is the human-readable standard.", ""]
    return "\n".join(lines)


KB_README = """\
# Knowledge base

This Project's knowledge base. Obsidian-style markdown with `[[wikilinks]]`. It is committed with the
repo and reads on its own: you do not need to run pam or cmux to use it.

Rules:
- One note per file, named in kebab-case; link related notes with `[[note-name]]`, and link liberally.
- Keep each note to one idea; put the specifics in the note, not in this index.
- This KB is the Project's durable knowledge: decisions, how-tos, gotchas, references.
"""


def scaffold_standards(pam_dir: str) -> None:
    """Seed the standalone-valuable standards into `.pam/`: roles.md, a knowledge base, agents/.

    The KB is a default part of `.pam/` (not a separate command): obsidian-style, with rules.
    Idempotent and non-clobbering: existing files are left as hand-edited.
    """
    os.makedirs(os.path.join(pam_dir, "agents"), exist_ok=True)
    roles_path = os.path.join(pam_dir, "roles.md")
    if not os.path.exists(roles_path):
        with open(roles_path, "w") as fh:
            fh.write(roles_doc())
    kb_dir = os.path.join(pam_dir, "kb")
    os.makedirs(kb_dir, exist_ok=True)
    kb_readme = os.path.join(kb_dir, "README.md")
    if not os.path.exists(kb_readme):
        with open(kb_readme, "w") as fh:
            fh.write(KB_README)


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
        scaffold_standards(pam_dir)
        if prog.get("config_path") != cfg_path:
            db.set_project_config_path(prog["id"], cfg_path)
        return {"project": prog, "pam_dir": pam_dir, "loaded": True}

    # Fresh init.
    pname = name or gitutil.normalize(origin).split("/")[-1]
    tracker = "github" if "github.com" in origin.lower() else "git"
    branch = gitutil.current_branch(cwd)
    os.makedirs(pam_dir, exist_ok=True)
    project_config.scaffold(cfg_path, name=pname, framework="ada")
    scaffold_standards(pam_dir)
    prog = db.add_project(name=pname, framework="ada", tracker=tracker, config_path=cfg_path)
    short = gitutil.normalize(origin).split("/")[-1]
    db.add_repo(prog["id"], name=short, repo_url=origin, path=cwd, origin=origin,
                default_branch=branch)
    return {"project": prog, "pam_dir": pam_dir, "loaded": False}
