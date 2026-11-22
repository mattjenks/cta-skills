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
this plugin (resolved at install time from this file's location) and records the previous value
in `.cta/gate.json` (git-excluded), so the hooks can chain to the hook the repo would otherwise
have run. `kbwork.write_pointer` installs it for a `loop` run and `kbwork.clear_pointer` removes
it, unless the repo opted in permanently with a tracked `.cta/security.toml`.

A hook run (`check`):
- The repository is the one git runs the hook in; the index is git's GIT_INDEX_FILE (made
  absolute), else the repository's index.
- Not gated (no `.cta/active-build`, no tracked `.cta/security.toml`): pass.
- Nothing staged against HEAD, or only `*.md` files: pass.
- semgrep or gitleaks missing (osv-scanner too when a staged path is a manifest): block with
  an install instruction.
- `scan.fast_scan` over that index, bounded by GATE_DEADLINE: any finding of severity low or
  above blocks; up to MAX_LISTED one-line findings (rule, path, line, scanner message; never the
  matched text) plus info items go to stderr.
- Any exception (deadline exceeded included): block with `cta commit gate error: <type>`.
Blocking is exit 1, the git-hook convention. After a pass, the hook chains to the previous
`core.hooksPath` (relative to the work tree), else `<git common dir>/hooks`, when `<name>`
exists there and is executable, passing arguments and stdin, and returns its exit code. Chaining
also happens when the repo is not gated.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from findings import git_env

HOOK_NAMES = ("pre-commit", "pre-merge-commit", "pre-applypatch")
STATE = Path(".cta") / "gate.json"
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
    proc = _git(top, "config", "--local", "--get", "core.hooksPath")
    if proc.returncode != 0:
        return None
    return proc.stdout.rstrip("\n") or None


def _set_hooks_path(top: Path, value: str | None) -> None:
    if value is None:
        proc = _git(top, "config", "--local", "--unset-all", "core.hooksPath")
        ok = proc.returncode in (0, 5)  # 5: the key was not set
    else:
        ok = _git(top, "config", "--local", "core.hooksPath", value).returncode == 0
    if not ok:
        raise GateError("git config core.hooksPath failed")


def read_state(top: Path) -> dict | None:
    try:
        data = json.loads((Path(top) / STATE).read_text())
    except (OSError, ValueError):
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
    import kbwork

    top = _toplevel(repo)
    target = str(hooks_dir())
    current = _hooks_path(top)
    state = read_state(top) or {}
    ours = _same(current, target) or (current is not None and current == state.get("hooks_path"))
    previous = state.get("previous") if ours else current
    (top / STATE).parent.mkdir(parents=True, exist_ok=True)
    (top / STATE).write_text(json.dumps({"hooks_path": target, "previous": previous}, indent=2) + "\n")
    kbwork.exclude_path(top, STATE.as_posix())
    if current != target:
        _set_hooks_path(top, target)


def uninstall_gate(repo: Path) -> None:
    """Restore the previous core.hooksPath (or unset it) and drop `.cta/gate.json`. A hooksPath
    someone else has set since install is left alone."""
    top = _toplevel(repo)
    state = read_state(top) or {}
    current = _hooks_path(top)
    if _same(current, hooks_dir()) or (current is not None and current == state.get("hooks_path")):
        previous = state.get("previous")
        _set_hooks_path(top, previous if isinstance(previous, str) and previous else None)
    (top / STATE).unlink(missing_ok=True)


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
    return (Path(top) / POINTER).exists() or opted_in(top)


# ------------------------------------------------------------------- check

def _staged(top: Path, index_file: str | None) -> list[str]:
    env = git_env(GIT_INDEX_FILE=index_file) if index_file else None
    proc = _git(top, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT", env=env)
    if proc.returncode != 0:
        raise GateError("git diff --cached failed")
    return [n for n in proc.stdout.split("\0") if n]


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
        blocked, text = _report(found)
        return (1 if blocked else 0), text
    except Exception as exc:
        tool = getattr(exc, "tool", None)
        return 1, f"cta commit gate error: {type(exc).__name__}{f' ({tool})' if tool else ''}"


# -------------------------------------------------------------------- hook

def _previous_hook(top: Path, name: str) -> Path | None:
    state = read_state(top) or {}
    previous = state.get("previous")
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
