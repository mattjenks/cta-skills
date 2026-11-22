import os
import shutil
import subprocess
from datetime import date, datetime

import pytest

import backup as backup_mod
from backup import backup

DAY = date(2026, 3, 10)


def make(path, content: bytes, day: date):
    path.write_bytes(content)
    ts = datetime(day.year, day.month, day.day, 12).timestamp()
    os.utime(path, (ts, ts))
    return path


@pytest.fixture
def dirs(tmp_path):
    src = tmp_path / "archive"
    dest = tmp_path / "backup"
    src.mkdir()
    return src, dest


def test_copies_day_and_backfills(dirs):
    src, dest = dirs
    make(src / "otel-20260308T010000.jsonl", b"old", date(2026, 3, 8))
    make(src / "otel-20260310T010000.jsonl", b"today", DAY)
    make(src / "otel-20260311T010000.jsonl", b"future", date(2026, 3, 11))
    assert backup(src, dest, DAY) == 2
    assert (dest / "otel-20260308T010000.jsonl").read_bytes() == b"old"
    assert (dest / "otel-20260310T010000.jsonl").read_bytes() == b"today"
    assert not (dest / "otel-20260311T010000.jsonl").exists()


def test_skips_already_copied(dirs):
    src, dest = dirs
    make(src / "otel-20260308T010000.jsonl", b"old", date(2026, 3, 8))
    assert backup(src, dest, DAY) == 1
    assert backup(src, dest, DAY) == 0


def test_no_files_returns_zero_and_exits_0(dirs, capsys, monkeypatch):
    src, dest = dirs
    assert backup(src, dest, DAY) == 0
    monkeypatch.setattr(backup_mod, "configured_dest", lambda: dest)
    monkeypatch.setattr(backup_mod, "ARCHIVE", src)
    assert backup_mod.main(["--day", "2026-03-10"]) == 0
    assert "nothing to back up" in capsys.readouterr().out


def test_checksum_mismatch_raises(dirs, monkeypatch):
    src, dest = dirs
    make(src / "otel-20260308T010000.jsonl", b"0123456789", date(2026, 3, 8))
    real = shutil.copy2

    def truncating(s, d, **kw):
        real(s, d, **kw)
        with open(d, "r+b") as fh:
            fh.truncate(4)
        return d

    monkeypatch.setattr(backup_mod.shutil, "copy2", truncating)
    with pytest.raises(backup_mod.BackupError):
        backup(src, dest, DAY)
    assert [p.name for p in dest.iterdir()] == []  # no partial file left
    assert (src / "otel-20260308T010000.jsonl").read_bytes() == b"0123456789"


def test_live_snapshot_dated_and_replaced(dirs):
    src, dest = dirs
    live = make(src / "otel.jsonl", b"v1\n", DAY)
    assert backup(src, dest, DAY) == 1
    snap = dest / "otel-live-2026-03-10.jsonl"
    assert snap.read_bytes() == b"v1\n"
    live.write_bytes(b"v2-longer\n")
    assert backup(src, dest, DAY) == 1  # same day re-run replaces the snapshot
    assert snap.read_bytes() == b"v2-longer\n"
    assert live.read_bytes() == b"v2-longer\n"  # source untouched
    assert backup(src, dest, date(2026, 3, 11)) == 1
    assert (dest / "otel-live-2026-03-11.jsonl").exists() and snap.exists()


def test_cli_without_backup_dir_exits_1(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CTA_CONFIG", str(tmp_path / "none.toml"))
    assert backup_mod.main([]) == 1
    assert "backup_dir not configured" in capsys.readouterr().err


def test_live_snapshot_tolerates_append_during_copy(dirs, monkeypatch):
    src, dest = dirs
    live = make(src / "otel.jsonl", b'{"a":1}\n{"b":2}\n', DAY)
    real = shutil.copy2

    def copy_then_append(s, d, **kw):
        real(s, d, **kw)
        with open(s, "ab") as fh:  # collector keeps writing, mid-line
            fh.write(b'{"c":3}\n{"d":')

    monkeypatch.setattr(backup_mod.shutil, "copy2", copy_then_append)
    assert backup(src, dest, DAY) == 1
    snap = (dest / "otel-live-2026-03-10.jsonl").read_bytes()
    assert snap == b'{"a":1}\n{"b":2}\n'
    assert live.read_bytes().endswith(b'{"d":')


def test_live_snapshot_trims_partial_trailing_line(dirs):
    src, dest = dirs
    make(src / "otel.jsonl", b'{"a":1}\n{"b"', DAY)
    backup(src, dest, DAY)
    assert (dest / "otel-live-2026-03-10.jsonl").read_bytes() == b'{"a":1}\n'


@pytest.fixture(autouse=True)
def not_macos(monkeypatch):
    """No real notification from any test unless it opts in with a fake runner."""
    monkeypatch.setattr(backup_mod.platform, "system", lambda: "Linux")


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))


def test_failure_notifies_on_macos(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(backup_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("CTA_CONFIG", str(tmp_path / "none.toml"))
    run = FakeRun()
    assert backup_mod.main([], run=run) == 1
    assert len(run.calls) == 1
    cmd, kw = run.calls[0]
    assert cmd[:2] == ["osascript", "-e"]
    assert "CTA telemetry backup failed: backup_dir not configured" in cmd[2]
    assert kw["stdout"] == subprocess.DEVNULL and kw["stderr"] == subprocess.DEVNULL


def test_copy_failure_notifies_with_reason(dirs, monkeypatch):
    src, dest = dirs
    monkeypatch.setattr(backup_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(backup_mod, "configured_dest", lambda: dest)
    monkeypatch.setattr(backup_mod, "ARCHIVE", src)

    def boom(*a, **kw):
        raise backup_mod.BackupError("checksum mismatch copying x")

    monkeypatch.setattr(backup_mod, "backup", boom)
    run = FakeRun()
    assert backup_mod.main(["--day", "2026-03-10"], run=run) == 1
    assert "CTA telemetry backup failed: checksum mismatch copying x" in run.calls[0][0][2]


def test_failure_off_macos_does_not_notify(monkeypatch, tmp_path):
    monkeypatch.setenv("CTA_CONFIG", str(tmp_path / "none.toml"))
    run = FakeRun()
    assert backup_mod.main([], run=run) == 1
    assert run.calls == []


def test_success_does_not_notify(dirs, monkeypatch):
    src, dest = dirs
    monkeypatch.setattr(backup_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(backup_mod, "configured_dest", lambda: dest)
    monkeypatch.setattr(backup_mod, "ARCHIVE", src)
    run = FakeRun()
    assert backup_mod.main(["--day", "2026-03-10"], run=run) == 0
    assert run.calls == []


def test_config_notes_go_to_stderr(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "config.toml"
    bad.write_text("this is = = not toml\n", encoding="utf-8")
    monkeypatch.setenv("CTA_CONFIG", str(bad))
    assert backup_mod.main([], run=FakeRun()) == 1
    err = capsys.readouterr().err
    assert "config unreadable" in err
    assert "backup_dir not configured" in err


def test_prunes_live_snapshots_keeping_newest_seven(dirs):
    src, dest = dirs
    dest.mkdir()
    for d in range(1, 10):  # 2026-03-01 .. 2026-03-09
        (dest / f"otel-live-2026-03-{d:02d}.jsonl").write_bytes(b"x\n")
    rotated = dest / "otel-20260301T010000.jsonl"
    rotated.write_bytes(b"rotated\n")
    other = dest / "notes.txt"
    other.write_bytes(b"keep\n")
    make(src / "otel.jsonl", b"live\n", DAY)
    backup(src, dest, DAY)
    lives = sorted(p.name for p in dest.glob("otel-live-*.jsonl"))
    assert lives == [f"otel-live-2026-03-{d:02d}.jsonl" for d in range(4, 11)]
    assert rotated.exists() and other.exists()


def test_failed_run_does_not_prune(dirs, monkeypatch):
    src, dest = dirs
    dest.mkdir()
    for d in range(1, 10):
        (dest / f"otel-live-2026-03-{d:02d}.jsonl").write_bytes(b"x\n")
    make(src / "otel.jsonl", b"live\n", DAY)
    monkeypatch.setattr(backup_mod.shutil, "copy2", lambda s, d, **kw: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        backup(src, dest, DAY)
    assert len(list(dest.glob("otel-live-*.jsonl"))) == 9


def test_unexpected_error_notifies(monkeypatch):
    monkeypatch.setattr(backup_mod.platform, "system", lambda: "Darwin")

    def broken():
        raise RuntimeError("config loader exploded")

    monkeypatch.setattr(backup_mod, "configured_dest", broken)
    run = FakeRun()
    assert backup_mod.main([], run=run) == 1
    assert "CTA telemetry backup failed: RuntimeError: config loader exploded" in run.calls[0][0][2]
