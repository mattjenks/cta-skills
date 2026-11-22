#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse security gate for `git commit` (Bash).

Acts only when a command runs `git commit` (or `merge`/`pull`/`am`, below). Any word whose
basename is `git` counts, so wrappers (`timeout`, `xargs`, `sudo -u x`, `env -u X`, `nice -n 5`,
`find -exec`, `bash -o pipefail -c`, `eval`), global options (`-C`, `-c k=v`, attached `-ckey=v`,
`--config-env`, `--git-dir`, `--work-tree`), `-c alias.x=...commit...` aliases, quotes, `;`/`&&`/`|`
chains, subshells, `$(...)`, backticks and `<(...)` are all seen. Substitution bodies are analysed
too, and an index changer anywhere in the command (`git add` inside `$(...)` included) refuses
the commit. Quoted-delimiter heredoc bodies (commit messages) are data and are skipped.

The target repository is the payload `cwd`, moved by `cd`/`pushd` and `git -C`; `~`, `$HOME`,
`$PWD` and variables assigned earlier in the command are expanded. A target that is still
dynamic (unknown variable, `$(...)`, `cd -`) makes the gate refuse the commit in any repo,
asking for a literal path.

A repository is *gated* when `.cta/active-build` exists at its top level (a
`loop` run is active) or `.cta/security.toml` is tracked. Not gated, not a git
repository, or not a commit: exit 0, always.

In a gated repository the gate FAILS CLOSED (exit 2, reason on stderr):
- `git commit` with `-a/--all`, `-i/--include`, `-o/--only`, `-p/--patch`, any
  pathspec (also after `--`), or after a `git add`/`rm`/`mv`/... in the same
  command is refused: git changes the index after this hook runs, so a scan of
  the staged set would miss those files. Stage first, commit separately.
- `git merge`, `git pull` and `git am` create commits without a scan: refused unless the
  arguments carry `--no-commit`, `--squash`, `--ff-only`, `--abort` or `--quit`. Known and
  accepted: `cherry-pick`, `revert`, `rebase` and `commit-tree` + `update-ref` recommit existing
  history; the branch-level `full_scan` covers them.
- no staged files, or staged files all `*.md`: allowed.
- semgrep or gitleaks missing (osv-scanner too when a staged path is a manifest
  or lockfile scan.py recognizes): blocked with an install instruction.
- `scan.fast_scan(staged=True)` findings of severity low or above: blocked,
  up to 10 listed. `info` findings are listed but never block.
- scanners run under an internal deadline (GATE_DEADLINE, below the hook timeout): a timeout
  blocks with `security gate error: TimeoutExpired (<tool>)`.
- any exception while gating (or while handling a payload that mentions git): blocked with
  `security gate error: <type>`.

Hook-input that is not JSON, or a repository git cannot open, exits 0: gating
cannot be decided.

A project pre-commit hook that re-stages files runs after this scan and is not covered.

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
GATE_DEADLINE = 100  # seconds for the scanners together; hooks.json allows 120
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
REFUSE_MERGE = (
    "security gate: `git merge`, `git pull` and `git am` create commits without a staged scan. "
    "Use `--no-commit` (merge) or `--no-rebase --no-commit` (pull), review and stage the result, "
    "then run `git commit`."
)
REFUSE_COMPLEX = (
    "security gate: this command is too complex to check (unbalanced quoting, or a git "
    "subcommand built at runtime). Simplify it: quote heredoc delimiters ('EOF'), and write the "
    "subcommand literally."
)
REFUSE_TARGET = (
    "security gate: cannot tell which repository this `git commit` targets (a `cd`/`-C` path "
    "built from a variable or command). Use a literal path, or run the command from the "
    "repository directory."
)

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                  "--config-env", "--attr-source"}
INDEX_CHANGERS = {"add", "stage", "rm", "mv", "apply", "restore", "reset", "checkout", "switch",
                  "merge", "cherry-pick", "revert", "stash", "am", "rebase", "pull",
                  "update-index", "read-tree", "clean"}
MERGERS = {"merge", "pull", "am"}
MERGE_SAFE = {"--no-commit", "--squash", "--ff-only", "--abort", "--quit"}
# commit options that take a separate value (short letters; long names)
SHORT_VALUE = set("mFCct")
LONG_VALUE = {"--message", "--file", "--author", "--date", "--reuse-message", "--reedit-message",
              "--fixup", "--squash", "--template", "--cleanup", "--trailer",
              "--pathspec-from-file"}
STAGING_LONG = ("--all", "--patch", "--interactive", "--pathspec-from-file", "--include", "--only")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_BAD_ENV = ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE")
_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


@dataclass
class Commit:
    dir: Path
    refuse: str | None = None
    kind: str = "commit"
    unresolved: bool = False


def _expand(value: str, variables: dict, cwd: Path | None) -> str | None:
    """`~`, `$HOME`, `$PWD` and variables assigned earlier in the command; None if anything
    dynamic (`$(...)`, backticks, unknown variables) is left."""
    if value == "~" or value.startswith("~/"):
        value = os.environ.get("HOME", "~") + value[1:]
    if "`" in value or "$(" in value:
        return None

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in variables:
            return variables[name]
        if name == "PWD" and cwd is not None:
            return str(cwd)
        return os.environ.get(name, m.group(0)) if name == "HOME" else m.group(0)

    for _ in range(4):
        new = _VAR.sub(sub, value)
        if new == value:
            break
        value = new
    return None if "$" in value else value


def _resolve(base: Path | None, value: str, variables: dict) -> Path | None:
    """`base` joined with `value`; None when either is unknown."""
    if base is None:
        return None
    value = _expand(value, variables, base)
    if value is None or value == "-":
        return None
    p = Path(value)
    return p if p.is_absolute() else base / p


def _long_prefix(name: str, full: str, minimum: int = 4) -> bool:
    return len(name) >= minimum and full.startswith(name)


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
            if name == "--all" or any(_long_prefix(name, f) for f in STAGING_LONG[1:]):
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


def _git_command(words: list[str], cwd: Path | None, variables: dict):
    """For `git <opts> <sub> <args>`: (repo dir or None, args, subcommand or None)."""
    base = cwd
    i = 1
    aliases: set[str] = set()
    while i < len(words):
        w = words[i]
        name, eq, attached = w.partition("=")
        if w.startswith("-c") and len(w) > 2 and not w.startswith("--"):
            opt, val, step = "-c", w[2:], 1
        elif w in GIT_VALUE_OPTS:
            opt, val, step = w, words[i + 1] if i + 1 < len(words) else "", 2
        elif eq and name in GIT_VALUE_OPTS:
            opt, val, step = name, attached, 1
        elif w.startswith("-") and w != "-":
            i += 1
            continue
        else:
            break
        if opt == "-C" or opt == "--work-tree":
            base = _resolve(base, val, variables)
        elif opt == "--git-dir":
            gd = _resolve(base, val, variables)
            base = (gd.parent if gd.name == ".git" else gd) if gd else None
        elif opt in ("-c", "--config-env"):
            m = re.match(r"alias\.([^=]+)=(.*)", val, re.S)
            if m and (opt == "--config-env" or "commit" in m.group(2)):
                aliases.add(m.group(1))
        i += step
    if i >= len(words):
        return None
    sub = words[i]
    return base, words[i + 1:], "commit" if sub in aliases else sub


def find_commits(command: str, payload_cwd: Path) -> list[Commit]:
    """Every `git commit`-like invocation in the command. A lexing error propagates."""
    commits: list[Commit] = []
    state = {"index": False}
    variables: dict[str, str] = {}
    text = shelltext.unify_newlines(command)
    seen_text: set[str] = set()

    def analyze(src: str, start: Path | None, depth: int = 0) -> None:
        if src in seen_text or depth > 8:
            return
        seen_text.add(src)
        items = shelltext.lex(src)
        cwd = start
        stack: list[Path | None] = []
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
            elif val == "<<heredoc":
                pass
            elif "<" in val or ">" in val:
                if seg and seg[-1].isdigit():
                    seg.pop()
                if k + 1 < len(items) and items[k + 1][0] == "word":
                    k += 1  # redirection target
            else:
                end_segment()
            k += 1
        end_segment()

    def handle(words: list[str], cwd: Path | None, depth: int) -> Path | None:
        if all(_ASSIGN.match(w) for w in words):
            for w in words:
                name, _, value = w.partition("=")
                expanded = _expand(value, variables, cwd)
                if expanded is not None:
                    variables[name] = expanded
            return cwd
        words = [_expand(w, variables, cwd) or w if _VAR.search(w) else w for w in words]
        first = next((w for w in words if not _ASSIGN.match(w)), "")
        prog = PurePosixPath(first).name
        if prog in ("cd", "pushd"):
            args = [w for w in words[words.index(first) + 1:] if w == "-" or not w.startswith("-")]
            return _resolve(cwd, args[0] if args else "~", variables)
        if first == "eval":
            analyze(" ".join(words[words.index(first) + 1:]), cwd, depth + 1)
        for k, w in enumerate(words):
            base_name = PurePosixPath(w).name
            if base_name in SHELLS:
                rest = words[k + 1:]
                for j, a in enumerate(rest[:-1]):
                    if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
                        analyze(rest[j + 1], cwd, depth + 1)
                        break
            elif base_name == "git":
                env_names = [x.split("=", 1)[0] for x in words[:k] if _ASSIGN.match(x)]
                git_at(words[k:], cwd, env_names)
        return cwd

    def git_at(words: list[str], cwd: Path | None, env_names: list[str]) -> None:
        got = _git_command(words, cwd, variables)
        if got is None:
            return
        base, args, sub = got
        if _VAR.search(sub) or "$(" in sub or "`" in sub:
            commits.append(Commit(payload_cwd, REFUSE_COMPLEX, "complex"))
            return
        if sub == "commit":
            refuse = REFUSE_PATHS if _commit_flags(args) else None
            if refuse is None and any(n in _BAD_ENV for n in env_names):
                refuse = REFUSE_INDEX
            commits.append(Commit(base or payload_cwd, refuse, "commit", base is None))
            return
        if sub in INDEX_CHANGERS:
            state["index"] = True
        if sub in MERGERS and not (MERGE_SAFE & set(args)):
            commits.append(Commit(base or payload_cwd, REFUSE_MERGE, "merge", base is None))

    analyze(text, payload_cwd)  # a lexing error here reaches the caller
    for body in sorted(set(shelltext.substitutions(text)), key=len):
        try:
            analyze(body, payload_cwd)
        except shelltext.LexError:
            commits.append(Commit(payload_cwd, REFUSE_COMPLEX, "complex"))
    if state["index"]:
        for c in commits:
            if c.kind == "commit" and c.refuse is None:
                c.refuse = REFUSE_INDEX
    return commits


def _coarse(command: str, payload_cwd: Path) -> list[Commit]:
    """When the lexer fails: any `git ... commit` mention counts and a gated repo refuses."""
    flat = shelltext.normalize(command.replace("\\", ""))
    if re.search(r"\bgit\b.*\b(commit|merge|pull|am)\b", flat):
        return [Commit(payload_cwd, REFUSE_COMPLEX, "complex")]
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
        run_scan = scan_fn if scan_fn is not None else (
            lambda r: scan.fast_scan(r, staged=True, timeout=GATE_DEADLINE))
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
    if "git" not in shelltext.normalize(command.replace("\\", "")):
        return 0, ""  # cheap pre-filter; quotes and backslashes folded first
    cwd = Path(payload.get("cwd") or os.getcwd())
    try:
        commits = find_commits(command, cwd)
    except Exception:
        commits = _coarse(command, cwd)
    done: set[tuple[str, str | None]] = set()
    notes: list[str] = []
    for c in commits:
        if c.unresolved:
            return 2, REFUSE_TARGET
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
    try:
        code, text = evaluate(payload, scan_fn, which_fn)
    except Exception as exc:  # fail closed whenever the command mentions a commit
        try:
            command = str((payload.get("tool_input") or {}).get("command") or "")
            mentions = payload.get("tool_name") == "Bash" and "git" in command
        except Exception:
            mentions = False
        if not mentions:
            return 0
        code, text = 2, f"security gate error: {type(exc).__name__}"
    if text:
        print(text, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
