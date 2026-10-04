"""pam spawn: bring an onboarded agent up through cmux (issue #50).

The model: at spawn there is no worktree. PAM seeds the agent's cmux homedir with a bootstrap
`AGENTS.md` (what Claude auto-reads on boot), a symlink to its committed identity, and a refs file
pointing at the repo and `.pam/`. Then it runs `cmux up` FROM the homedir, so cwd = homedir and
Claude reads that bootstrap. The agent then acts for its role: an ADA creates its own worktree; a
Division Lead just works the forge. cmux owns the homedir, the session, and session_id.

Dry-run by default: `spawn` acts on a live agent, so the CLI only prints the plan unless `--go` is
passed. The cmux runner is injectable so tests never launch anything. PAM never imports cmux; it
shells out, so a machine without cmux can still do everything up to the launch.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import activate


def cmux_state_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("CMUX_STATE_DIR", "~/.cmux")))


def homedir(name: str) -> Path:
    """cmux's homedir for this agent (cwd at boot)."""
    return cmux_state_dir() / name


def render_bootstrap(name: str, type_key: str, project: str, repo_path: str, pam_dir: str,
                     identity_rel: str, issue: str | None = None) -> str:
    """The homedir AGENTS.md Claude auto-reads on boot: who you are + where your real config is."""
    lines = [
        f"# {name} ({type_key})",
        "",
        f"You are **{name}**, a `{type_key}` on the **{project}** Project.",
        "",
        "Your full definition and skills live in the Project's `.pam/` (read these first):",
        f"- identity: `{identity_rel}`",
        f"- roles standard: `{os.path.join(pam_dir, 'roles.md')}`",
        "",
        f"Project repo: `{repo_path}`",
        f"Project config (.pam): `{pam_dir}`",
    ]
    if issue:
        lines += ["", f"Assigned issue: #{issue}"]
    if type_key == "ada_agent":
        lines += [
            "",
            "You are an ADA. Create your OWN git worktree off the project repo for your issue, "
            "and do your code work there. Do not work on the main checkout.",
        ]
    lines += ["", "cq (your private queue) and your session live in this homedir."]
    return "\n".join(lines) + "\n"


def seed_home(name: str, type_key: str, project: str, repo_path: str, pam_dir: str,
              defn_dir: str, issue: str | None = None) -> Path:
    """Create and populate the cmux homedir before launch. Idempotent; never clobbers edits."""
    home = homedir(name)
    home.mkdir(parents=True, exist_ok=True)

    identity_src = Path(defn_dir) / "identity.md"
    # symlink the committed identity into the homedir for convenience (best-effort).
    link = home / "identity.md"
    if identity_src.exists() and not link.exists():
        try:
            link.symlink_to(identity_src)
        except OSError:
            pass

    agents_md = home / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(render_bootstrap(
            name, type_key, project, repo_path, pam_dir, str(identity_src), issue))

    refs = home / "refs.toml"
    if not refs.exists():
        refs.write_text(
            "# PAM references for this agent (seeded at spawn).\n"
            f'project = "{project}"\n'
            f'type = "{type_key}"\n'
            f'repo_path = "{repo_path}"\n'
            f'pam_dir = "{pam_dir}"\n'
            + (f'issue = "{issue}"\n' if issue else ""))
    return home


def cmux_up_cmd(name: str) -> list[str]:
    """The cmux command PAM runs from the homedir to boot the agent clean."""
    return ["cmux", "up", name, "--no-inject", "-d"]


def launch(name: str, env: dict | None = None,
           runner=subprocess.run) -> subprocess.CompletedProcess:
    """Run `cmux up` from the agent's homedir with the given env. Injectable for tests."""
    cmd = cmux_up_cmd(name)
    full_env = {**os.environ, **(env or {})}
    return runner(cmd, cwd=str(homedir(name)), env=full_env)


def plan(name: str, project: str) -> dict:
    """The dry-run plan: what spawn WOULD do. Pure (no launch)."""
    return {
        "homedir": str(homedir(name)),
        "command": " ".join(cmux_up_cmd(name)),
        "env": activate.env_for(project),
    }
