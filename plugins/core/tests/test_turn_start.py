import io
import json
import os
import time

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


def _aged(path, age_seconds, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1.0", encoding="utf-8")
    ts = now - age_seconds
    os.utime(path, (ts, ts))
    return path


def test_prunes_turn_files_older_than_24h(state, monkeypatch):
    now = time.time()
    turns = state / "turns"
    old = _aged(turns / "old", 25 * 3600, now)
    fresh = _aged(turns / "fresh", 3600, now)
    _run(monkeypatch, {"session_id": "s1"})
    assert not old.exists()
    assert fresh.exists()
    assert (turns / "s1").exists()


def test_prune_is_bounded(state, monkeypatch):
    now = time.time()
    turns = state / "turns"
    for i in range(turn_start.PRUNE_LIMIT + 50):
        _aged(turns / f"old{i}", 25 * 3600, now)
    _run(monkeypatch, {"session_id": "s1"})
    left = [p for p in turns.iterdir() if p.name != "s1"]
    assert len(left) >= 50  # at most PRUNE_LIMIT entries were examined
