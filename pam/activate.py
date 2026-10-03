"""pam activate: per-developer, per-Project activation (the virtualenv model, issue #48).

Activating a Project records which Project is active for this developer and keeps its private
settings in `~/.pam/projects/<project>/`, so forge and git actions run as that Project's
configured identity. PAM never stores credentials: auth is human-driven. The clean mechanism
is env vars, not duplicated binaries or copied tokens. `env_for()` points each tool's config
dir at the per-Project location (e.g. `GH_CONFIG_DIR`), where the human runs `gh auth login`
once. `export_lines()` lets a shell opt into virtualenv-style activation via `eval`.

This module is pure filesystem + env; it never shells out and never starts a session.
"""
from __future__ import annotations

from pathlib import Path

from . import config

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

SETTINGS = "config.toml"
_IDENT_KEYS = ("gh_account", "git_name", "git_email")


def settings_path(name: str) -> Path:
    return config.project_dir(name) / SETTINGS


def gh_config_dir(name: str) -> Path:
    return config.project_dir(name) / "gh"


def load_settings(name: str) -> dict:
    """Read the per-Project private settings. Returns {} if absent or unreadable."""
    p = settings_path(name)
    if not p.exists() or tomllib is None:
        return {}
    try:
        with p.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(name: str, identity: dict | None = None) -> Path:
    """Merge `identity` into the per-Project settings and write them. Returns the path."""
    current = load_settings(name).get("identity", {})
    if identity:
        current.update({k: v for k, v in identity.items() if v})
    config.project_dir(name).mkdir(parents=True, exist_ok=True)
    lines = [
        "# PAM per-developer, per-Project settings (private, never committed).",
        "# Written by `pam activate`. Edit freely; PAM never stores credentials here.",
        "",
        "[identity]",
    ]
    for k in _IDENT_KEYS:
        if current.get(k):
            lines.append(f'{k} = "{current[k]}"')
    p = settings_path(name)
    p.write_text("\n".join(lines) + "\n")
    return p


def env_for(name: str) -> dict:
    """Env vars that run forge/git tools as this Project's identity (no bins, no tokens copied)."""
    ident = load_settings(name).get("identity", {})
    env = {"PAM_ACTIVE_PROJECT": name, "GH_CONFIG_DIR": str(gh_config_dir(name))}
    if ident.get("git_name"):
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = ident["git_name"]
    if ident.get("git_email"):
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = ident["git_email"]
    return env


def export_lines(name: str) -> str:
    """Shell export lines for `eval "$(pam activate <project> --export)"`."""
    return "\n".join(f'export {k}="{v}"' for k, v in env_for(name).items())


def is_gh_authed(name: str) -> bool:
    """Best-effort: has the per-Project gh config dir been logged in to?"""
    return (gh_config_dir(name) / "hosts.yml").exists()


def set_active(name: str) -> None:
    config.pam_home().mkdir(parents=True, exist_ok=True)
    config.active_marker().write_text(name + "\n")


def get_active() -> str | None:
    p = config.active_marker()
    if not p.exists():
        return None
    try:
        v = p.read_text().strip()
        return v or None
    except OSError:
        return None


def clear_active() -> None:
    try:
        config.active_marker().unlink()
    except FileNotFoundError:
        pass
