#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Knowledge-base worktrees, project mapping and the active-build pointer.

The build loop writes its documents into a git worktree of the user's knowledge
base, on its own branch, so the live checkout is never touched. Writing the
active-build pointer also installs the commit gate (gitgate.install_gate); clearing
it removes the gate unless the repo tracks `.cta/security.toml`. Stdlib only.

CLI (prints JSON):
  kbwork.py open --kb PATH --slug S --topic T [--projects-dir D] [--date YYYY-MM-DD]
                 [--root DIR] [--repo PATH]
  kbwork.py project --repo PATH [--slug S] [--config PATH]   (resolve, or record with --slug)
  kbwork.py pointer --repo PATH
  kbwork.py close --repo PATH
  kbwork.py clear --repo PATH  (drop the pointer; the gate too unless opted in or another worktree builds)
  kbwork.py gate --repo PATH   (reinstall the commit gate when a build is active and it is missing or stale)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path
from typing import NamedTuple

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


def _fetch(kb: Path, *extra: str) -> None:
    """Best-effort fetch: offline or hung remotes degrade to local refs."""
    try:
        _git(kb, "fetch", "--quiet", *extra, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _check_slug(value: str, what: str) -> None:
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        raise ValueError(f"{what} {value!r} must match [a-z0-9][a-z0-9-]{{0,62}}")


# --- project mapping ---------------------------------------------------------


_HEADER = re.compile(r"^\s*\[\s*projects\s*\]\s*(#.*)?$")
_ANY_HEADER = re.compile(r"^\s*\[")


def _toml_str(value: str) -> str:
    """TOML basic string: escape backslash, quote and control characters (incl. DEL)."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _parses(text: str) -> bool:
    try:
        tomllib.loads(text)
        return True
    except tomllib.TOMLDecodeError:
        return False


def record_project(config_path: Path, repo: Path, slug: str) -> None:
    """Add `"<resolved repo>" = "<slug>"` under [projects] without touching other lines.

    Refuses (KbError, file untouched) when the existing config is not valid TOML or
    its `projects` entry is not a plain `[projects]` table.
    """
    _check_slug(slug, "slug")
    repo_key = str(Path(repo).expanduser().resolve())
    entry = f"{_toml_str(repo_key)} = {_toml_str(slug)}"
    path = Path(os.path.realpath(Path(config_path).expanduser()))

    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise KbError(f"{path} is not valid TOML ({exc}); not editing it") from exc
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    existing = before.get("projects")
    if existing is not None and not isinstance(existing, dict):
        raise KbError(f"{path}: `projects` is not a table; not editing it")
    headers = [i for i, l in enumerate(lines) if _HEADER.match(l)]
    if existing is not None and len(headers) != 1:
        raise KbError(f"{path}: cannot find a single plain [projects] table; not editing it")

    if not headers:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[projects]", entry]
    else:
        header = headers[0]
        end = len(lines)
        for i in range(header + 1, len(lines)):
            if _ANY_HEADER.match(lines[i]) and _parses("\n".join(lines[:i])):
                end = i
                break
        same = None
        for i in range(header + 1, end):
            try:
                one = tomllib.loads(lines[i])
            except tomllib.TOMLDecodeError:
                continue
            if repo_key in one:
                same = i
        if same is not None:
            lines[same] = entry
        else:
            at = end
            while at > header + 1 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, entry)

    out = nl.join(lines) + nl
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError as exc:
        raise KbError(f"{path}: edit would produce invalid TOML ({exc}); not editing it") from exc
    expected = dict(before)
    expected["projects"] = {**(existing or {}), repo_key: slug}
    if after != expected:
        raise KbError(f"{path}: edit did not round-trip; not editing it")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-kbwork")
    tmp.write_bytes(out.encode("utf-8"))
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


# --- worktrees ---------------------------------------------------------------


def _require_repo(kb: Path) -> None:
    top = _out(kb, "rev-parse", "--show-toplevel") if Path(kb).is_dir() else ""
    if not top or Path(top).resolve() != Path(kb).resolve():
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
        _fetch(kb)

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


class CloseResult(NamedTuple):
    removed: bool
    reason: str


def close_build(build: Build) -> CloseResult:
    """Remove the worktree only if its work is safe: merged, or its remote branch was
    deleted and nothing exists only locally."""
    wt = build.worktree
    if not wt.exists():
        return CloseResult(True, f"worktree {wt} already removed")
    common = _out(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    kb = Path(common).parent if common else wt
    ref = f"refs/heads/{build.branch}"
    tip = _out(kb, "rev-parse", "--verify", "-q", ref)
    pushed = _out(kb, "rev-parse", "--verify", "-q", f"{build.branch}@{{upstream}}")
    if _out(kb, "remote"):
        _fetch(kb, "--prune")

    merged = False
    try:
        merged = _ok(kb, "merge-base", "--is-ancestor", build.branch, _base_ref(kb))
    except KbError:
        pass
    gone = "[gone]" in _out(kb, "for-each-ref", "--format=%(upstream:track)", ref)
    if not merged:
        if not gone:
            return CloseResult(False, f"kept {wt}: branch {build.branch} is not merged and not deleted on the remote")
        if not tip or tip != pushed:
            return CloseResult(False, f"kept {wt}: branch {build.branch} has commits that were never pushed")
    if _out(wt, "status", "--porcelain"):
        return CloseResult(False, f"kept {wt}: it has uncommitted changes")
    try:
        _git(kb, "worktree", "remove", str(wt))
    except subprocess.CalledProcessError as exc:
        return CloseResult(False, f"kept {wt}: {exc.stderr.strip()}")
    if _ok(kb, "branch", "-d", build.branch):
        return CloseResult(True, f"removed {wt}")
    return CloseResult(True, f"removed {wt}; kept branch {build.branch} (git would not delete it as merged)")


# --- active-build pointer ----------------------------------------------------


def exclude_path(repo: Path, entry: str) -> bool:
    """Idempotently add `entry` to the repo's info/exclude. Warns on stderr and
    returns False when git cannot say where that file is."""
    repo = Path(repo)
    rel = _out(repo, "rev-parse", "--git-path", "info/exclude")
    if not rel:
        print(f"warning: could not locate git info/exclude in {repo}; {entry} not excluded", file=sys.stderr)
        return False
    exclude = Path(rel)
    if not exclude.is_absolute():
        exclude = repo / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if entry not in existing.splitlines():
        sep = "" if not existing or existing.endswith("\n") else "\n"
        exclude.write_text(existing + sep + entry + "\n")
    return True


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
    exclude_path(repo, ".cta/active-build")
    import gitgate  # here, not at the top: gitgate imports this module

    gitgate.install_gate(repo)
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


def _other_worktree_builds(repo: Path) -> bool:
    """Another linked worktree of this repo still has an active-build pointer."""
    here = Path(repo).resolve()
    out = _out(here, "worktree", "list", "--porcelain")
    for line in out.splitlines():
        if line.startswith("worktree "):
            other = Path(line[len("worktree "):])
            try:
                same = other.resolve() == here
            except OSError:
                continue
            if not same and (other / POINTER).exists():
                return True
    return False


def clear_pointer(repo: Path) -> None:
    """Remove the pointer and the commit gate, unless the repo opted in to a permanent gate
    with a tracked `.cta/security.toml` or another worktree of it is still mid-build (the
    gate is shared through the common git config)."""
    (Path(repo) / POINTER).unlink(missing_ok=True)
    import gitgate

    if not gitgate.opted_in(repo) and not _other_worktree_builds(repo):
        try:
            gitgate.uninstall_gate(repo)
        except gitgate.GateError as exc:  # the gate stays on: the safe side
            print(f"warning: commit gate not removed from {repo}: {exc}", file=sys.stderr)


def ensure_gate(repo: Path) -> bool:
    """With an active build, (re)install the commit gate when it is missing or its hooksPath is
    stale (the plugin moved on an update). True when it had to be repaired."""
    import gitgate

    if read_pointer(repo) is None or gitgate.gate_installed(repo):
        return False
    gitgate.install_gate(repo)
    return True


def project_info(repo: Path, config: Path | None = None, slug: str | None = None) -> dict:
    """The knowledge base, projects folder and project slug for `repo`; records `slug` first when given."""
    path = Path(config) if config else Path(
        os.environ.get("CTA_CONFIG") or Path.home() / ".config/cta/config.toml"
    )
    path = path.expanduser()
    try:
        data = tomllib.loads(path.read_text()) if path.exists() else {}
    except tomllib.TOMLDecodeError as exc:
        raise KbError(f"{path} is not valid TOML ({exc})") from exc
    kb = data.get("kb")
    if not isinstance(kb, str) or not kb.strip():
        raise KbError(f"`kb` is not set in {path}; run /core:init-kb")
    if slug is not None:
        record_project(path, repo, slug)
        data = tomllib.loads(path.read_text())
    projects_dir = data.get("projects_dir")
    if not isinstance(projects_dir, str) or not projects_dir:
        projects_dir = "projects"
    mapped = (data.get("projects") or {}).get(str(Path(repo).expanduser().resolve()))
    return {
        "kb": str(Path(kb).expanduser()),
        "projects_dir": projects_dir,
        "slug": mapped if isinstance(mapped, str) else None,
        "repo": str(Path(repo).expanduser().resolve()),
    }


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
    pj = sub.add_parser("project")
    pj.add_argument("--repo", required=True, type=Path)
    pj.add_argument("--slug", default=None)
    pj.add_argument("--config", type=Path, default=None)
    for name in ("pointer", "close", "gate", "clear"):
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
        elif args.cmd == "project":
            print(json.dumps(project_info(args.repo, args.config, args.slug)))
        elif args.cmd == "clear":
            clear_pointer(args.repo)
            print(json.dumps({"cleared": True}))
        elif args.cmd == "gate":
            print(json.dumps({"gate": "reinstalled" if ensure_gate(args.repo) else "ok"}))
        elif args.cmd == "pointer":
            build = read_pointer(args.repo)
            print(json.dumps(_as_json(build) if build else None))
        else:
            build = read_pointer(args.repo)
            if build is None:
                print(json.dumps({"closed": False, "message": "no active build"}))
            else:
                result = close_build(build)
                if result.removed:
                    clear_pointer(args.repo)
                print(json.dumps({"closed": result.removed, "message": result.reason}))
    except (KbError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
