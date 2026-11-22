#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse security gate for `git commit` (Bash).

Acts only when a command runs `git commit` (found after folding quotes and
backslashes and looking inside `$(...)`, backticks, `;`/`&&`/`|` chains,
`bash -c`/`eval`, `cd x &&`, `git -C x`, `git -c k=v`, `/usr/bin/git`).

A repository is *gated* when `.cta/active-build` exists at its top level (a
`loop` run is active) or `.cta/security.toml` is tracked. Not gated, not a git
repository, or not a commit: exit 0, always.

In a gated repository the gate FAILS CLOSED (exit 2, reason on stderr):
- `git commit` with `-a/--all`, `-i/--include`, `-o/--only`, `-p/--patch`, any
  pathspec (also after `--`), or after a `git add`/`rm`/`mv`/... in the same
  command is refused: git changes the index after this hook runs, so a scan of
  the staged set would miss those files. Stage first, commit separately.
- no staged files, or staged files all `*.md`: allowed.
- semgrep or gitleaks missing (osv-scanner too when a staged path is a manifest
  or lockfile scan.py recognizes): blocked with an install instruction.
- `scan.fast_scan(staged=True)` findings of severity low or above: blocked,
  up to 10 listed. `info` findings are listed but never block.
- any exception while gating: blocked with `security gate error: <type>`.

Hook-input that is not JSON, or a repository git cannot open, exits 0: gating
cannot be decided.

Known gaps: git aliases defined in config (only `-c alias.x=commit...` is
seen); `GIT_*` set by an outer `export`; commits made by other programs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

HOOKS = Path(__file__).resolve().parent
SCRIPTS = HOOKS.parent / "scripts"
for _p in (str(HOOKS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shelltext  # noqa: E402

try:
    import scan  # noqa: E402
    from findings import git_env  # noqa: E402
    _IMPORT_ERROR: str | None = None
except Exception as exc:  # broken plugin install: fail closed once gated
    scan = None
    _IMPORT_ERROR = type(exc).__name__

    def git_env(**overrides):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        env.update(overrides)
        return env

MAX_LISTED = 10
BLOCKING = ("critical", "high", "medium", "low")
RANK = {s: i for i, s in enumerate(("critical", "high", "medium", "low", "info"))}

REFUSE_PATHS = (
    "security gate: `git commit` with -a/--all, -i/--include, -o/--only, -p/--patch or a path "
    "stages files after this check runs, so the staged scan would miss them. Stage with "
    "`git add <files>` first, then run `git commit` without paths."
)
REFUSE_INDEX = (
    "security gate: this command changes the index and commits in one step; the staged scan "
    "runs before it and would miss those changes. Run `git add` (or rm/mv/...) as its own "
    "command first, then `git commit` without paths."
)

WRAPPERS = {"command", "exec", "time", "nohup", "builtin", "sudo", "nice", "env", "!", "{",
            "if", "then", "elif", "else", "while", "until", "do"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                  "--config-env", "--exec-path", "--attr-source"}
INDEX_CHANGERS = {"add", "stage", "rm", "mv", "apply", "restore", "reset", "checkout", "switch",
                  "merge", "cherry-pick", "revert", "stash", "am", "rebase", "pull",
                  "update-index", "read-tree", "clean"}
# commit options that take a separate value (short letters; long names)
SHORT_VALUE = set("mFCctu") - {"u"}
LONG_VALUE = {"--message", "--file", "--author", "--date", "--reuse-message", "--reedit-message",
              "--fixup", "--squash", "--template", "--cleanup", "--trailer",
              "--pathspec-from-file"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_BAD_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")


@dataclass
class Commit:
    dir: Path
    refuse: str | None = None


def _resolve(base: Path, value: str, fallback: Path) -> Path:
    if not value or "$" in value or "`" in value or value == "-":
        return fallback
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else base / p


def _commit_flags(args: list[str]) -> bool:
    """True when the `git commit` arguments stage files themselves (flags or paths)."""
    i = 0
    while i < len(args):
        tok = args[i]
        i += 1
        if tok == "--":
            return i < len(args)
        if tok.startswith("--"):
            name = tok.split("=", 1)[0]
            if name in ("--all", "--patch", "--interactive", "--pathspec-from-file"):
                return True
            if len(name) >= 5 and "--include".startswith(name):
                return True
            if len(name) >= 4 and "--only".startswith(name):
                return True
            if name in LONG_VALUE and "=" not in tok:
                i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            for pos, letter in enumerate(tok[1:], start=1):
                if letter in "aiop":
                    return True
                if letter in SHORT_VALUE:
                    if pos == len(tok) - 1:
                        i += 1  # value is the next word
                    break
                if letter in "uS":  # optional attached value only
                    break
            continue
        return True  # a pathspec
    return False


def _git_command(words: list[str], cwd: Path, fallback: Path) -> tuple[Path, list[str], str] | None:
    """For `git <opts> <sub> <args>`: (repo dir, args, subcommand); an alias to commit reads as
    `commit`."""
    base = cwd
    i = 1
    alias_here: set[str] = set()
    while i < len(words):
        w = words[i]
        if w in GIT_VALUE_OPTS:
            val = words[i + 1] if i + 1 < len(words) else ""
            if w == "-C":
                base = _resolve(base, val, fallback)
            elif w == "--work-tree":
                base = _resolve(base, val, fallback)
            elif w == "--git-dir":
                gd = _resolve(base, val, fallback)
                base = gd.parent if gd.name == ".git" else gd
            elif w == "-c":
                m = re.match(r"alias\.([^=]+)=\s*commit\b", val)
                if m:
                    alias_here.add(m.group(1))
            i += 2
            continue
        if w.startswith("--work-tree="):
            base = _resolve(base, w.split("=", 1)[1], fallback)
        elif w.startswith("--git-dir="):
            gd = _resolve(base, w.split("=", 1)[1], fallback)
            base = gd.parent if gd.name == ".git" else gd
        elif w.startswith("-") and w != "-":
            pass
        else:
            break
        i += 1
    if i >= len(words):
        return None
    sub = words[i]
    return base, words[i + 1:], "commit" if sub in alias_here else sub


def find_commits(command: str, payload_cwd: Path) -> list[Commit]:
    commits: list[Commit] = []
    index_changed = [False]
    text = shelltext.unify_newlines(command)
    seen_text: set[str] = set()

    def analyze(text: str, start: Path, depth: int = 0) -> None:
        if text in seen_text or depth > 8:
            return
        seen_text.add(text)
        items = shelltext.lex(text)
        cwd = start
        stack: list[Path] = []
        seg: list[str] = []

        def end_segment() -> None:
            nonlocal cwd, seg
            words, seg = seg, []
            if words:
                cwd = handle(words, cwd, depth)

        k = 0
        while k < len(items):
            kind, val = items[k]
            if kind == "word":
                seg.append(val)
            elif val == "(":
                end_segment()
                stack.append(cwd)
            elif val == ")":
                end_segment()
                if stack:
                    cwd = stack.pop()
            elif "<" in val or ">" in val:
                if seg and seg[-1].isdigit():
                    seg.pop()
                if k + 1 < len(items) and items[k + 1][0] == "word":
                    k += 1  # redirection target
            else:
                end_segment()
            k += 1
        end_segment()

    def handle(words: list[str], cwd: Path, depth: int) -> Path:
        env_names: list[str] = []
        while words:
            w = words[0]
            if _ASSIGN.match(w):
                env_names.append(w.split("=", 1)[0])
                words = words[1:]
            elif w in WRAPPERS:
                words = words[1:]
                if w in ("env", "sudo", "nice"):
                    while words and (words[0].startswith("-") or _ASSIGN.match(words[0])):
                        if _ASSIGN.match(words[0]):
                            env_names.append(words[0].split("=", 1)[0])
                        words = words[1:]
            else:
                break
        if not words:
            return cwd
        prog = PurePosixPath(words[0]).name
        if prog in ("cd", "pushd"):
            target = next((w for w in words[1:] if not w.startswith("-")), "")
            return _resolve(cwd, target, payload_cwd) if target else cwd
        if prog in SHELLS or prog == "eval":
            if prog == "eval":
                analyze(" ".join(words[1:]), cwd, depth + 1)
            elif "-c" in words or any(w.startswith("-") and "c" in w[1:] and not w.startswith("--")
                                      for w in words[1:]):
                rest = [w for w in words[1:] if not w.startswith("-")]
                if rest:
                    analyze(rest[0], cwd, depth + 1)
            return cwd
        if prog != "git":
            return cwd
        got = _git_command(words, cwd, payload_cwd)
        if got is None:
            return cwd
        base, args, sub = got
        if sub == "commit":
            refuse = None
            if _commit_flags(args):
                refuse = REFUSE_PATHS
            elif index_changed[0]:
                refuse = REFUSE_INDEX
            elif any(n in _BAD_ENV for n in env_names):
                refuse = REFUSE_INDEX
            commits.append(Commit(base, refuse))
        elif sub in INDEX_CHANGERS:
            index_changed[0] = True
        return cwd

    analyze(text, payload_cwd)  # a lexing error here reaches the caller (coarse fallback)
    for body in sorted(set(shelltext.substitutions(text)), key=len):
        try:
            analyze(body, payload_cwd)
        except shelltext.LexError:
            pass
    return commits


def _coarse(command: str, payload_cwd: Path) -> list[Commit]:
    """When the lexer fails: any `git ... commit` mention counts, paths unknown."""
    flat = shelltext.normalize(command.replace("\\", ""))
    if re.search(r"\bgit\b.*\bcommit\b", flat):
        refuse = REFUSE_PATHS if re.search(r"\bcommit\b.*\s-[A-Za-z]*[aiop]|\s--(all|include|only)\b",
                                           flat) else None
        return [Commit(payload_cwd, refuse)]
    return []


# --------------------------------------------------------------------- gating

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, env=git_env())


def _toplevel(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    try:
        proc = _git(["rev-parse", "--show-toplevel"], path)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return Path(os.fsdecode(proc.stdout.rstrip(b"\n")))


def is_gated(top: Path) -> bool:
    if (top / ".cta" / "active-build").exists():
        return True
    try:
        return _git(["ls-files", "--error-unmatch", "--", ".cta/security.toml"], top).returncode == 0
    except OSError:
        return False


def _staged(top: Path) -> list[str]:
    proc = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"], top)
    if proc.returncode != 0:
        raise RuntimeError("git diff --cached failed")
    return [os.fsdecode(n) for n in proc.stdout.split(b"\0") if n]


def _one_line(f) -> str:
    msg = " ".join(str(f.message).split())[:160]
    return f"[{f.severity}] {f.path}:{f.line} {f.rule} - {msg}"


def _report(found: list) -> tuple[bool, str]:
    ordered = sorted(found, key=lambda f: RANK.get(f.severity, 0))
    blocking = [f for f in ordered if f.severity in BLOCKING]
    lines = [_one_line(f) for f in ordered[:MAX_LISTED]]
    if len(ordered) > MAX_LISTED:
        lines.append(f"... and {len(ordered) - MAX_LISTED} more")
    head = (f"security gate: {len(blocking)} finding(s) in the staged changes; fix them and "
            "re-stage before committing" if blocking else "security gate: info findings only")
    return bool(blocking), head + "\n" + "\n".join(lines)


def gate(commit: Commit, scan_fn=None, which_fn=None) -> tuple[int, str]:
    top = _toplevel(commit.dir)
    if top is None or not is_gated(top):
        return 0, ""
    try:
        if _IMPORT_ERROR:
            raise ImportError(_IMPORT_ERROR)
        if commit.refuse:
            return 2, commit.refuse
        names = _staged(top)
        if not names or all(n.lower().endswith(".md") for n in names):
            return 0, ""
        needed = ["semgrep", "gitleaks"]
        if any(scan._is_manifest(n) for n in names):
            needed.append("osv-scanner")
        which = which_fn if which_fn is not None else shutil.which
        missing = scan.missing_scanners(needed, which)
        if missing:
            return 2, (f"security gate: install {', '.join(missing)} "
                       f"(brew install {' '.join(missing)})")
        run_scan = scan_fn if scan_fn is not None else (lambda r: scan.fast_scan(r, staged=True))
        found = run_scan(top)
        if not found:
            return 0, ""
        blocked, text = _report(found)
        return (2 if blocked else 0), text
    except Exception as exc:
        tool = getattr(exc, "tool", None)
        suffix = f" ({tool})" if tool else ""
        return 2, f"security gate error: {type(exc).__name__}{suffix}"


def evaluate(payload: dict, scan_fn=None, which_fn=None) -> tuple[int, str]:
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0, ""
    tool_input = payload.get("tool_input") or {}
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    if "commit" not in shelltext.normalize(command.replace("\\", "")):
        return 0, ""  # cheap pre-filter; quotes and backslashes folded first
    cwd = Path(payload.get("cwd") or os.getcwd())
    try:
        commits = find_commits(command, cwd)
    except Exception:
        commits = _coarse(command, cwd)
    done: set[tuple[str, str | None]] = set()
    notes: list[str] = []
    for c in commits:
        key = (str(c.dir), c.refuse)
        if key in done:
            continue
        done.add(key)
        code, text = gate(c, scan_fn, which_fn)
        if code:
            return code, text
        if text:
            notes.append(text)
    return 0, "\n".join(notes)


def main(payload: dict | None = None, scan_fn=None, which_fn=None) -> int:
    if payload is None:
        try:
            payload = json.load(sys.stdin)
        except Exception:
            return 0
    code, text = evaluate(payload, scan_fn, which_fn)
    if text:
        print(text, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
