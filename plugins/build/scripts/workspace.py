#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
# Adapted from obra/superpowers skills/subagent-driven-development/scripts (MIT)
"""Per-plan workspace, task briefs and review packages for subagent-driven builds.

The workspace lives at <repo>/.cta/sdd/<plan-slug>/ so a follow-up plan can never
read or overwrite another plan's artifacts. Each workspace records its owning
plan in a `plan-path` marker (repo-relative inside the repo, absolute outside);
a slug collision with a different plan is disambiguated by the plan's parent
directory name, then a counter. A self-ignoring .gitignore sits in `.cta/sdd/`,
so a workspace never shows in `git status` (the rest of `.cta/`, such as a
tracked security.toml, stays visible). Stdlib only.

CLI (prints the written path):
  workspace.py workspace [-C DIR] PLAN_FILE
  workspace.py brief     [-C DIR] PLAN_FILE TASK [--out DIR]
  workspace.py package   [-C DIR] PLAN_FILE BASE HEAD [--out DIR]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SDD = Path(".cta") / "sdd"

_TASK_HEADING = re.compile(r"^(#+)[ \t]+Task[ \t]+(.*)$")
_TASK_ID = re.compile(r"^[A-Za-z0-9]+(\.[A-Za-z0-9]+)*")


class WorkspaceError(Exception):
    """A helper could not do its job; the message says why."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def repo_root(start: Path) -> Path:
    """Physical top-level of the git working tree containing `start`."""
    start = Path(start)
    proc = _git(start if start.is_dir() else start.parent, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise WorkspaceError(
            f"must run inside a git working tree (looked in {start}): {proc.stderr.strip()}"
        )
    return Path(proc.stdout.strip()).resolve()


def workspace_dir(repo: Path, plan_file: Path) -> Path:
    """Resolve and create the workspace for `plan_file` under `repo/.cta/sdd/`."""
    plan_file = Path(plan_file)
    if not plan_file.is_file():
        raise WorkspaceError(f"no such plan file: {plan_file}")
    root = repo_root(Path(repo))
    slug = plan_file.name.removesuffix(".md")
    if not slug or slug in (".", ".."):
        raise WorkspaceError(f"cannot derive a workspace name from: {plan_file}")
    base = root / SDD

    plan_dir = plan_file.parent.resolve()
    plan_abs = plan_dir / plan_file.name
    try:
        plan_id = plan_abs.relative_to(root).as_posix()
    except ValueError:
        plan_id = str(plan_abs)

    def owns(d: Path) -> bool:
        marker = d / "plan-path"
        if marker.exists():
            return marker.read_text().strip() == plan_id
        d.mkdir(parents=True, exist_ok=True)
        marker.write_text(plan_id + "\n")
        return True

    d = base / slug
    if not owns(d):
        parent = plan_dir.name
        d = base / f"{slug}-{parent}"
        if not owns(d):
            n = 2
            while not owns(base / f"{slug}-{parent}-{n}"):
                n += 1
            d = base / f"{slug}-{parent}-{n}"

    gitignore = base / ".gitignore"
    if not gitignore.exists():  # create-only: a repo may version its own
        gitignore.write_text("*\n")
    return d


def task_brief(plan_file: Path, task: str, out_dir: Path) -> Path:
    """Write the text of `### Task <task>:` up to the next task heading."""
    plan_file = Path(plan_file)
    if not plan_file.is_file():
        raise WorkspaceError(f"no such plan file: {plan_file}")
    lines = plan_file.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    captured: list[str] = []
    infence = False
    fence_line = 0
    hidden = False
    intask = False
    level = 0
    tasks = 0
    for number, line in enumerate(lines, 1):
        if line.startswith("```"):
            infence = not infence
            if infence:
                fence_line, hidden = number, False
        m = _TASK_HEADING.match(line)
        if m and infence and not line.startswith("```"):
            hidden = True
        if m and not infence:
            idm = _TASK_ID.match(m.group(2))
            if idm and re.search(r"\d", idm.group(0)):
                tasks += 1
                tid = idm.group(0)
                depth = len(m.group(1))
                subtask = (
                    intask
                    and depth > level
                    and tid.startswith(task)
                    and len(tid) > len(task)
                    and (tid[len(task)].isalpha() or tid[len(task)] == ".")
                )
                if not subtask:
                    intask = tid == task
                    level = depth
        if intask:
            captured.append(line)

    if infence and hidden and (intask or not captured):
        raise WorkspaceError(
            f"the code fence opened at line {fence_line} of {plan_file} never closes, "
            "so a Task heading after it cannot be seen; close that fence and rerun"
        )
    if not captured:
        hint = ""
        if not tasks:
            hint = ' (task headings must use the English word "Task", e.g. "### Task 1: ...")'
        raise WorkspaceError(f"task {task} not found in {plan_file}{hint}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"task-{task}-brief.md"
    out.write_text("\n".join(captured) + "\n")
    return out


def review_package(repo: Path, base: str, head: str, out_dir: Path) -> Path:
    """Write commit list, stat and -U10 diff for the explicit `base..head` range."""
    root = repo_root(Path(repo))
    for label, ref in (("BASE", base), ("HEAD", head)):
        if _git(root, "rev-parse", "--verify", "--quiet", ref).returncode != 0:
            raise WorkspaceError(f"bad {label}: {ref}")
    if _git(root, "merge-base", "--is-ancestor", base, head).returncode != 0:
        raise WorkspaceError(f"HEAD is not a descendant of BASE: {base}..{head}")
    rng = f"{base}..{head}"
    count = _git(root, "rev-list", "--count", rng).stdout.strip()
    if count in ("", "0"):
        raise WorkspaceError(f"empty commit range: {rng}")

    def short(ref: str) -> str:
        return _git(root, "rev-parse", "--short=7", ref).stdout.strip()

    def run(*args: str) -> str:
        proc = _git(root, *args)
        if proc.returncode != 0:
            raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    text = (
        f"# Review package: {rng}\n\n"
        f"## Commits\n{run('log', '--oneline', rng)}\n"
        f"## Files changed\n{run('diff', '--stat', rng)}\n"
        f"## Diff\n{run('diff', '-U10', rng)}"
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"review-{short(base)}..{short(head)}.diff"
    out.write_text(text)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workspace.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("workspace", "brief", "package"):
        p = sub.add_parser(name)
        p.add_argument("-C", dest="chdir", metavar="DIR")
        p.add_argument("plan")
        if name == "brief":
            p.add_argument("task")
        if name == "package":
            p.add_argument("base")
            p.add_argument("head")
        if name != "workspace":
            p.add_argument("--out", metavar="DIR")
    args = parser.parse_args(argv)
    try:
        if args.chdir:
            if not os.path.isdir(args.chdir):
                raise WorkspaceError(f"bad -C directory: {args.chdir}")
            os.chdir(args.chdir)
        plan = Path(args.plan)
        repo = repo_root(Path.cwd())
        if args.cmd == "workspace":
            result = workspace_dir(repo, plan)
        elif args.cmd == "brief":
            out = Path(args.out) if args.out else workspace_dir(repo, plan)
            result = task_brief(plan, args.task, out)
        else:
            out = Path(args.out) if args.out else workspace_dir(repo, plan)
            result = review_package(repo, args.base, args.head, out)
    except WorkspaceError as err:
        print(f"workspace.py: {err}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
