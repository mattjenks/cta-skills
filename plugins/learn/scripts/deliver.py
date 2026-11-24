#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Prepare, record and fall back for the delivery of the weekly report email.

Usage:
  deliver.py prepare --date YYYY-MM-DD [--config PATH]   print {to, subject, html_path, md_path}
  deliver.py record  --date YYYY-MM-DD --result sent|fallback --detail TEXT [--config PATH]
  deliver.py notify  --date YYYY-MM-DD [--config PATH]   macOS notification pointing at the .md

The recipient comes only from `[learn.delivery] to` in the CTA config. Exit 2: bad input, no
recipient, or the report files are missing. The script never sends mail; the skill does.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import decide
import learn_config
import report
import sanitize

SUBJECT_CHARS = 150
MESSAGE_CHARS = 120
RECIPIENT = re.compile(r"[^\s,;<>\"'()\[\]\\]+@[^\s,;<>\"'()\[\]\\]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SPACE = re.compile(r"\s+")


class DeliverError(Exception):
    pass


def _one_line(text: object, limit: int) -> str:
    """Control characters and whitespace runs collapsed to single spaces, then truncated."""
    out = _SPACE.sub(" ", _CONTROL.sub(" ", "" if text is None else str(text))).strip()
    return out[:limit].rstrip()


def subject_for(day: str, status: str, headline: str) -> str:
    return _one_line(f"CTA weekly report {day}: {_one_line(status, 20)} — "
                     f"{_one_line(headline, 200)}", SUBJECT_CHARS)


def _check_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DeliverError("--date must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise DeliverError("--date must be YYYY-MM-DD") from None
    return value


def find_reports(cfg: learn_config.LearnConfig, day: str) -> Path | None:
    """The `reports/` folder holding this day's HTML file: the live kb, then the worktrees."""
    for root in decide._roots(cfg, day):
        if (root / "reports" / f"{day}.html").is_file():
            return root / "reports"
    return None


def prepare(cfg: learn_config.LearnConfig, day: str) -> dict:
    to = cfg.delivery.to
    if not to:
        raise DeliverError("learn.delivery.to is not set in the CTA config")
    if not RECIPIENT.fullmatch(to):
        raise DeliverError("learn.delivery.to must be one plain email address")
    reports = find_reports(cfg, day)
    if reports is None:
        raise DeliverError(f"no HTML report found for {day}")
    try:
        rep = report.from_json((reports / f"{day}.json").read_text())
    except (OSError, ValueError, KeyError, TypeError):
        raise DeliverError(f"no readable report JSON for {day}") from None
    return {"to": to, "subject": subject_for(day, rep.status, rep.headline),
            "html_path": str(reports / f"{day}.html"), "md_path": str(reports / f"{day}.md")}


def record(cfg: learn_config.LearnConfig, day: str, result: str, detail: str) -> Path:
    reports = find_reports(cfg, day)
    if reports is None:
        raise DeliverError(f"no HTML report found for {day}")
    row = {"date": day, "result": result, "detail": sanitize.line(detail),
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = reports / f"{day}.delivery.json"
    path.write_text(json.dumps(row, indent=2) + "\n")
    _commit_record(path, day)
    return path


def _warn(message: str) -> None:
    print(f"deliver.py: warning: {message}", file=sys.stderr)


def _commit_record(path: Path, day: str) -> None:
    """Commit (and push, when a remote exists) the record on the report's branch.

    Only when the file sits in the `learn-report-<day>` worktree on `learn/report-<day>`; never
    the default branch. A failure is a warning: the record still stands.
    """
    wt = decide.WORKTREE_ROOT / f"learn-report-{day}"
    branch = f"learn/report-{day}"
    if wt not in path.parents:
        return
    head = decide._git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != branch:
        _warn(f"{wt.name} is not on {branch}; the delivery record was not committed")
        return
    rel = str(path.relative_to(wt))
    steps = [("add", "--", rel),
             ("-c", "commit.gpgsign=false", "commit", "-q", "-m",
              f"docs(learn): delivery record {day}", "--", rel)]
    for step in steps:
        out = decide._git(wt, *step)
        if out.returncode != 0:
            _warn(f"git {step[0]} failed: {sanitize.line(out.stderr)}")
            return
    if decide._has_remote(wt):
        out = decide._git(wt, "push", "--quiet", "origin", branch)
        if out.returncode != 0:
            _warn(f"git push failed: {sanitize.line(out.stderr)}")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notification_args(day: str, md_path: Path) -> list[str]:
    """The osascript argv for the fallback notification (pattern: core/hooks/notify.py)."""
    message = _one_line(f"Weekly report {day} was not emailed. Read {md_path}", MESSAGE_CHARS * 3)
    script = f'display notification "{_escape(message)}" with title "CTA"'
    return ["osascript", "-e", script]


def notify(cfg: learn_config.LearnConfig, day: str) -> int:
    reports = find_reports(cfg, day)
    if reports is None:
        raise DeliverError(f"no HTML report found for {day}")
    if platform.system() != "Darwin":
        print(f"notifications need macOS; the report is at {reports / f'{day}.md'}")
        return 0
    try:
        subprocess.run(notification_args(day, reports / f"{day}.md"), timeout=5, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"deliver.py: notification failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deliver.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prepare", "record", "notify"):
        p = sub.add_parser(name)
        p.add_argument("--date", required=True)
        p.add_argument("--config")
        if name == "record":
            p.add_argument("--result", required=True, choices=["sent", "fallback"])
            p.add_argument("--detail", required=True)
    args = ap.parse_args(argv)
    try:
        day = _check_date(args.date)
        cfg = learn_config.load_learn_config(Path(args.config) if args.config else None)
        if args.cmd == "prepare":
            print(json.dumps(prepare(cfg, day)))
        elif args.cmd == "record":
            print(record(cfg, day, args.result, args.detail))
        else:
            return notify(cfg, day)
    except DeliverError as err:
        print(f"deliver.py: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
