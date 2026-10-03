"""Action manifest loader: pure parsing/validation (no network, no tmux)."""
import textwrap

import pytest

from pam.runtime.actions import DEFAULT_COOLDOWN_H, ActionError, load_actions


def _w(d, name, text):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(textwrap.dedent(text))


def test_event_spawn_action(tmp_path):
    d = tmp_path / "actions"
    _w(d, "spawn-on-assign.toml", """
        [trigger]
        event = "issue.assigned"
        match = { label = "Type: Subtask" }
        [handler]
        spawn = { role = "ada_agent", oracle_bundle = "oracle.pr.yml" }
        [guard]
        requires = ["no_running_session"]
    """)
    (a,) = load_actions(d)
    assert a.id == "spawn-on-assign"
    assert a.trigger_type == "event" and a.event == "issue.assigned"
    assert a.match["label"] == "Type: Subtask"
    assert a.handler_type == "spawn" and a.handler_params["role"] == "ada_agent"
    assert a.requires == ["no_running_session"]
    assert a.cooldown_h == DEFAULT_COOLDOWN_H
    assert len(a.content_hash) == 16


def test_schedule_and_cooldown_override(tmp_path):
    d = tmp_path / "a"
    _w(d, "nag.toml", """
        cooldown_h = 48
        [trigger]
        schedule = "0 9 * * *"
        [handler]
        deliver = { template = "nag" }
    """)
    (a,) = load_actions(d)
    assert a.trigger_type == "schedule" and a.schedule == "0 9 * * *"
    assert a.cooldown_h == 48.0 and a.handler_type == "deliver"


@pytest.mark.parametrize("body,msg", [
    ('[handler]\nspawn = {}\n', "exactly one of event"),                       # no trigger
    ('[trigger]\nevent="x"\nschedule="y"\n[handler]\nspawn={}\n', "exactly one of event"),
    ('[trigger]\nevent="x"\n', "exactly one of deliver"),                      # no handler
    ('[trigger]\nevent="x"\n[handler]\nspawn={}\ndeliver={}\n', "exactly one of deliver"),
])
def test_invalid_manifests(tmp_path, body, msg):
    d = tmp_path / "a"
    d.mkdir(parents=True)
    (d / "bad.toml").write_text(body)
    with pytest.raises(ActionError, match=msg):
        load_actions(d)


def test_bundle_overrides_generic(tmp_path):
    g, b = tmp_path / "generic", tmp_path / "bundle"
    _w(g, "x.toml", '[trigger]\nevent="a"\n[handler]\nspawn={role="generic"}\n')
    _w(b, "x.toml", '[trigger]\nevent="a"\n[handler]\nspawn={role="override"}\n')
    (a,) = load_actions(b, generic_dir=g)
    assert a.handler_params["role"] == "override"


def test_content_hash_tracks_edits(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    _w(d1, "x.toml", '[trigger]\nevent="a"\n[handler]\nspawn={role="r"}\n')
    _w(d2, "x.toml", '[trigger]\nevent="a"\n[handler]\nspawn={role="r"}\n# edited\n')
    assert load_actions(d1)[0].content_hash != load_actions(d2)[0].content_hash


def test_missing_dir_is_empty(tmp_path):
    assert load_actions(tmp_path / "nope") == []
