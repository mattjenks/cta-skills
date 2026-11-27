"""Skills that cannot work: missing frontmatter fields or links to files that do not exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

import gather
import sanitize
from model import RotItem
from rot import _common

KIND = "broken"
INSTALLED_PLUGINS = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)[^)]*\)")
_KEY = re.compile(r"^([A-Za-z_-]+):[ \t]*(.*)$")


# A scan root: (folder to scan, issue repo, folder the stable key is relative to, key prefix).
Root = tuple[Path, str, Path, str]


def _plugin_roots(cfg) -> list[Root]:
    try:
        data = json.loads(INSTALLED_PLUGINS.read_text())
    except (OSError, ValueError):
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    repos = gather._marketplace_repos()
    roots: list[Root] = []
    for key, entries in (plugins.items() if isinstance(plugins, dict) else ()):
        market = key.split("@", 1)[1] if "@" in key else None
        if not gather.personal(cfg, None, gather._owner(repos.get(market)) if market else None):
            continue
        for entry in entries if isinstance(entries, list) else ():
            path = entry.get("installPath") if isinstance(entry, dict) else None
            if isinstance(path, str) and Path(path) not in [r[0] for r in roots]:
                roots.append((Path(path), repos.get(market, "") if market else "",
                              Path(path), key))
    return roots


def _roots(cfg) -> list[Root]:
    roots = _plugin_roots(cfg)
    for repo in cfg.repos:
        if _common.personal_repo(repo, cfg):
            # The GitHub `owner/name` keeps the same path in two repos apart; never an absolute path.
            roots.append((repo / ".claude" / "skills", "", repo, _common.origin_repo(repo) or ""))
    return roots


def _frontmatter(lines: list[str]) -> set[str] | None:
    """Keys with a value in the leading `---` block, or None when there is no block."""
    if not lines or lines[0].strip() != "---":
        return None
    keys: set[str] = set()
    current = None
    for line in lines[1:]:
        if line.strip() == "---":
            return keys
        match = _KEY.match(line)
        if match:
            current = match.group(1)
            if match.group(2).strip() not in ("", ">", "|", ">-", "|-"):
                keys.add(current)
        elif current and line.strip() and line[:1] in (" ", "\t"):
            keys.add(current)
    return keys


def _stable(skill: Path, base: Path, prefix: str) -> str:
    """A location that does not change when a plugin is updated: `plugin@market/<relative path>`
    for a plugin skill, the path relative to the repo root for a repo skill."""
    try:
        rel = skill.relative_to(base).as_posix()
    except ValueError:
        rel = skill.name
    return sanitize.path(f"{prefix}/{rel}" if prefix else rel)


def _check_skill(skill: Path, repo: str, base: Path, prefix: str) -> list[RotItem]:
    try:
        lines = skill.read_text(errors="replace").splitlines()
    except OSError:
        return []
    where = sanitize.path(skill)
    stable = _stable(skill, base, prefix)
    items: list[RotItem] = []
    keys = _frontmatter(lines)
    missing = [k for k in ("name", "description") if keys is None or k not in keys]
    if missing:
        items.append(_common.item("broken", f"{where}:1",
                                  f"frontmatter is missing {' and '.join(missing)}",
                                  "add the missing fields to the SKILL.md frontmatter",
                                  fingerprint=f"broken|{stable}|frontmatter|{','.join(sorted(missing))}",
                                  repo=repo))
    for number, text in _common.scan_lines(skill):
        for target in _LINK.findall(text):
            if re.match(r"^([a-z][a-z0-9+.-]*:|#|/|~)", target, re.I) or ".." in Path(target).parts:
                continue
            rel = target.split("#", 1)[0].split("?", 1)[0]
            if rel and not (skill.parent / rel).exists():
                named = sanitize.path(rel)
                items.append(_common.item("broken", f"{where}:{number}",
                                          f"link to {named} does not exist",
                                          "fix the link or restore the file",
                                          fingerprint=f"broken|{stable}|link|{named}", repo=repo))
    return items


def check(week, cfg) -> list[RotItem]:
    items: list[RotItem] = []
    seen: set[Path] = set()
    for root, repo, base, prefix in _roots(cfg):
        if not root.is_dir():
            continue
        for skill in sorted(root.rglob("SKILL.md")):
            if skill not in seen:
                seen.add(skill)
                items.extend(_check_skill(skill, repo, base, prefix))
    return items
