#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Back up the raw telemetry archive to the folder set by `[telemetry] backup_dir`.

Copies rotated archive files (mtime date <= day) not yet at the destination, plus a dated
snapshot of the live otel.jsonl (`otel-live-<day>.jsonl`, replaced on same-day re-run).
Every copy goes to a temp file, is verified by size and SHA-256, then renamed into place.
Then it mirrors the 5 newest learn reports to `<backup_dir>/../learn/reports`.
The source is never modified or deleted. After a successful run only the newest
LIVE_KEEP live snapshots (by date) are kept at the destination; rotated copies are never pruned.
On any failure it exits 1 and, on macOS, raises a notification with the reason.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "core" / "hooks"
ARCHIVE = Path(os.environ.get("CTA_DATA", Path.home() / ".local/share/cta/telemetry")) / "archive"
LIVE_KEEP = 7
_LIVE_SNAPSHOT = re.compile(r"otel-live-(\d{4}-\d{2}-\d{2})\.jsonl")
REPORTS_KEEP = 5
DEFAULT_REPORTS_DIR = Path.home() / ".local/share/cta/learn"
_REPORT_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_REPORT_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})\.(?:json|md|html|delivery\.json)")
_REPORT_KINDS = ("json", "md", "html", "delivery.json")


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
    if dest.is_dir():
        prune_live_snapshots(dest)
    return copied


def prune_live_snapshots(dest: Path, keep: int = LIVE_KEEP) -> None:
    """Delete all but the newest `keep` otel-live-<date>.jsonl files. Rotated copies are untouched."""
    snaps = sorted(
        (m.group(1), p) for p in dest.iterdir() if (m := _LIVE_SNAPSHOT.fullmatch(p.name))
    )
    for _, path in snaps[: max(len(snaps) - keep, 0)]:
        path.unlink(missing_ok=True)


def _valid_report_date(value: object) -> bool:
    if not isinstance(value, str) or not _REPORT_DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_plain_file(p: Path) -> bool:
    return not p.is_symlink() and p.is_file()


def _copy_if_changed(src: Path, target: Path) -> bool:
    if (_is_plain_file(target) and target.stat().st_size == src.stat().st_size
            and sha256(target) == sha256(src)):
        return False
    _copy_verified(src, target)
    return True


def backup_reports(src: Path, dest: Path, keep: int = REPORTS_KEEP) -> int:
    """Mirror the `keep` newest learn reports (and index.json) to dest. Returns files copied.

    Dates come from src/index.json and are used only when they are real YYYY-MM-DD dates;
    only regular, non-symlink files are copied. Report-named files at dest for other dates
    are deleted; anything else at dest is left alone. A missing src is success.
    """
    if not src.is_dir():
        return 0
    try:
        entries = json.loads((src / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = []
    found = set()
    for e in entries if isinstance(entries, list) else []:
        d = e.get("date") if isinstance(e, dict) else None
        if _valid_report_date(d) and _is_plain_file(src / f"{d}.json"):
            found.add(d)
    dates = sorted(found, reverse=True)[:keep]
    copied = 0
    pairs = [(src / f"{d}.{k}", dest / f"{d}.{k}") for d in dates for k in _REPORT_KINDS]
    pairs.append((src / "index.json", dest / "index.json"))
    for s_path, target in pairs:
        if not _is_plain_file(s_path):
            continue
        dest.mkdir(parents=True, exist_ok=True)
        copied += _copy_if_changed(s_path, target)
    if dest.is_dir():
        for p in dest.iterdir():
            m = _REPORT_FILE.fullmatch(p.name)
            if m and m.group(1) not in dates:
                p.unlink(missing_ok=True)
    return copied


def local_reports_dir() -> Path:
    """`<[learn] reports_dir>/reports`, with the same rules as the learn plugin's config."""
    sys.path.insert(0, str(HOOKS))
    import cta_config

    override = os.environ.get("CTA_CONFIG")
    path = Path(override) if override else cta_config.DEFAULT_CONFIG_PATH
    try:
        with open(path, "rb") as fh:
            section = tomllib.load(fh).get("learn")
    except (OSError, ValueError):
        section = None
    root = DEFAULT_REPORTS_DIR
    value = section.get("reports_dir") if isinstance(section, dict) else None
    if isinstance(value, str) and value.strip():
        try:
            cand = Path(value).expanduser()
        except (RuntimeError, ValueError):
            cand = None
        if cand is not None and cand.is_absolute() and ".." not in cand.parts:
            root = cand
    return root / "reports"


def configured_dest() -> Path | None:
    sys.path.insert(0, str(HOOKS))
    from cta_config import load_config

    cfg = load_config()
    for note in cfg.notes:  # e.g. a malformed config.toml: show the cause
        print(f"config: {note}", file=sys.stderr)
    return cfg.backup_dir


def notify_failure(run, reason: str) -> None:
    """macOS notification for a failed run; skipped elsewhere. Never raises."""
    if platform.system() != "Darwin":
        return
    text = f"CTA telemetry backup failed: {reason}"[:200]
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    try:
        run(["osascript", "-e", f'display notification "{text}" with title "CTA telemetry"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def _run_backup(day: date | None) -> str | None:
    """Do the backup. Returns a failure reason, or None on success."""
    dest = configured_dest()
    if dest is None:
        return "backup_dir not configured"
    reasons = []
    try:
        n = backup(ARCHIVE, dest, day or date.today())
        print(f"backed up {n} file(s) to {dest}" if n else "nothing to back up")
    except (BackupError, OSError) as exc:
        reasons.append(str(exc))
    reports_dest = dest.parent / "learn" / "reports"
    try:  # a reports failure never stops the telemetry backup, which has already run
        r = backup_reports(local_reports_dir(), reports_dest)
        if r:
            print(f"backed up {r} report file(s) to {reports_dest}")
    except Exception as exc:
        reasons.append(f"reports backup failed: {type(exc).__name__}: {exc}")
    return "; ".join(reasons) or None


def main(argv: list[str] | None = None, run=subprocess.run) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    try:
        reason = _run_backup(args.day)
    except Exception as exc:  # anything unexpected still fails loudly, with a notification
        reason = f"{type(exc).__name__}: {exc}"
    if reason is None:
        return 0
    print(reason if reason == "backup_dir not configured" else f"backup failed: {reason}",
          file=sys.stderr)
    notify_failure(run, reason)
    return 1


if __name__ == "__main__":
    sys.exit(main())
