#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Knowledge-base worktrees, project mapping and the active-build pointer.

The build loop writes its documents into a git worktree of the user's knowledge
base, on its own branch, so the live checkout is never touched. Stdlib only.

CLI (prints JSON):
  kbwork.py open --kb PATH --slug S --topic T [--projects-dir D] [--date YYYY-MM-DD]
                 [--root DIR] [--repo PATH]
  kbwork.py pointer --repo PATH
  kbwork.py close --repo PATH
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
DEFAULT_ROOT = Path.home() / ".local/share/cta/kb-worktrees"
POINTER = Path(".cta") / "active-build"


class KbError(Exception):
    """The knowledge base cannot be used for a build."""


@dataclass(frozen=True)
class Build:
    slug: str
    topic: str
    date: Date
    worktree: Path
    branch: str
    folder: Path


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _ok(cwd: Path, *args: str) -> bool:
    try:
        return _git(cwd, *args, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _out(cwd: Path, *args: str) -> str:
    try:
        r = _git(cwd, *args, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _check_slug(value: str, what: str) -> None:
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        raise ValueError(f"{what} {value!r} must match [a-z0-9][a-z0-9-]{{0,62}}")


# --- project mapping ---------------------------------------------------------


def record_project(config_path: Path, repo: Path, slug: str) -> None:
    """Add `"<resolved repo>" = "<slug>"` under [projects] without touching other lines."""
    _check_slug(slug, "slug")
    key = json.dumps(str(Path(repo).expanduser().resolve()))
    entry = f"{key} = {json.dumps(slug)}"
    config_path = Path(config_path)
    lines = config_path.read_text().splitlines() if config_path.exists() else []

    header = next((i for i, l in enumerate(lines) if l.strip() == "[projects]"), None)
    if header is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[projects]", entry]
    else:
        end = len(lines)
        for i in range(header + 1, len(lines)):
            if lines[i].lstrip().startswith("["):
                end = i
                break
        existing = next(
            (i for i in range(header + 1, end) if lines[i].lstrip().startswith(key + " ")
             or lines[i].lstrip().startswith(key + "=")),
            None,
        )
        if existing is not None:
            lines[existing] = entry
        else:
            at = end
            while at > header + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, entry)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines) + "\n")


# --- worktrees ---------------------------------------------------------------


def _require_repo(kb: Path) -> None:
    if not Path(kb).is_dir() or not _ok(kb, "rev-parse", "--git-dir"):
        raise KbError(f"knowledge base at {kb} is not a git repo; run /core:init-kb")


def _base_ref(kb: Path) -> str:
    """Default branch ref: origin/HEAD, else a conventional local default."""
    head = _out(kb, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head and _ok(kb, "rev-parse", "--verify", "-q", head):
        return head
    configured = _out(kb, "config", "init.defaultBranch")
    names = [n for n in (configured, "main", "master", "trunk") if n]
    for name in names:
        if _ok(kb, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}"):
            return f"origin/{name}"
    for name in names:
        if _ok(kb, "rev-parse", "--verify", "-q", f"refs/heads/{name}"):
            return name
    current = _out(kb, "symbolic-ref", "--short", "HEAD")
    if current:
        return current
    raise KbError(f"knowledge base at {kb} has no default branch to build from")


def _worktree_paths(kb: Path) -> dict[Path, str]:
    """Registered worktrees: resolved path -> branch name ('' when detached)."""
    found: dict[Path, str] = {}
    path: Path | None = None
    for line in _out(kb, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[9:]).resolve()
            found[path] = ""
        elif line.startswith("branch ") and path is not None:
            found[path] = line[7:].removeprefix("refs/heads/")
    return found


def open_build(
    kb: Path,
    projects_dir: str,
    slug: str,
    topic: str,
    today: Date,
    root: Path | None = None,
) -> Build:
    """Create (or reuse) the worktree for one build and its documents folder."""
    _check_slug(slug, "slug")
    _check_slug(topic, "topic")
    kb = Path(kb).expanduser()
    root = Path(root).expanduser() if root is not None else DEFAULT_ROOT
    _require_repo(kb)

    name = f"{slug}-{today.isoformat()}-{topic}"
    branch = f"build/{name}"
    worktree = root / name

    if _out(kb, "remote"):
        _git(kb, "fetch", "--quiet", check=False)  # offline: build from what we have

    registered = _worktree_paths(kb)
    if worktree.resolve() in registered:
        if registered[worktree.resolve()] != branch:
            raise KbError(f"worktree {worktree} exists but is not on branch {branch}")
    elif worktree.exists():
        raise KbError(f"{worktree} exists and is not a worktree of {kb}")
    else:
        root.mkdir(parents=True, exist_ok=True)
        if _ok(kb, "rev-parse", "--verify", "-q", f"refs/heads/{branch}"):
            args = ["worktree", "add", str(worktree), branch]
        else:
            args = ["worktree", "add", "-b", branch, str(worktree), _base_ref(kb)]
        try:
            _git(kb, *args)
        except subprocess.CalledProcessError as exc:
            raise KbError(f"git worktree add failed: {exc.stderr.strip()}") from exc

    folder = worktree / projects_dir / slug / "builds" / f"{today.isoformat()}-{topic}"
    folder.mkdir(parents=True, exist_ok=True)
    return Build(slug, topic, today, worktree, branch, folder)


def close_build(build: Build) -> str:
    """Remove the worktree only if its branch is merged or gone on the remote."""
    wt = build.worktree
    if not wt.exists():
        return f"worktree {wt} already removed"
    common = _out(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    kb = Path(common).parent if common else wt
    if _out(kb, "remote"):
        _git(kb, "fetch", "--quiet", "--prune", check=False)

    merged = False
    try:
        base = _base_ref(kb)
        merged = _ok(kb, "merge-base", "--is-ancestor", build.branch, base)
    except KbError:
        pass
    gone = "[gone]" in _out(kb, "for-each-ref", "--format=%(upstream:track)", f"refs/heads/{build.branch}")
    if not (merged or gone):
        return f"kept {wt}: branch {build.branch} is not merged and not deleted on the remote"
    if _out(wt, "status", "--porcelain"):
        return f"kept {wt}: it has uncommitted changes"
    try:
        _git(kb, "worktree", "remove", str(wt))
    except subprocess.CalledProcessError as exc:
        return f"kept {wt}: {exc.stderr.strip()}"
    _git(kb, "branch", "-d", build.branch, check=False)
    return f"removed {wt}"


# --- active-build pointer ----------------------------------------------------


def _exclude_file(repo: Path) -> Path | None:
    out = _out(repo, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    return Path(out) if out else None


def write_pointer(repo: Path, build: Build) -> Path:
    repo = Path(repo)
    pointer = repo / POINTER
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "worktree": str(build.worktree),
                "folder": str(build.folder),
                "slug": build.slug,
                "topic": build.topic,
                "branch": build.branch,
            },
            indent=2,
        )
        + "\n"
    )
    exclude = _exclude_file(repo)
    if exclude is not None:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text() if exclude.exists() else ""
        if ".cta/" not in existing.splitlines():
            sep = "" if not existing or existing.endswith("\n") else "\n"
            exclude.write_text(existing + sep + ".cta/\n")
    return pointer


def read_pointer(repo: Path) -> Build | None:
    try:
        data = json.loads((Path(repo) / POINTER).read_text())
        slug, topic, branch = data["slug"], data["topic"], data["branch"]
        stamp = branch.removeprefix(f"build/{slug}-")[:10]
        return Build(
            slug=slug,
            topic=topic,
            date=Date.fromisoformat(stamp),
            worktree=Path(data["worktree"]),
            branch=branch,
            folder=Path(data["folder"]),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def clear_pointer(repo: Path) -> None:
    (Path(repo) / POINTER).unlink(missing_ok=True)


# --- CLI ---------------------------------------------------------------------


def _as_json(build: Build) -> dict:
    return {
        "slug": build.slug,
        "topic": build.topic,
        "date": build.date.isoformat(),
        "worktree": str(build.worktree),
        "branch": build.branch,
        "folder": str(build.folder),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    op = sub.add_parser("open")
    op.add_argument("--kb", required=True, type=Path)
    op.add_argument("--slug", required=True)
    op.add_argument("--topic", required=True)
    op.add_argument("--projects-dir", default="projects")
    op.add_argument("--date", type=Date.fromisoformat, default=None)
    op.add_argument("--root", type=Path, default=None)
    op.add_argument("--repo", type=Path, default=None, help="write the active-build pointer here")
    for name in ("pointer", "close"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", required=True, type=Path)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "open":
            build = open_build(
                args.kb, args.projects_dir, args.slug, args.topic,
                args.date or Date.today(), args.root,
            )
            if args.repo:
                write_pointer(args.repo, build)
            print(json.dumps(_as_json(build)))
        elif args.cmd == "pointer":
            build = read_pointer(args.repo)
            print(json.dumps(_as_json(build) if build else None))
        else:
            build = read_pointer(args.repo)
            if build is None:
                print(json.dumps({"closed": False, "message": "no active build"}))
            else:
                message = close_build(build)
                removed = message.startswith(("removed", "worktree"))
                if removed:
                    clear_pointer(args.repo)
                print(json.dumps({"closed": removed, "message": message}))
    except (KbError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
