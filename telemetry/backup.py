#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Back up the raw telemetry archive to the folder set by `[telemetry] backup_dir`.

Copies rotated archive files (mtime date <= day) not yet at the destination, plus a dated
snapshot of the live otel.jsonl (`otel-live-<day>.jsonl`, replaced on same-day re-run).
Every copy goes to a temp file, is verified by size and SHA-256, then renamed into place.
The source is never modified or deleted.
"""
import argparse
import hashlib
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "core" / "hooks"
ARCHIVE = Path(os.environ.get("CTA_DATA", Path.home() / ".local/share/cta/telemetry")) / "archive"


class BackupError(Exception):
    pass


def sha256(path: Path, limit: int | None = None) -> str:
    """SHA-256 of the file, or of its first `limit` bytes."""
    h = hashlib.sha256()
    remaining = limit
    with open(path, "rb") as fh:
        while remaining is None or remaining > 0:
            chunk = fh.read(1 << 20 if remaining is None else min(1 << 20, remaining))
            if not chunk:
                break
            h.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return h.hexdigest()


def _trim_partial_line(path: Path) -> None:
    """Truncate after the last newline so the file holds whole JSONL lines only."""
    data = path.read_bytes()
    keep = data.rfind(b"\n") + 1
    if keep != len(data):
        with open(path, "r+b") as fh:
            fh.truncate(keep)


def _copy_verified(src: Path, target: Path, growing: bool = False) -> None:
    """Copy via a temp file, verify, rename. `growing` tolerates appends to src (live file)."""
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        shutil.copy2(src, tmp)
        if growing:
            n = tmp.stat().st_size
            if src.stat().st_size < n or sha256(tmp) != sha256(src, limit=n):
                raise BackupError(f"checksum mismatch copying {src.name}")
            _trim_partial_line(tmp)
        elif tmp.stat().st_size != src.stat().st_size or sha256(tmp) != sha256(src):
            raise BackupError(f"checksum mismatch copying {src.name}")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def backup(src: Path, dest: Path, day: date) -> int:
    """Copy archive files to dest. Returns the number of files copied."""
    if not src.is_dir():
        return 0
    copied = 0
    for f in sorted(src.glob("otel-*.jsonl")):
        if datetime.fromtimestamp(f.stat().st_mtime).date() > day:
            continue
        target = dest / f.name
        if target.exists() and target.stat().st_size == f.stat().st_size:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        _copy_verified(f, target)
        copied += 1
    live = src / "otel.jsonl"
    if live.is_file() and live.stat().st_size > 0:
        dest.mkdir(parents=True, exist_ok=True)
        _copy_verified(live, dest / f"otel-live-{day.isoformat()}.jsonl", growing=True)
        copied += 1
    return copied


def configured_dest() -> Path | None:
    sys.path.insert(0, str(HOOKS))
    from cta_config import load_config

    return load_config().backup_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    dest = configured_dest()
    if dest is None:
        print("backup_dir not configured", file=sys.stderr)
        return 1
    day = args.day or date.today()
    try:
        n = backup(ARCHIVE, dest, day)
    except (BackupError, OSError) as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"backed up {n} file(s) to {dest}" if n else "nothing to back up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
