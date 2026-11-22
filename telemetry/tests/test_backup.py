import os
import shutil
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
    live = make(src / "otel.jsonl", b"v1", DAY)
    assert backup(src, dest, DAY) == 1
    snap = dest / "otel-live-2026-03-10.jsonl"
    assert snap.read_bytes() == b"v1"
    live.write_bytes(b"v2-longer")
    assert backup(src, dest, DAY) == 1  # same day re-run replaces the snapshot
    assert snap.read_bytes() == b"v2-longer"
    assert live.read_bytes() == b"v2-longer"  # source untouched
    assert backup(src, dest, date(2026, 3, 11)) == 1
    assert (dest / "otel-live-2026-03-11.jsonl").exists() and snap.exists()


def test_cli_without_backup_dir_exits_1(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CTA_CONFIG", str(tmp_path / "none.toml"))
    assert backup_mod.main([]) == 1
    assert "backup_dir not configured" in capsys.readouterr().err
