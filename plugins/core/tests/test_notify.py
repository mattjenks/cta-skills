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
    monkeypatch.setenv("CTA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("CTA_UNATTENDED", raising=False)
    monkeypatch.setattr(notify.time, "time", lambda: NOW)
    return run, persona


NOW = 10_000.0
SID = "sess-1"


def _start_file(tmp_path):
    return tmp_path / "state" / "turns" / SID


def _started(tmp_path, elapsed):
    path = _start_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repr(NOW - elapsed), encoding="utf-8")
    return path


def _main_with(monkeypatch, event):
    event = {"session_id": SID, **event}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    return notify.main()


def test_stop_message(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 301)
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
    run.assert_called_once()
    args = run.call_args.args[0]
    assert args == ["osascript", "-e", 'display notification "Done" with title "Ada"']
    assert run.call_args.kwargs == {
        "timeout": 5,
        "check": False,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }


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


def test_stands_down_when_stop_hook_active(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 1000)
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


def test_non_macos_does_nothing(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 1000)
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
    run.assert_not_called()


def test_malformed_stdin_exits_zero(cta_env, monkeypatch):
    run, _ = cta_env
    monkeypatch.setattr("sys.stdin", io.StringIO("not json{"))
    assert notify.main() == 0
    run.assert_not_called()


def test_subprocess_failure_exits_zero(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 1000)
    run.side_effect = subprocess.TimeoutExpired("osascript", 5)
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0


def test_short_turn_is_silent(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 299)
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
    run.assert_not_called()


def test_exactly_at_threshold_notifies(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 300)
    _main_with(monkeypatch, {"hook_event_name": "Stop"})
    run.assert_called_once()


def test_no_start_file_is_silent(cta_env, monkeypatch):
    run, _ = cta_env
    assert _main_with(monkeypatch, {"hook_event_name": "Stop"}) == 0
    run.assert_not_called()


def test_unreadable_start_file_is_silent(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    path = _started(tmp_path, 1000)
    path.write_text("garbage", encoding="utf-8")
    _main_with(monkeypatch, {"hook_event_name": "Stop"})
    run.assert_not_called()


def test_invalid_session_id_is_silent(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 1000)
    _main_with(monkeypatch, {"hook_event_name": "Stop", "session_id": "../sess-1"})
    run.assert_not_called()


def test_unattended_is_silent(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    _started(tmp_path, 1000)
    monkeypatch.setenv("CTA_UNATTENDED", "1")
    _main_with(monkeypatch, {"hook_event_name": "Stop"})
    run.assert_not_called()


def test_threshold_zero_always_notifies(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    config = tmp_path / "config.toml"
    config.write_text(config.read_text() + "[notify]\nmin_turn_seconds = 0\n", encoding="utf-8")
    _started(tmp_path, 0)
    _main_with(monkeypatch, {"hook_event_name": "Stop"})
    run.assert_called_once()


def test_configured_threshold_applies(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    config = tmp_path / "config.toml"
    config.write_text(config.read_text() + "[notify]\nmin_turn_seconds = 60\n", encoding="utf-8")
    _started(tmp_path, 61)
    _main_with(monkeypatch, {"hook_event_name": "Stop"})
    run.assert_called_once()


def test_notification_follows_threshold_and_keeps_start(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    path = _started(tmp_path, 301)
    _main_with(monkeypatch, {"hook_event_name": "Notification", "message": "Approve?"})
    run.assert_called_once()
    assert path.exists()
    run.reset_mock()
    path.write_text(repr(NOW - 10), encoding="utf-8")
    _main_with(monkeypatch, {"hook_event_name": "Notification", "message": "Approve?"})
    run.assert_not_called()
    assert path.exists()


def test_stop_removes_start_file_even_when_silent(cta_env, monkeypatch, tmp_path):
    run, _ = cta_env
    path = _started(tmp_path, 5)
    _main_with(monkeypatch, {"hook_event_name": "Stop"})
    run.assert_not_called()
    assert not path.exists()
