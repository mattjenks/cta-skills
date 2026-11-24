#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Record the owner's decision on a report recommendation; an accept files a GitHub issue.

Usage: decide.py <id> accept|defer|reject [--reason-stdin] [--config PATH]

Exit 0 done (or already decided: the existing row is printed); 1 a tool failed; 2 bad input
(malformed or unknown ID, reject without a reason); 3 no repo to file in; 4 the issue body
failed the secret scan.

Every decision is appended to `decisions.jsonl` in a worktree of the knowledge base on branch
`learn/decisions`, committed and pushed, with one PR. The reason is read from stdin only, so it
never passes through a shell argument.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import gather
import learn_config
import report
import sanitize
from learn_config import LearnConfig

ID_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}-R[1-5]")
REPO_PATTERN = re.compile(r"[\w.-]+/[\w.-]+")
WORKTREE_ROOT = Path.home() / ".local" / "share" / "cta" / "kb-worktrees"
BRANCH = "learn/decisions"
LABEL = "cta-learn"
_PATHISH = re.compile(r"(?<![\w:])(?:~|/[\w.-]+)(?:/[\w.@+-]+)+")
_GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX")


class DecideError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- subprocess

def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _GIT_VARS}


def _run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=cwd, env=_env(), capture_output=True, text=True,
                              timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: {type(exc).__name__}")


def _gh(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _run(["gh", *argv], cwd)


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(cwd), *argv])


def _warn(message: str) -> None:
    print(f"decide.py: warning: {message}", file=sys.stderr)


# ---------------------------------------------------------------- telemetry

def _text(key: str, value: object) -> dict:
    return {"key": key, "value": {"stringValue": str(value)}}


def build_event(row: dict) -> dict:
    """OTLP/HTTP JSON log body for one decision. The reason text is never included."""
    attributes = [_text("event.name", "cta.learn.decision"), _text("id", row["id"]),
                  _text("skill", row["skill"]), _text("signal", row["signal"]),
                  _text("decision", row["decision"])]
    return {"resourceLogs": [{
        "resource": {"attributes": [_text("service.name", "cta-learn")]},
        "scopeLogs": [{"logRecords": [{
            "timeUnixNano": str(time.time_ns()),
            "severityText": "INFO",
            "body": {"stringValue": "cta learn decision"},
            "attributes": attributes,
        }]}],
    }]}


# An opener with only the http and https handlers: file:// and other schemes cannot be opened.
_OPENER = urllib.request.build_opener(urllib.request.HTTPHandler, urllib.request.HTTPSHandler)


def send(event: dict, endpoint: str, timeout: float = 5.0) -> None:
    if urllib.parse.urlsplit(endpoint).scheme not in ("http", "https"):
        raise ValueError("endpoint must be http or https")
    req = urllib.request.Request(
        endpoint, data=json.dumps(event).encode(), headers={"Content-Type": "application/json"})
    _OPENER.open(req, timeout=timeout).read()


# ---------------------------------------------------------------- knowledge base

def _default_branch(kb: Path) -> str:
    out = _git(kb, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip().split("/", 1)[-1]
    out = _git(kb, "rev-parse", "--abbrev-ref", "HEAD")
    name = out.stdout.strip()
    return name if out.returncode == 0 and name not in ("", "HEAD") else "main"


def _has_remote(path: Path) -> bool:
    return bool(_git(path, "remote").stdout.strip())


def _worktree(cfg: LearnConfig) -> Path:
    """The `learn/decisions` worktree of the knowledge base; created once, then reused."""
    if cfg.kb is None:
        raise DecideError(2, "kb is not configured")
    path = WORKTREE_ROOT / "learn-decisions"
    if (path / ".git").exists():
        return path
    if _has_remote(cfg.kb):
        _git(cfg.kb, "fetch", "--quiet")
    exists = _git(cfg.kb, "rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if exists.returncode == 0:
        made = _git(cfg.kb, "worktree", "add", str(path), BRANCH)
    else:
        made = _git(cfg.kb, "worktree", "add", "-b", BRANCH, str(path), _default_branch(cfg.kb))
    if made.returncode != 0:
        raise DecideError(1, "cannot create the learn/decisions worktree: "
                             + sanitize.line(made.stderr))
    return path


def _roots(cfg: LearnConfig, day: str) -> list[Path]:
    """Places a report or the decisions log may live: the live checkout, then the worktrees."""
    roots = [learn_config.learn_dir(cfg)]
    for name in ("learn-decisions", f"learn-report-{day}"):
        roots.append(WORKTREE_ROOT / name / cfg.kb_dir)
    return roots


def _find_row(cfg: LearnConfig, rec_id: str) -> dict | None:
    for root in _roots(cfg, rec_id[:10]):
        try:
            lines = (root / "decisions.jsonl").read_text().splitlines()
        except OSError:
            continue
        for raw in lines:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id") == rec_id:
                return row
    return None


def _load_report(cfg: LearnConfig, rec_id: str) -> report.Report:
    for root in _roots(cfg, rec_id[:10]):
        try:
            return report.from_json((root / "reports" / f"{rec_id[:10]}.json").read_text())
        except (OSError, ValueError, KeyError, TypeError):
            continue
    raise DecideError(2, f"no report found for {rec_id[:10]}")


# ---------------------------------------------------------------- repo and issue

def resolve_repo(skill: str, cfg: LearnConfig, marketplace: str | None = None
                 ) -> tuple[str, str]:
    """(owner/repo, reason): the skill's marketplace repo when the owner can push to it."""
    repo = gather._marketplace_repos().get(marketplace) if marketplace else None
    if repo is None:
        why = "no marketplace repo is known for the skill"
    elif not REPO_PATTERN.fullmatch(repo):
        why = "the skill's marketplace repo name is not valid"
    else:
        out = _gh(["api", f"repos/{repo}", "--jq", ".permissions.push"])
        if out.returncode == 0 and out.stdout.strip() == "true":
            return repo, f"filed on the skill's repo {repo}"
        why = f"skill repo {repo} is not writable"
    if cfg.fallback_repo and REPO_PATTERN.fullmatch(cfg.fallback_repo):
        return cfg.fallback_repo, f"{why}; used the fallback repo"
    raise DecideError(3, "no repo to file in")


def _no_paths(text: str) -> str:
    return _PATHISH.sub("[path]", text)


def _issue_body(rec: report.Recommendation, day: str) -> str:
    c = rec.candidate

    def prose(value: str) -> str:
        return _no_paths(sanitize.line(value))

    return "\n".join([
        f"Skill: {sanitize.name(c.skill)}",
        f"Signal: {sanitize.name(c.signal)}",
        "",
        "## Problem", prose(rec.problem), "",
        "## Why it matters", prose(rec.why), "",
        "## Change", prose(rec.change), "",
        "## Measure", prose(rec.measure), "",
        f"Metric: {sanitize.name(c.metric)} = {c.value:.2f}",
        f"Report date: {day}",
        "",
    ])


def _scan(body: str) -> None:
    """gitleaks over the body file alone; fails closed (exit 4) on a hit or any scan problem."""
    with tempfile.TemporaryDirectory(prefix="cta-learn-body-") as tmp:
        root = Path(tmp)
        src = root / "body"
        src.mkdir()
        ignore = root / "no-ignore"
        ignore.mkdir()
        (src / "body.md").write_text(body)
        out = root / "report.json"
        proc = _run(["gitleaks", "dir", "--no-banner", "--no-color", "--redact",
                     "--report-format", "json", "--ignore-gitleaks-allow",
                     "--gitleaks-ignore-path", str(ignore), "--report-path", str(out),
                     str(src)])
        try:
            findings = json.loads(out.read_text())
        except (OSError, ValueError):
            findings = None
    if proc.returncode == 127 or not isinstance(findings, list):
        raise DecideError(4, "the secret scan could not run; nothing was filed")
    if findings or proc.returncode != 0:
        raise DecideError(4, "the issue body looks like it holds a secret; nothing was filed")


def _file_issue(repo: str, rec: report.Recommendation, rec_id: str, day: str) -> str:
    skill = sanitize.name(rec.candidate.skill)
    title = f"{skill}: {sanitize.name(rec.candidate.signal)} ({rec_id})"
    body = _issue_body(rec, day)
    _scan(body)
    _gh(["label", "create", LABEL, "--repo", repo, "--color", "0e8a16",
         "--description", "Recommendation from the weekly learn report"])  # exists is fine
    with tempfile.TemporaryDirectory(prefix="cta-learn-issue-") as tmp:
        body_file = Path(tmp) / "body.md"
        body_file.write_text(body)
        made = _gh(["issue", "create", "--repo", repo, "--title", title, "--label", LABEL,
                    "--body-file", str(body_file)])
    url = made.stdout.strip().splitlines()[-1] if made.stdout.strip() else ""
    if made.returncode != 0 or not url.startswith("https://"):
        raise DecideError(1, "gh could not create the issue: " + sanitize.line(made.stderr))
    return url


# ---------------------------------------------------------------- publishing

def _publish(worktree: Path, rec_id: str, decision: str, log: Path) -> None:
    rel = str(log.relative_to(worktree))
    _git(worktree, "add", "--", rel)
    done = _git(worktree, "commit", "-m", f"docs(learn): decision {rec_id} {decision}",
                "--only", "--", rel)
    if done.returncode != 0:
        _warn("could not commit the decision: " + sanitize.line(done.stderr or done.stdout))
        return
    if not _has_remote(worktree):
        return
    pushed = _git(worktree, "push", "-u", "origin", BRANCH)
    if pushed.returncode != 0:
        _warn("could not push learn/decisions: " + sanitize.line(pushed.stderr))
        return
    listed = _gh(["pr", "list", "--head", BRANCH, "--state", "open", "--json", "url",
                  "--jq", ".[0].url"], worktree)
    if listed.returncode == 0 and listed.stdout.strip():
        return
    base = _default_branch(worktree)
    made = _gh(["pr", "create", "--base", base, "--head", BRANCH,
                "--title", "Learn decisions",
                "--body", "Decisions on weekly report recommendations."], worktree)
    if made.returncode != 0:
        _warn("could not open the decisions PR: " + sanitize.line(made.stderr))


def _append(log: Path, row: dict) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    try:
        existing = log.read_text()
        prefix = "" if not existing or existing.endswith("\n") else "\n"
    except OSError:
        pass
    with open(log, "a") as fh:
        fh.write(prefix + json.dumps(row, ensure_ascii=True) + "\n")


# ---------------------------------------------------------------- decide

def decide(cfg: LearnConfig, rec_id: str, decision: Literal["accept", "defer", "reject"],
           reason: str | None) -> dict:
    """Log one decision (filing the issue on accept). A repeat of an ID returns the old row."""
    if not ID_PATTERN.fullmatch(rec_id):
        raise DecideError(2, "malformed recommendation ID")
    try:
        date.fromisoformat(rec_id[:10])
    except ValueError:
        raise DecideError(2, "malformed recommendation ID") from None
    if decision not in ("accept", "defer", "reject"):
        raise DecideError(2, "decision must be accept, defer or reject")
    reason = reason.strip() if reason is not None else None
    if decision == "reject" and not reason:
        raise DecideError(2, "reject needs a reason")
    existing = _find_row(cfg, rec_id)
    if existing is not None:
        return existing

    rep = _load_report(cfg, rec_id)
    rec = next((r for r in rep.recommendations if r.id == rec_id), None)
    if rec is None:
        raise DecideError(2, f"unknown recommendation {rec_id}")
    cand = rec.candidate
    usage = next((s for s in rep.top if s.skill == cand.skill), None)

    repo = url = None
    note = reason
    if decision == "accept":
        repo, why = resolve_repo(cand.skill, cfg, usage.marketplace if usage else None)
        url = _file_issue(repo, rec, rec_id, rep.date)
        note = f"{reason}; {why}" if reason else why
    row = {"id": rec_id, "date": rep.date, "skill": cand.skill, "fingerprint": cand.fingerprint,
           "decision": decision, "reason": note, "repo": repo, "issue_url": url,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "signal": cand.signal, "metric": cand.metric, "value": cand.value}

    worktree = _worktree(cfg)
    log = worktree / cfg.kb_dir / "decisions.jsonl"
    _append(log, row)
    _publish(worktree, rec_id, decision, log)
    try:
        send(build_event(row), cfg.otlp_url.rstrip("/") + "/v1/logs")
    except Exception as exc:  # a missing collector must never fail a decision
        _warn(f"decision event not sent ({type(exc).__name__})")
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="decide.py", description=__doc__.splitlines()[0])
    ap.add_argument("id")
    ap.add_argument("decision", choices=["accept", "defer", "reject"])
    ap.add_argument("--reason-stdin", action="store_true")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    reason = sys.stdin.read() if args.reason_stdin else None
    cfg = learn_config.load_learn_config(Path(args.config) if args.config else None)
    try:
        row = decide(cfg, args.id, args.decision, reason)
    except DecideError as err:
        print(f"decide.py: {err}", file=sys.stderr)
        return err.code
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
