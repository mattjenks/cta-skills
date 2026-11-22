import io
import json

import pytest

import turn_start


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CTA_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def _run(monkeypatch, payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    return turn_start.main()


def test_records_float_for_valid_session(state, monkeypatch, capsys):
    monkeypatch.setattr(turn_start.time, "time", lambda: 1234.5)
    assert _run(monkeypatch, {"session_id": "abc-123_X"}) == 0
    assert float((state / "turns" / "abc-123_X").read_text()) == 1234.5
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("sid", ["../x", "", "a/b", "a b", None, 5])
def test_invalid_session_ids_do_nothing(state, monkeypatch, sid):
    assert _run(monkeypatch, {"session_id": sid}) == 0
    assert not state.exists()


def test_malformed_stdin_exits_zero(state, monkeypatch, capsys):
    assert _run(monkeypatch, "not json{") == 0
    assert capsys.readouterr().out == ""
    assert not state.exists()


def test_overwrites_previous_start(state, monkeypatch):
    for now in (100.0, 200.0):
        monkeypatch.setattr(turn_start.time, "time", lambda now=now: now)
        _run(monkeypatch, {"session_id": "s1"})
    assert float((state / "turns" / "s1").read_text()) == 200.0
    assert [p.name for p in (state / "turns").iterdir()] == ["s1"]
