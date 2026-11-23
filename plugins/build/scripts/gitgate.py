"""The commit gate as real git hooks. Stdlib only.

The hooks in `plugins/build/hooks/git/` (`pre-commit`, `pre-merge-commit`, `pre-applypatch`) call
`hook_main`. git runs them on the exact index it is about to commit, so every way of making a
commit that runs hooks is covered: `commit -a`, `commit <paths>`, `git add` inside a `$(...)`
of the message, aliases, wrappers, scripts, merges that create a merge commit, and `git am`.
Commands that skip hooks (`--no-verify`, a `core.hooksPath` override, `GIT_CONFIG*`) are the job
of the PreToolUse guard `hooks/gate_guard.py`. History recommitters that run no pre-commit hook
(`cherry-pick`, `revert`, `rebase`, `commit-tree` + `update-ref`) only recommit content that
already passed a gate, and the branch-level `full_scan` (secure step, `pr` check) is the backstop.

Threat model: the assistant's mistakes and casual bypasses, not a determined attacker.

Install: `install_gate(repo)` points the repo-local `core.hooksPath` at the hook directory of
this plugin (resolved at install time from this file's location). It writes the gate record
`<git common dir>/cta/gate.json`: the plugin hook directory, the previous LOCAL value (`previous`,
restored exactly on uninstall, empty string included) and the previous EFFECTIVE value (`chain`,
read with the user's normal git config, so a global `core.hooksPath` is chained too). The record
lives in the git common dir, out of reach of `rm -rf .cta` and `git clean -fdx`, and is shared by
every linked worktree, which also shares `core.hooksPath`. The record is also the gate marker:
while it exists the repository is gated. `kbwork.write_pointer` installs the gate for a `loop`
run and `kbwork.clear_pointer` removes it, unless the repo opted in permanently with a tracked
`.cta/security.toml`.

A hook run (`check`):
- The repository is the one git runs the hook in; the index is git's GIT_INDEX_FILE (made
  absolute), else the repository's index.
- Not gated (no gate record, no `.cta/active-build`, no tracked `.cta/security.toml`): pass.
- Nothing staged against HEAD, or only `*.md` files: pass.
- semgrep or gitleaks missing (osv-scanner too when a staged path is a manifest): block with
  an install instruction.
- `scan.fast_scan` over that index, bounded by GATE_DEADLINE. Only findings on lines the commit
  adds or edits (`changed_lines`) are judged; file-level findings (line 0) and paths the diff does
  not map (binary, pure rename, quoted name) are judged whole. Findings on unchanged lines are
  counted in a note and left to the branch-level `full_scan`. Any judged finding of severity low or
  above blocks; up to MAX_LISTED one-line findings (rule, path, line, scanner message; never the
  matched text) plus info items go to stderr.
- Any exception (deadline exceeded included): block with `cta commit gate error: <type>`.
Blocking is exit 1, the git-hook convention. After a pass, the hook chains to the previous
effective `core.hooksPath` (relative to the work tree), else `<git common dir>/hooks`, when `<name>`
exists there and is executable, passing arguments and stdin, and returns its exit code. Chaining
also happens when the repo is not gated.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from findings import git_env

HOOK_NAMES = ("pre-commit", "pre-merge-commit", "pre-applypatch")
STATE = Path("cta") / "gate.json"  # under the git common dir
POINTER = Path(".cta") / "active-build"
OPT_IN = ".cta/security.toml"
GATE_DEADLINE = 100  # seconds for the scanners together
MAX_LISTED = 10
BLOCKING = ("critical", "high", "medium", "low")
RANK = {s: i for i, s in enumerate(("critical", "high", "medium", "low", "info"))}


class GateError(Exception):
    """git could not answer a question the gate needs."""


def hooks_dir() -> Path:
    """This plugin's git-hook directory (`plugins/build/hooks/git`), resolved."""
    return (Path(__file__).resolve().parent.parent / "hooks" / "git").resolve()


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, env=git_env() if env is None else env)


def _toplevel(repo: Path) -> Path:
    proc = _git(Path(repo), "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise GateError(f"not a git work tree: {repo}")
    return Path(proc.stdout.rstrip("\n"))


def _hooks_path(top: Path) -> str | None:
    """The repo-local value; None when unset (an empty value stays "")."""
    proc = _git(top, "config", "--local", "--get", "core.hooksPath")
    if proc.returncode != 0:
        return None
    return proc.stdout.rstrip("\n")


def _effective_hooks_path(top: Path) -> str | None:
    """core.hooksPath as git itself would see it, global and system config included: this one
    read deliberately does not use git_env()."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    proc = _git(top, "config", "--get", "core.hooksPath", env=env)
    return (proc.stdout.rstrip("\n") or None) if proc.returncode == 0 else None


def common_dir(top: Path) -> Path:
    proc = _git(Path(top), "rev-parse", "--git-common-dir")
    if proc.returncode != 0:
        raise GateError("git rev-parse --git-common-dir failed")
    common = Path(proc.stdout.rstrip("\n"))
    return common if common.is_absolute() else Path(top) / common


def _set_hooks_path(top: Path, value: str | None) -> None:
    if value is None:
        proc = _git(top, "config", "--local", "--unset-all", "core.hooksPath")
        ok = proc.returncode in (0, 5)  # 5: the key was not set
    else:
        ok = _git(top, "config", "--local", "core.hooksPath", value).returncode == 0
    if not ok:
        raise GateError("git config core.hooksPath failed")


def state_path(top: Path) -> Path:
    return common_dir(top) / STATE


def read_state(top: Path) -> dict | None:
    try:
        data = json.loads(state_path(top).read_text())
    except (OSError, ValueError, GateError):
        return None
    return data if isinstance(data, dict) else None


def _same(a: str | None, b: str | Path | None) -> bool:
    if not a or not b:
        return False
    return os.path.realpath(os.path.expanduser(a)) == os.path.realpath(str(b))


# ------------------------------------------------------------------ install

def install_gate(repo: Path) -> None:
    """Point core.hooksPath at this plugin's git hooks, remembering the previous value.
    Idempotent; a gate left pointing at an older plugin location is moved here."""
    top = _toplevel(repo)
    target = str(hooks_dir())
    current = _hooks_path(top)
    state = read_state(top) or {}
    ours = _same(current, target) or (current is not None and current == state.get("hooks_path"))
    if ours:
        previous, chain = state.get("previous"), state.get("chain")
    else:
        previous = current
        chain = _effective_hooks_path(top)
        if _same(chain, target):
            chain = None
    record = {"hooks_path": target, "previous": previous, "chain": chain,
              "build": (top / POINTER).exists(), "opted_in": opted_in(top)}
    path = state_path(top)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    if current != target:
        _set_hooks_path(top, target)


def uninstall_gate(repo: Path) -> None:
    """Restore the previous local core.hooksPath exactly (or unset it) and drop the gate record.
    A hooksPath someone else has set since install is left alone."""
    top = _toplevel(repo)
    state = read_state(top) or {}
    current = _hooks_path(top)
    if _same(current, hooks_dir()) or (current is not None and current == state.get("hooks_path")):
        previous = state.get("previous")
        _set_hooks_path(top, previous if isinstance(previous, str) else None)
    state_path(top).unlink(missing_ok=True)


def gate_installed(repo: Path) -> bool:
    """core.hooksPath is this plugin's hook directory and every hook there is executable."""
    try:
        top = _toplevel(repo)
    except GateError:
        return False
    if not _same(_hooks_path(top), hooks_dir()):
        return False
    return all(os.access(hooks_dir() / n, os.X_OK) for n in HOOK_NAMES)


def opted_in(repo: Path) -> bool:
    """`.cta/security.toml` is tracked: the repo keeps the gate permanently."""
    return _git(Path(repo), "ls-files", "--error-unmatch", "--", OPT_IN).returncode == 0


def is_gated(top: Path) -> bool:
    """A gate record in the git common dir, `.cta/active-build`, or a tracked security.toml."""
    if (Path(top) / POINTER).exists() or state_path(top).exists():
        return True
    return opted_in(top)


# ------------------------------------------------------------------- check

def _staged(top: Path, index_file: str | None) -> list[str]:
    env = git_env(GIT_INDEX_FILE=index_file) if index_file else None
    proc = _git(top, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT", env=env)
    if proc.returncode != 0:
        raise GateError("git diff --cached failed")
    return [n for n in proc.stdout.split("\0") if n]


_HUNK = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines(top: Path, index_file: str | None) -> dict[str, set[int]]:
    """Post-image line numbers the commit adds or edits, by path (`git diff --cached -U0`).

    A path is in the result only when the diff names it with a `+++ b/<path>` header, so a
    binary file, a pure rename, a mode-only change or a quoted (unusual) path is absent and its
    findings are judged whole. A path with only deletions maps to an empty set."""
    env = git_env(GIT_INDEX_FILE=index_file) if index_file else git_env()
    proc = subprocess.run(
        ["git", "-C", str(top), "-c", "core.quotePath=true", "diff", "--cached", "-U0",
         "--no-color", "--no-ext-diff", "--no-textconv", "--diff-filter=ACMRT",
         "--src-prefix=a/", "--dst-prefix=b/"],
        capture_output=True, stdin=subprocess.DEVNULL, env=env)
    if proc.returncode != 0:
        raise GateError("git diff --cached -U0 failed")
    changed: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in proc.stdout.split(b"\n"):
        if line.startswith(b"diff --git "):
            current = None
        elif line.startswith(b"+++ "):
            name = line[4:]
            current = None
            if name.startswith(b"b/"):
                current = changed.setdefault(os.fsdecode(name[2:]), set())
        elif current is not None:
            m = _HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or b"1")
                current.update(range(start, start + count))
    return changed


def _in_change(f, changed: dict[str, set[int]]) -> bool:
    """File-level findings (line 0) and unmapped paths always count; others only on a changed line."""
    lines = changed.get(f.path)
    return f.line <= 0 or lines is None or f.line in lines


def _one_line(f) -> str:
    msg = " ".join(str(f.message).split())[:160]
    return f"[{f.severity}] {f.path}:{f.line} {f.rule} - {msg}"


def _report(found: list) -> tuple[bool, str]:
    ordered = sorted(found, key=lambda f: RANK.get(f.severity, 0))
    blocking = [f for f in ordered if f.severity in BLOCKING]
    lines = [_one_line(f) for f in ordered[:MAX_LISTED]]
    if len(ordered) > MAX_LISTED:
        lines.append(f"... and {len(ordered) - MAX_LISTED} more")
    head = (f"cta commit gate: {len(blocking)} finding(s) in the commit; fix them and re-stage"
            if blocking else "cta commit gate: info findings only")
    return bool(blocking), head + "\n" + "\n".join(lines)


def check(top: Path, index_file: str | None, scan_fn=None, which_fn=None) -> tuple[int, str]:
    """(exit code, stderr text) for the commit git is about to make from `index_file`."""
    try:
        import scan

        top = Path(top)
        if not is_gated(top):
            return 0, ""
        names = _staged(top, index_file)
        if not names or all(n.lower().endswith(".md") for n in names):
            return 0, ""
        needed = ["semgrep", "gitleaks"]
        if any(scan._is_manifest(n) for n in names):
            needed.append("osv-scanner")
        missing = scan.missing_scanners(needed, which_fn or shutil.which)
        if missing:
            return 1, (f"cta commit gate: install {', '.join(missing)} "
                       f"(brew install {' '.join(missing)})")
        if scan_fn is None:
            found = scan.fast_scan(top, staged=True, timeout=GATE_DEADLINE, index_file=index_file)
        else:
            found = scan_fn(top, index_file)
        if not found:
            return 0, ""
        changed = changed_lines(top, index_file)
        kept = [f for f in found if _in_change(f, changed)]
        note = ""
        if len(kept) < len(found):
            note = (f"cta commit gate: {len(found) - len(kept)} finding(s) on unchanged lines "
                    "not judged here; the branch scan (/build:secure) still reports them")
        if not kept:
            return 0, note
        blocked, text = _report(kept)
        return (1 if blocked else 0), text + (f"\n{note}" if note else "")
    except Exception as exc:
        tool = getattr(exc, "tool", None)
        return 1, f"cta commit gate error: {type(exc).__name__}{f' ({tool})' if tool else ''}"


# -------------------------------------------------------------------- hook

def _previous_hook(top: Path, name: str) -> Path | None:
    state = read_state(top) or {}
    previous = state.get("chain")
    if isinstance(previous, str) and previous:
        directory = Path(os.path.expanduser(previous))
        if not directory.is_absolute():
            directory = top / directory
    else:
        # the hook's own environment: git may have set GIT_DIR for a separate git dir
        proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True,
                              text=True, cwd=str(top), stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise GateError("git rev-parse --git-common-dir failed")
        common = Path(proc.stdout.rstrip("\n"))
        directory = (common if common.is_absolute() else top / common) / "hooks"
    if _same(str(directory), hooks_dir()):
        return None  # never chain to ourselves
    hook = directory / name
    return hook if hook.is_file() and os.access(hook, os.X_OK) else None


def hook_main(name: str, args: list[str]) -> int:
    """Entry point of the git hooks: CTA's check, then the hook the repo would have run."""
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise GateError("no work tree")
        top = Path(proc.stdout.rstrip("\n"))
        index = os.environ.get("GIT_INDEX_FILE")
        index = os.path.abspath(index) if index else None
        code, text = check(top, index)
        if text:
            print(text, file=sys.stderr)
        if code:
            return code
        hook = _previous_hook(top, name)
    except Exception as exc:
        print(f"cta commit gate error: {type(exc).__name__}", file=sys.stderr)
        return 1
    if hook is None:
        return 0
    try:
        return subprocess.run([str(hook), *args]).returncode
    except OSError as exc:
        print(f"cta commit gate: could not run {hook.name}: {type(exc).__name__}", file=sys.stderr)
        return 1
