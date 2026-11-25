"""Shared helpers for the rot checks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import sanitize
from model import RotItem

_OWNER = re.compile(r"[:/]([^/:]+)/[^/:]+?(?:\.git)?/?$")


def item(kind: str, location: str, problem: str, fix: str) -> RotItem:
    """A RotItem whose text is inert; callers pass external strings through `sanitize.path`."""
    return RotItem(kind, sanitize.line(location, keep="()"), sanitize.line(problem), sanitize.line(fix, keep="()"))


def origin_owner(repo: Path) -> str | None:
    """Owner of the repo's `origin` remote, or None. Git is called with an argv list."""
    try:
        done = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _OWNER.search(done.stdout.strip()) if done.returncode == 0 else None
    return match.group(1) if match else None


def personal_repo(repo: Path, cfg) -> bool:
    """False when the repo's origin owner is excluded (S4)."""
    owner = origin_owner(repo)
    return owner is None or owner.lower() not in {o.lower() for o in cfg.exclude_owners}


def scan_lines(path: Path):
    """(line number, text) of a markdown file outside fenced code blocks. Unreadable: nothing."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        marker = stripped[:3] if stripped[:3] in ("```", "~~~") else None
        if marker:
            fence = None if fence == marker else (fence or marker)
            continue
        if fence is None:
            yield number, line
