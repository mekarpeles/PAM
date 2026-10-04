"""pam kb: a Project's knowledge base pointer, kept in `.pam/kb.toml` (authored, committed).

The KB is Obsidian-style markdown with `[[wikilinks]]`. It can live in-repo (default `.pam/kb/`)
or point at an external location (a path or a repo URL). Like the rest of `.pam/`, it is valuable
standalone: a reader gets the Project's knowledge without running pam or cmux. See issues #34, #49.

This module only writes the pointer and, for a local in-repo KB, scaffolds a starter. It does not
clone or install external KBs yet (that is the deferred registry path).
"""
from __future__ import annotations

from pathlib import Path

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

KB_FILE = "kb.toml"
DEFAULT_LOCATION = ".pam/kb"

_KB_TOML = """\
# PAM knowledge base pointer: authored, committed, read live by PAM.
[kb]
# Where this Project's KB lives: an in-repo path (default) or an external path/URL.
location = "{location}"
# Obsidian-style markdown with [[wikilinks]] is the suggested format.
style = "obsidian"
"""

_KB_README = """\
# Knowledge base

This Project's knowledge base. Obsidian-style markdown with `[[wikilinks]]`.

It is committed with the repo and reads on its own: you do not need to run pam or cmux to use it.
Add notes as plain `.md` files and link them with `[[note-name]]`.
"""


def kb_toml_path(pam_dir: str | Path) -> Path:
    return Path(pam_dir) / KB_FILE


def load(pam_dir: str | Path) -> dict:
    """Read `.pam/kb.toml`. Returns {} if absent or unreadable."""
    p = kb_toml_path(pam_dir)
    if not p.exists() or tomllib is None:
        return {}
    try:
        with p.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError):
        return {}


def is_local(location: str) -> bool:
    """A location is external if it looks like a URL or scp-style git remote; else local."""
    return not (location.startswith(("http://", "https://", "git@")) or "://" in location)


def set_location(pam_dir: str | Path, location: str | None = None) -> tuple[Path, bool]:
    """Write `.pam/kb.toml` with `location` (default in-repo `.pam/kb`). Scaffold a local KB if
    it is in-repo and missing. Returns (kb.toml path, scaffolded_local?)."""
    pam_dir = Path(pam_dir)
    location = location or DEFAULT_LOCATION
    kb_toml_path(pam_dir).write_text(_KB_TOML.format(location=location))
    scaffolded = False
    if is_local(location):
        repo_root = pam_dir.parent
        target = Path(location) if Path(location).is_absolute() else repo_root / location
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            (target / "README.md").write_text(_KB_README)
            scaffolded = True
    return kb_toml_path(pam_dir), scaffolded
