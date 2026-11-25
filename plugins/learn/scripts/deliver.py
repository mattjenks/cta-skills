#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Prepare, record and fall back for the delivery of the weekly report email.

Usage:
  deliver.py prepare --date YYYY-MM-DD [--config PATH]   print {to, subject, html_path, md_path}
  deliver.py record  --date YYYY-MM-DD --result sent|fallback|skipped --detail TEXT [--config PATH]
  deliver.py notify  --date YYYY-MM-DD [--result skipped|fallback] [--config PATH]

The recipient comes only from `[learn.delivery] to`; unset prints `to: null`. Exit 2: bad input,
a malformed recipient, `skipped` recorded while an address is set, or the report is missing.
Reports and records live in the local reports folder. The script never sends mail.
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
    """The local `reports/` folder when it holds this day's HTML file."""
    reports = learn_config.reports_dir(cfg)
    return reports if (reports / f"{day}.html").is_file() else None


def prepare(cfg: learn_config.LearnConfig, day: str) -> dict:
    to = cfg.delivery.to or None
    if to is not None and not RECIPIENT.fullmatch(to):
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
    """Write `<reports>/<day>.delivery.json` in the local folder. Runs no git."""
    if result == "skipped" and cfg.delivery.to:
        raise DeliverError("cannot record skipped: an address is configured")
    reports = find_reports(cfg, day)
    if reports is None:
        raise DeliverError(f"no HTML report found for {day}")
    row = {"date": day, "result": result, "detail": sanitize.line(detail),
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = reports / f"{day}.delivery.json"
    path.write_text(json.dumps(row, indent=2) + "\n")
    return path


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notification_args(day: str, result: str) -> list[str]:
    """The osascript argv for the notification (pattern: core/hooks/notify.py).

    One of two fixed sentences; `result` only picks which and is never interpolated.
    """
    if result == "skipped":
        message = f"Weekly report {_one_line(day, 40)} is ready. Open /cta-reports in Claude Code."
    else:
        message = (f"Weekly report {_one_line(day, 40)} was not emailed. "
                   "Open /cta-reports in Claude Code.")
    script = f'display notification "{_escape(message)}" with title "CTA"'
    return ["osascript", "-e", script]


def notify(cfg: learn_config.LearnConfig, day: str, result: str = "fallback") -> int:
    reports = find_reports(cfg, day)
    if reports is None:
        raise DeliverError(f"no HTML report found for {day}")
    if platform.system() != "Darwin":
        print(f"notifications need macOS; open /cta-reports in Claude Code for {day}")
        return 0
    try:
        subprocess.run(notification_args(day, result), timeout=5, check=False,
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
            p.add_argument("--result", required=True, choices=["sent", "fallback", "skipped"])
            p.add_argument("--detail", required=True)
        if name == "notify":
            p.add_argument("--result", choices=["skipped", "fallback"], default="fallback")
    args = ap.parse_args(argv)
    try:
        day = _check_date(args.date)
        cfg = learn_config.load_learn_config(Path(args.config) if args.config else None)
        if args.cmd == "prepare":
            print(json.dumps(prepare(cfg, day)))
        elif args.cmd == "record":
            print(record(cfg, day, args.result, args.detail))
        else:
            return notify(cfg, day, args.result)
    except DeliverError as err:
        print(f"deliver.py: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
