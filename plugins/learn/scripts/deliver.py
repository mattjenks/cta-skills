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


def _within(path: Path, root: Path) -> bool:
    return root.resolve() in path.resolve().parents


def _delivery_worktree(cfg: learn_config.LearnConfig, day: str) -> Path:
    """A kb worktree on `learn/delivery-<day>` cut from the default branch; reused when present."""
    if cfg.kb is None:
        raise DeliverError("kb is not configured")
    kb = cfg.kb
    path = decide.WORKTREE_ROOT / f"learn-delivery-{day}"
    branch = f"learn/delivery-{day}"
    if (path / ".git").exists():
        return path
    if decide._has_remote(kb):
        decide._git(kb, "fetch", "--quiet")
    exists = decide._git(kb, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DeliverError(f"cannot create the delivery worktree: {type(exc).__name__}") from None
    if exists.returncode == 0:
        made = decide._git(kb, "worktree", "add", str(path), branch)
    else:
        made = decide._git(kb, "worktree", "add", "-b", branch, str(path),
                           decide._default_branch(kb))
    if made.returncode != 0:
        raise DeliverError("cannot create the delivery worktree: " + sanitize.line(made.stderr))
    return path


def record(cfg: learn_config.LearnConfig, day: str, result: str, detail: str) -> Path:
    """Write the delivery record; never into the live checkout.

    Beside the report when that sits in the `learn-report-<day>` worktree, otherwise in a fresh
    `learn-delivery-<day>` worktree on its own branch and pull request.
    """
    reports = find_reports(cfg, day)
    if reports is None:
        raise DeliverError(f"no HTML report found for {day}")
    row = {"date": day, "result": result, "detail": sanitize.line(detail),
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    report_wt = decide.WORKTREE_ROOT / f"learn-report-{day}"
    if _within(reports, report_wt):
        path = reports / f"{day}.delivery.json"
        path.write_text(json.dumps(row, indent=2) + "\n")
        _commit_record(path, day)
        return path
    wt = _delivery_worktree(cfg, day)
    path = wt / cfg.kb_dir / "reports" / f"{day}.delivery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n")
    _publish_record(wt, path, day)
    return path


def _publish_record(wt: Path, path: Path, day: str) -> None:
    """Commit the record on `learn/delivery-<day>`, push it and open a PR. Failures warn."""
    branch = f"learn/delivery-{day}"
    rel = str(path.relative_to(wt))
    decide._git(wt, "add", "--", rel)
    done = decide._git(wt, "-c", "commit.gpgsign=false", "commit", "-q", "-m",
                       f"docs(learn): delivery record {day}", "--only", "--", rel)
    if done.returncode != 0:
        _warn("could not commit the delivery record: " + sanitize.line(done.stderr or done.stdout))
        return
    if not decide._has_remote(wt):
        return
    pushed = decide._git(wt, "push", "--quiet", "-u", "origin", branch)
    if pushed.returncode != 0:
        _warn("git push failed: " + sanitize.line(pushed.stderr))
        return
    listed = decide._gh(["pr", "list", "--head", branch, "--state", "open", "--json", "url",
                         "--jq", ".[0].url"], wt)
    if listed.returncode == 0 and listed.stdout.strip():
        return
    made = decide._gh(["pr", "create", "--base", decide._default_branch(wt), "--head", branch,
                       "--title", f"Learn delivery record {day}",
                       "--body", "Delivery record for the weekly report."], wt)
    if made.returncode != 0:
        _warn("could not open the delivery PR: " + sanitize.line(made.stderr))


def _warn(message: str) -> None:
    print(f"deliver.py: warning: {message}", file=sys.stderr)


def _commit_record(path: Path, day: str) -> None:
    """Commit (and push, when a remote exists) the record on the report's branch.

    Only when the file sits in the `learn-report-<day>` worktree on `learn/report-<day>`; never
    the default branch. A failure is a warning: the record still stands.
    """
    wt = decide.WORKTREE_ROOT / f"learn-report-{day}"
    branch = f"learn/report-{day}"
    if not _within(path, wt):
        return
    head = decide._git(wt, "rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != branch:
        _warn(f"{wt.name} is not on {branch}; the delivery record was not committed")
        return
    rel = str(path.resolve().relative_to(wt.resolve()))
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
