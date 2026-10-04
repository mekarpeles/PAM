"""Authored agent definitions in a Project's `.pam/agents/<name>/`.

`pam onboard` writes a committed, human-readable definition for each team member: an
`agent.toml` (name, uuid, type, reports_to) and a vanilla `identity.md` that `@link`s the
type's canonical manual shipped with the pam package. The runtime home is provisioned
later by cmux (issue #50); nothing here touches `~/.pam` or the session.

These files are valuable standalone: someone who never runs pam or cmux still gets the
standardized role and the ADA process by reading them (issue #49).
"""
from __future__ import annotations

from pathlib import Path

# role/type key -> directory under pam/agents/ that ships its canonical manual.
_TYPE_PKG_DIR = {"ada_agent": "ada"}


def _pkg_agents_root() -> Path:
    return Path(__file__).resolve().parent / "agents"


def type_def_link(type_key: str) -> str | None:
    """Repo-relative path to the type's manual in the pam package, or None if none ships yet."""
    sub = _TYPE_PKG_DIR.get(type_key, type_key)
    if (_pkg_agents_root() / sub / "AGENTS.md").exists():
        return f"pam/agents/{sub}/AGENTS.md"
    return None


def agent_dir(pam_dir: str | Path, name: str) -> Path:
    return Path(pam_dir) / "agents" / name


_AGENT_TOML = """\
# PAM agent definition: authored, committed, hand-editable. This is {name}'s identity in
# this Project. The running agent reads identity.md (beside this file) on startup.
[agent]
name = "{name}"
uuid = "{uuid}"
type = "{type_key}"
reports_to = "{reports_to}"
can_onboard = {can_onboard}
{orders_line}"""


def _identity_md(name: str, type_key: str, link: str | None) -> str:
    head = f"# {name}\n\n"
    if link:
        body = (f"This agent is a `{type_key}`. Its canonical manual ships with PAM:\n\n"
                f"@link {link}\n\n")
    else:
        body = (f"This agent is a `{type_key}`. No canonical manual ships with PAM for this type "
                f"yet; describe the role here.\n\n")
    tail = "<!-- Project-specific identity, skills, and overrides for this agent go below. -->\n"
    return head + body + tail


def scaffold(pam_dir: str | Path, name: str, uuid: str, type_key: str,
             reports_to: str = "", can_onboard: bool = False,
             orders_src: str | Path | None = None) -> tuple[Path, bool]:
    """Write <pam_dir>/agents/<name>/{agent.toml,identity.md[,orders.md]} if absent.

    `can_onboard` records whether this agent may onboard others. `orders_src`, if given and
    readable, is copied in as orders.md (the agent's specific marching orders). Returns
    (dir, created?)."""
    d = agent_dir(pam_dir, name)
    if d.exists():
        return d, False
    d.mkdir(parents=True, exist_ok=True)
    orders_line = ""
    if orders_src and Path(orders_src).exists():
        (d / "orders.md").write_text(Path(orders_src).read_text())
        orders_line = 'orders = "orders.md"\n'
    (d / "agent.toml").write_text(_AGENT_TOML.format(
        name=name, uuid=uuid, type_key=type_key, reports_to=reports_to or "",
        can_onboard="true" if can_onboard else "false", orders_line=orders_line))
    (d / "identity.md").write_text(_identity_md(name, type_key, type_def_link(type_key)))
    return d, True
