#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""The security findings record (`security.json`), the diff hash and status rules.

Stdlib only. The builder writes only ASSISTANT_STATUSES. The independent reviewer in
build:review closes a proposal as `false-positive` (REVIEWER_STATUSES), with `closed_by`
`review` and a reason. `accepted-risk` was the owner's and survives only in old records.
No hook enforces any of this; `secure.py verify` checks that a closure has a reason and a closer.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ASSISTANT_STATUSES = {"open", "fixed", "proposed-false-positive"}
CLOSED = {"false-positive", "accepted-risk"}
REVIEWER_STATUSES = {"false-positive"}
SEVERITIES = ("critical", "high", "medium", "low", "info")

ENTRY_KEYS = (
    "id", "tool", "rule", "severity", "path", "line", "message",
    "status", "test", "fix_commit", "reason", "closed_by",
)


def finding_id(tool: str, rule: str, path: str, line: int) -> str:
    """Stable id: first 16 hex chars of sha256 over `tool|rule|path|line`."""
    raw = f"{tool}|{rule}|{path}|{line}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class Finding:
    id: str
    tool: str
    rule: str
    severity: str
    path: str
    line: int
    message: str

    @classmethod
    def create(cls, tool, rule, path, line, severity, message) -> "Finding":
        line = int(line or 0)
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {severity!r}")
        return cls(finding_id(tool, rule, path, line), tool, rule, severity, path, line, message)

    def to_dict(self) -> dict:
        return asdict(self)


Record = dict  # {"base","head","diff_hash","findings":[{ENTRY_KEYS}]}


def new_record(base: str, head: str, dhash: str, found: list[Finding]) -> Record:
    entries = [
        {**f.to_dict(), "status": "open", "test": None, "fix_commit": None,
         "reason": None, "closed_by": None}
        for f in found
    ]
    return {"base": base, "head": head, "diff_hash": dhash, "findings": entries}


def open_findings(record: Record) -> list[dict]:
    """Findings still `open` (not fixed, not proposed or closed)."""
    return [f for f in record["findings"] if f.get("status") == "open"]


def unresolved(record: Record) -> list[dict]:
    """Findings that still need the reviewer or a fix: open plus proposed-false-positive."""
    return [f for f in record["findings"] if f.get("status") in ("open", "proposed-false-positive")]


# Repository-locating variables a git hook (or a caller) may have exported; inherited,
# they would point every git call at another repository, worktree or index.
_GIT_LOCAL_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_IMPLICIT_WORK_TREE", "GIT_PREFIX",
    "GIT_NAMESPACE", "GIT_GRAFT_FILE", "GIT_SHALLOW_FILE", "GIT_REPLACE_REF_BASE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_INTERNAL_SUPER_PREFIX",
    # injected or redirected configuration (could change diff output, hooks, drivers)
    "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
)
_GIT_CONFIG_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def git_env(**overrides: str) -> dict:
    """The environment for git (and tools that run git): os.environ without the
    repository-locating and config-injecting GIT_* variables, with system and global
    config switched off (only the repository's own config applies), plus `overrides`
    (e.g. a temp GIT_INDEX_FILE)."""
    env = {k: v for k, v in os.environ.items()
           if k not in _GIT_LOCAL_ENV and not k.startswith(_GIT_CONFIG_PREFIXES)}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env.update(overrides)
    return env


def check_ref(ref: str) -> str:
    """Refuse refs that git would parse as options (or that contain whitespace)."""
    if not ref or ref.startswith("-") or any(c.isspace() for c in ref):
        raise ValueError(f"invalid git ref: {ref!r}")
    return ref


def toplevel(repo: Path, run=subprocess.run) -> Path:
    """The git top-level of `repo` (a subdirectory is resolved up, never scanned alone)."""
    proc = run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True,
               env=git_env())
    if proc.returncode != 0:
        err = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode(errors="replace")
        raise RuntimeError(f"not a git repository: {err.strip()[-300:]}")
    out = proc.stdout if isinstance(proc.stdout, bytes) else proc.stdout.encode()
    return Path(os.fsdecode(out.rstrip(b"\n")))


def diff_hash(repo: Path, base: str, head: str = "HEAD") -> str:
    """SHA-256 of `git diff --binary --full-index base..head`.

    Only committed history is hashed (never the working tree). Blob ids make
    binary files stable. Renames, ordering, algorithm, context and the indent
    heuristic are pinned on the command line so user git config cannot change
    the hash. Stdout is streamed (large diffs stay cheap); stderr goes to a temp
    file so a chatty git cannot deadlock the pipe.
    """
    check_ref(base)
    check_ref(head)
    repo = toplevel(repo)
    cmd = [
        "git", "-C", str(repo), "-c", "core.quotepath=off",
        "-c", "diff.algorithm=myers", "-c", "diff.suppressBlankEmpty=false",
        "diff", "--no-relative", "-O/dev/null", "--binary", "--full-index", "--no-renames",
        "--no-color", "--no-ext-diff", "--no-textconv", "--no-indent-heuristic",
        "--unified=3", "--inter-hunk-context=0", "--src-prefix=a/", "--dst-prefix=b/",
        f"{base}..{head}",
    ]
    digest = hashlib.sha256()
    with tempfile.TemporaryFile() as err:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, env=git_env()) as proc:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
                digest.update(chunk)
            rc = proc.wait()
        if rc != 0:
            err.seek(0)
            tail = err.read().decode(errors="replace").strip()[-500:]
            raise RuntimeError(f"git diff {base}..{head} failed: {tail}")
    return digest.hexdigest()


def load(path: Path) -> Record:
    """Read a record. A missing file raises FileNotFoundError; callers decide."""
    return json.loads(Path(path).read_text())


def save(path: Path, record: Record) -> None:
    """Atomic write: temp file in the same directory, fsync, os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
