import io
import json
import subprocess
from unittest.mock import MagicMock

import pytest

import notify


@pytest.fixture(autouse=True)
def cta_env(tmp_path, monkeypatch):
    """Point config at a temp persona and stub subprocess so no real notification fires."""
    persona = tmp_path / "persona.md"
    persona.write_text("intro line\n# Ada\n\nI am Ada.\n", encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(f'persona = "{persona}"\n', encoding="utf-8")
    monkeypatch.setenv("CTA_CONFIG", str(config))
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    run = MagicMock()
    monkeypatch.setattr(notify.subprocess, "run", run)
    return run, persona


def _main_with(monkeypatch, event):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    return notify.main()


def test_stop_message(cta_env, monkeypatch):
    run, _ = cta_env
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
    run.assert_called_once()
    args = run.call_args.args[0]
    assert args == ["osascript", "-e", 'display notification "Done" with title "Ada"']
    assert run.call_args.kwargs == {"timeout": 5, "check": False}


def test_notification_uses_event_message(cta_env):
    assert notify.notification_args(
        {"hook_event_name": "Notification", "message": "Needs a decision"}
    ) == ["osascript", "-e", 'display notification "Needs a decision" with title "Ada"']


def test_notification_message_truncated_to_120(cta_env):
    args = notify.notification_args(
        {"hook_event_name": "Notification", "message": "x" * 300}
    )
    assert args[2] == 'display notification "' + "x" * 120 + '" with title "Ada"'


def test_quotes_are_escaped(cta_env):
    args = notify.notification_args(
        {"hook_event_name": "Notification", "message": 'say "hi" \\ bye'}
    )
    assert args[2] == r'display notification "say \"hi\" \\ bye" with title "Ada"'


def test_stands_down_when_stop_hook_active(cta_env, monkeypatch):
    run, _ = cta_env
    assert _main_with(monkeypatch, {"hook_event_name": "Stop", "stop_hook_active": True}) == 0
    run.assert_not_called()


def test_title_from_persona_heading(cta_env, monkeypatch):
    _, persona = cta_env
    persona.write_text("intro\n#  Ada Lovelace  \n", encoding="utf-8")
    args = notify.notification_args({"hook_event_name": "Stop"})
    assert args[2] == 'display notification "Done" with title "Ada Lovelace"'


def test_title_falls_back_to_cta(cta_env):
    _, persona = cta_env
    persona.write_text("no heading in this persona\n", encoding="utf-8")
    assert notify.notification_args({"hook_event_name": "Stop"})[2].endswith('with title "CTA"')
    persona.unlink()
    assert notify.notification_args({"hook_event_name": "Stop"})[2].endswith('with title "CTA"')


def test_unknown_or_missing_event_is_stop(cta_env):
    for event in ({"hook_event_name": "Weird"}, {}):
        assert notify.notification_args(event)[2].startswith('display notification "Done"')


def test_non_macos_does_nothing(cta_env, monkeypatch):
    run, _ = cta_env
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
    run.assert_not_called()


def test_malformed_stdin_exits_zero(cta_env, monkeypatch):
    run, _ = cta_env
    monkeypatch.setattr("sys.stdin", io.StringIO("not json{"))
    assert notify.main() == 0
    run.assert_not_called()


def test_subprocess_failure_exits_zero(cta_env, monkeypatch):
    run, _ = cta_env
    run.side_effect = subprocess.TimeoutExpired("osascript", 5)
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
