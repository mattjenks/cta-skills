"""Rules files that name a path that no longer exists."""

from __future__ import annotations

import re
from pathlib import Path

import sanitize
from model import RotItem
from rot import _common

KIND = "stale"
_TICKS = re.compile(r"`([^`\n]+)`")


def _candidate(token: str, root: Path) -> str | None:
    """A relative file path under an existing folder of root, or None."""
    if re.search(r"[\s*<>${}|]", token) or "://" in token or "@" in token:
        return None
    if token.startswith(("/", "~", "-", "#")) or ".." in Path(token).parts:
        return None
    token = token.split("#", 1)[0].split(":", 1)[0]
    if token and "/" in token and (root / token).parent.is_dir():
        return token
    return None


def _files(cfg):
    if cfg.kb is not None:
        for name in ("CLAUDE.md", "PREFERENCES.md"):
            yield cfg.kb / name, cfg.kb
    for repo in cfg.repos:
        if _common.personal_repo(repo, cfg):
            yield repo / "CLAUDE.md", repo


def check(week, cfg) -> list[RotItem]:
    items: list[RotItem] = []
    for path, root in _files(cfg):
        repo = _common.origin_repo(root) or ""
        for number, text in _common.scan_lines(path):
            for token in _TICKS.findall(text):
                rel = _candidate(token.strip(), root)
                if rel and not (root / rel).exists():
                    where, named = sanitize.path(path), sanitize.path(rel)
                    items.append(_common.item(
                        "stale", f"{where}:{number}",
                        f"names {named}, which does not exist",
                        "update or remove the line",
                        fingerprint=f"stale|{where}|{named}", repo=repo))
    return items
