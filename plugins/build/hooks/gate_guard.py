#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse guard (Bash, Write, Edit, MultiEdit) that protects the commit gate.

The commit gate itself is a set of real git hooks (`hooks/git/`, installed through the
repo-local `core.hooksPath`; see scripts/gitgate.py). git runs them on the exact index it
commits, so this guard does not look for commits. It only refuses the casual ways of skipping
or disabling those hooks. Threat model: the assistant's mistakes and casual bypasses, not a
determined attacker; the branch-level secure step and the `pr` check are the backstop.

Bash, in a gated repository (`.cta/active-build` exists or `.cta/security.toml` is tracked),
decided for the payload `cwd` and for every literal `cd`/`pushd`/`-C` path in the command.
After folding quotes and backslashes (and also looking inside `$(...)` and backticks), the
command is refused when its text contains:
- `--no-verify`, or a prefix of it git accepts (`--no-veri`);
- `hooksPath` (any case);
- `GIT_CONFIG` (any `GIT_CONFIG*` variable);
- `-c core.`, `-c include.`/`-c includeIf.` (an include can set core.hooksPath), or `--config-env`;
- `.git/hooks`;
- `.cta/gate.json`, `hooks/git` or `.git/config` together with a write (`>`, rm, mv, cp, tee,
  chmod, chown, ln, unlink, truncate, install, rsync, dd, shred, `sed`/`perl` in place);
- `git ... commit` followed by a short-option cluster holding `n` (`-n`, `-nm`, `-anm`), read up
  to the first letter that takes a value (`m F C c t u S`), so `-mnote` and `-uno` pass;
- while a build is active (`.cta/active-build` exists): rm, mv or unlink together with
  `active-build`.
False positives are accepted and expected: the text is matched wherever it appears, so a
commit message or an echo that contains `--no-verify` or ` -n` after `git commit`, a
`git push --no-verify`, `cat .git/config 2>/dev/null`, or `ls .git/hooks` are refused too.

Write / Edit / MultiEdit: refused for `.cta/gate.json` and any file under this plugin's git-hook
directory (symlinks resolved), in any repository; for `.git/config` and files under `.git/hooks`
of a gated repository.

Not covered (documented, accepted): commands built at runtime (variables, `eval` of computed
text, `cd` to a computed path), scripts and programs that run git or edit the git config
themselves, git aliases from config files, and edits of the user's global git config by a
program. The git hooks still run in all of these unless the hooks themselves are skipped.

Exit 2 with the reason on stderr refuses. Malformed input exits 0. An error while deciding
whether a repository is gated, after a refusal rule matched, refuses (fail closed).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
SCRIPTS = HOOKS.parent / "scripts"
for _p in (str(HOOKS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shelltext  # noqa: E402

GIT_HOOK_DIR = (HOOKS / "git").resolve()
PREFIX = "cta gate guard: "
TAIL = (" The commit gate runs as git hooks in this repository; commit normally and fix what the "
        "gate reports.")

_NO_VERIFY = re.compile(r"--no-v(?:e(?:r(?:i(?:fy?)?)?)?)?(?![\w-])")
_HOOKS_PATH = re.compile(r"hookspath", re.IGNORECASE)
_GIT_CONFIG = re.compile(r"GIT_CONFIG")
_CONFIG_OPT = re.compile(r"(?<![\w-])-c\s*(?:core|include|includeif)\.|--config-env", re.IGNORECASE)
_GIT_HOOKS = re.compile(r"\.git/hooks")
_GATE_FILES = re.compile(r"\.cta/gate\.json|hooks/git(?![\w.-])|\.git/config(?![\w.-])")
_WRITE = re.compile(
    r">|(?<![\w./-])(?:rm|mv|cp|tee|chmod|chown|ln|unlink|truncate|install|rsync|dd|shred)(?![\w.-])"
    r"|(?<![\w./-])(?:sed|perl|ruby)\b.*\s(?:-[A-Za-z]*i|--in-place)")
_REMOVE = re.compile(r"(?<![\w./-])(?:rm|mv|unlink)(?![\w.-])")
_SEGMENT = re.compile(r"[;&|\n]+")
_VALUE_LETTERS = set("mFCctuS")


def _commit_short_n(text: str) -> bool:
    """`git ... commit` followed by a short-option cluster that sets -n (--no-verify)."""
    for body in sorted(set(shelltext.substitutions(text)), key=len, reverse=True):
        text = text.replace(body, " ")  # bodies are checked as variants of their own
    for seg in _SEGMENT.split(text):
        words = seg.split()
        gits = [i for i, w in enumerate(words) if os.path.basename(w) == "git"]
        if not gits:
            continue
        rest = words[gits[0] + 1:]
        at = next((i for i, w in enumerate(rest) if w.endswith("commit")), None)
        if at is None:
            continue
        for w in rest[at + 1:]:
            if re.fullmatch(r"-[A-Za-z]+", w):
                for letter in w[1:]:
                    if letter == "n":
                        return True
                    if letter in _VALUE_LETTERS:
                        break
    return False


def _rules(text: str) -> list[tuple[str, str]]:
    """(rule, reason) for every refusal rule the text matches."""
    hits = []
    if _NO_VERIFY.search(text):
        hits.append(("any", "--no-verify skips the commit gate."))
    if _HOOKS_PATH.search(text):
        hits.append(("any", "changing core.hooksPath disables the commit gate."))
    if _GIT_CONFIG.search(text):
        hits.append(("any", "GIT_CONFIG* variables can override core.hooksPath."))
    if _CONFIG_OPT.search(text):
        hits.append(("any", "`-c core.*`, `-c include.*` and --config-env can override core.hooksPath."))
    if _GIT_HOOKS.search(text):
        hits.append(("any", ".git/hooks is chained by the commit gate; leave it alone."))
    if _GATE_FILES.search(text) and _WRITE.search(text):
        hits.append(("any", "the commit gate's files (.cta/gate.json, the git hooks, .git/config) "
                            "are not edited from the shell."))
    if _commit_short_n(text):
        hits.append(("any", "`git commit -n` is --no-verify and skips the commit gate."))
    if "active-build" in text and _REMOVE.search(text):
        hits.append(("active", "the active-build pointer gates commits during a build; "
                               "end the build with the loop's close step."))
    return hits


def _candidates(texts: list[str], cwd: Path) -> list[Path]:
    """The payload cwd plus every literal `cd`, `pushd` or `-C` path."""
    out = [cwd]
    for text in texts:
        words = re.split(r"[\s;&|()]+", text)
        for i, w in enumerate(words[:-1]):
            if w in ("cd", "pushd", "-C"):
                target = words[i + 1]
                if not target or "$" in target or "`" in target or target == "-":
                    continue
                p = Path(os.path.expanduser(target))
                out.append(p if p.is_absolute() else cwd / p)
    return out


def _gated_dirs(texts: list[str], cwd: Path) -> list[Path]:
    """Top levels of the gated repositories the command may act on."""
    import gitgate
    from findings import git_env

    tops: list[Path] = []
    for path in _candidates(texts, cwd):
        if not path.is_dir():
            continue
        proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, env=git_env(), stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            continue
        top = Path(proc.stdout.rstrip("\n"))
        if top not in tops and gitgate.is_gated(top):
            tops.append(top)
    return tops


def _bash(command: str, cwd: Path) -> str | None:
    texts = shelltext.variants(command)
    hits = [h for t in texts for h in _rules(t)]
    if not hits:
        return None
    try:
        tops = _gated_dirs(texts, cwd)
    except Exception as exc:
        return f"{PREFIX}cannot tell whether the repository is gated ({type(exc).__name__}); refused."
    if not tops:
        return None
    active = any((t / ".cta" / "active-build").exists() for t in tops)
    for rule, reason in hits:
        if rule == "any" or active:
            return PREFIX + reason + TAIL
    return None


def _is_under(path: str, directory: Path) -> bool:
    try:
        return Path(path).is_relative_to(directory)
    except ValueError:
        return False


def _file(tool_input: dict, cwd: Path) -> str | None:
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = raw if os.path.isabs(raw) else os.path.join(str(cwd), raw)
    real = os.path.realpath(path)
    for p in (os.path.normpath(path), real):
        if p.replace("\\", "/").endswith("/.cta/gate.json") or _is_under(p, GIT_HOOK_DIR):
            return PREFIX + "the commit gate's own files are not edited." + TAIL
    import gitgate

    norm = real.replace("\\", "/")
    if norm.endswith("/.git/config") and gitgate.is_gated(Path(real).parent.parent):
        return PREFIX + ".git/config holds core.hooksPath for the commit gate." + TAIL
    if "/.git/hooks/" in norm:
        top = Path(norm.split("/.git/hooks/")[0])
        if gitgate.is_gated(top):
            return PREFIX + ".git/hooks is chained by the commit gate; leave it alone." + TAIL
    return None


def check(tool_name: str, tool_input, cwd=None) -> str | None:
    """The refusal reason, or None to allow."""
    if not isinstance(tool_input, dict):
        return None
    base = Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())
    if tool_name == "Bash":
        command = tool_input.get("command")
        return _bash(command, base) if isinstance(command, str) else None
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return _file(tool_input, base)
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        reason = check(data.get("tool_name", ""), data.get("tool_input"), data.get("cwd"))
    except Exception:
        return 0
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
