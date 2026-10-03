"""The invariant that keeps the layers from re-merging:

`pip install pam` must work on a machine with no tmux. PAM imports nothing from cmux. cmux may
import PAM, never the reverse. This test asserts both the runtime fact and the source fact.
"""
import pathlib
import sys


def test_importing_pam_pulls_in_no_cmux():
    # import the whole surface
    import pam  # noqa: F401
    import pam.cli  # noqa: F401
    import pam.db  # noqa: F401
    import pam.config  # noqa: F401
    import pam.ids  # noqa: F401
    import pam.gitutil  # noqa: F401
    import pam.forge  # noqa: F401
    import pam.state  # noqa: F401
    import pam.runtime  # noqa: F401
    import pam.agents.ada  # noqa: F401

    offenders = [m for m in sys.modules if m == "cmux" or m.startswith("cmux_lib")]
    assert not offenders, f"pam imported cmux modules: {offenders}"


def test_no_cmux_import_in_source():
    root = pathlib.Path(__file__).resolve().parent.parent / "pam"
    bad = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            s = line.strip()
            if s.startswith("import cmux") or s.startswith("from cmux"):
                bad.append(f"{path}:{i}: {s}")
    assert not bad, "cmux imports found in pam/:\n" + "\n".join(bad)
