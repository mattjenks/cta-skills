#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse guard: the assistant never closes a security finding.

Only the owner sets a finding's status to `false-positive` or `accepted-risk`
(findings.MATT_ONLY). The assistant may set `proposed-false-positive` with its
reasoning. Rules:

Write / Edit / MultiEdit, for a path that ends in `security.json` (case-insensitive),
either as given or after resolving symlinks (relative paths use the payload `cwd`):
  the RESULTING file is computed (Write: the new content; Edit/MultiEdit: the
  current file with every replacement applied in order, `replace_all` honoured)
  and parsed as JSON. Findings are objects carrying a `status` (or an `id`), grouped
  by `id` and compared with the current file as multisets. The call is blocked when,
  for any id:
  - more entries are closed (MATT_ONLY status) than before;
  - an entry that was not closed disappears (removed, renamed, or its `status` dropped);
  - an entry that is not closed carries anything other than `open`, `fixed` or
    `proposed-false-positive` (any non-string such as null, a number, a list or an object;
    an empty or unknown word).
  Entries already closed stay editable and may be removed. Renaming an open finding onto
  an already-closed id is caught by the disappearance rule, also when a fresh entry
  reuses the old id. The call is blocked (fail closed) when the current file cannot be
  read for an Edit, or the result is not valid JSON.

Bash (after folding quotes and backslashes, and looking inside `$(...)` and
backticks), per command segment:
  1. the command mentions `security.json` together with `false-positive` or
     `accepted-risk` not directly preceded by `proposed-`; or
  2. a shell write whose target could be a findings file: a redirection
     (`>`, `>>`, `>|`), `tee`, `sponge`, `sed -i`/`--in-place`, `perl -i`,
     `ruby -i`, `gawk -i inplace`, `mv`, `ln`/`link`, `cp -l`/`--link`, `rsync`,
     `dd of=`, `cp`/`install` with the target last, `rm`/`unlink`/`truncate`/`shred`,
     or an interpreter (python, node, perl, ruby) whose code mentions `security.json`
     and calls a write. A target "could be" a findings file when its name ends in
     `security.json`, or is a glob that matches `security.json` and also contains
     `json` or `sec`, or sits under a `builds` directory; or
  3. a shell edit aimed under `.cta/` or a `builds/` folder: a redirection target, `tee`,
     `sponge`, `mv`, `rsync`, `cp`/`install` target, `dd of=`, `cp -l`/`--link` (also
     `cp -al` of a whole tree), an in-place `sed`/`perl`/`ruby`/`awk`, `ex`, `ed`, `vi`/`vim`/`nvim`, `patch`, `git apply`, or `find` with
     `-exec`/`-execdir`/`-ok`/`-okdir`/`-delete`, when an argument names such a path or
     globs into one (a glob component that matches `.cta` or `builds`, so a bare `*`
     counts), or the payload `cwd` itself lies under one and the argument is relative.
  No surrounding words are needed. Reads (`jq ... security.json > /tmp/x.json`, `cat`,
  `sed -n`, `find` without an action, an interpreter that only reads) pass.

False positives accepted: a `cwd` inside any folder named `builds` protects every relative
argument; a bare `*` argument to an in-place tool is refused anywhere.

Known gaps (residual, documented): paths assembled at runtime (variables, command
output, `cd` to a computed directory); scripts and programs that edit files themselves
(a script file written by a tool call that does not touch a protected path, then run);
a patch file whose content targets a protected path when no argument names one.

Exit 2 with the reason on stderr blocks; anything else exits 0. Input that is not JSON
exits 0. An unexpected error fails CLOSED (exit 2) when the payload's `file_path` or
`command` names a `security.json`, and open otherwise.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

HOOKS = Path(__file__).resolve().parent
SCRIPTS = HOOKS.parent / "scripts"
for _p in (str(HOOKS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shelltext  # noqa: E402

try:
    from findings import ASSISTANT_STATUSES, MATT_ONLY  # noqa: E402
except Exception:
    MATT_ONLY = {"false-positive", "accepted-risk"}
    ASSISTANT_STATUSES = {"open", "fixed", "proposed-false-positive"}

MESSAGE = 'only Matt closes findings; set "proposed-false-positive" with your reasoning'

_MENTION = re.compile(rf"(?<!proposed-)({'|'.join(sorted(re.escape(x) for x in MATT_ONLY))})",
                      re.IGNORECASE)
_TARGET = "security.json"
READ_FAIL = MESSAGE  # fail closed: the edit cannot be verified
_IN_PLACE = re.compile(r"^-[A-Za-z]*i|^--in-place")
_WRITE_CALL = re.compile(
    r"\b(?:write|writelines|dump|dumps|write_text|write_bytes|writefile|writefilesync|rename|"
    r"replace|unlink|truncate|copy|copyfile|move|rmtree|appendfile)\w*\s*\(|"
    r"open\s*\([^)]*,\s*['\"]?[^'\")]*[wax+]|\s-i\b", re.IGNORECASE)
_INTERPRETERS = {"python", "python2", "python3", "node", "perl", "ruby", "uv", "deno", "bun"}
_PROTECTED_DIRS = (".cta", "builds")


_ABSENT = object()
_BAD = object()  # any status that is not a string (null, number, list, object)


def _norm(value):
    return value.strip().lower() if isinstance(value, str) else _BAD


def _closed(value) -> bool:
    return isinstance(value, str) and _norm(value) in MATT_ONLY


def _entries(doc) -> dict:
    """{finding id: [normalized status, ...]} for every object carrying `status` or an `id`
    (`_ABSENT` when it has no status). Id-less objects with a status get a unique key."""
    out: dict = {}

    def walk(node):
        if isinstance(node, dict):
            keys = {str(k).lower(): k for k in node}
            ident = node.get("id")
            has_id = isinstance(ident, (str, int)) and not isinstance(ident, bool) and ident != ""
            if "status" in keys or has_id:
                status = _norm(node[keys["status"]]) if "status" in keys else _ABSENT
                out.setdefault(ident if has_id else object(), []).append(status)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return out


def _violation(before: dict, after: dict) -> bool:
    """Per id: closed entries may not grow, open (non-closed) entries may not disappear, and
    every entry that is not closed must carry an assistant status (open, fixed,
    proposed-false-positive). Ids are compared as multisets, so renaming an open finding onto
    an already-closed id is caught too."""
    for key in set(before) | set(after):
        old, new = before.get(key, []), after.get(key, [])
        if any(s is _ABSENT for s in old) and not any(s is not _ABSENT for s in old):
            old = []  # an object with an id but no status was never a finding
        if not any(s is not _ABSENT for s in new) and not old:
            continue
        closed_old = sum(1 for s in old if _closed(s))
        closed_new = sum(1 for s in new if _closed(s))
        if closed_new > closed_old:
            return True
        kept = [s for s in new if not _closed(s)]
        if len(kept) < len(old) - closed_old:
            return True
        if any(s not in ASSISTANT_STATUSES for s in kept):
            return True
    return False


def _is_target(path) -> bool:
    return isinstance(path, str) and path.replace("\\", "/").lower().endswith(_TARGET)


def _target_path(tool_input: dict, cwd) -> tuple[bool, str]:
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw:
        return False, ""
    path = raw if os.path.isabs(raw) or not cwd else os.path.join(str(cwd), raw)
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        real = path
    return (_is_target(raw) or _is_target(real)), real


def _apply(content: str, edits: list) -> str:
    for old, new, every in edits:
        if isinstance(old, str) and isinstance(new, str) and old in content and old != "":
            content = content.replace(old, new) if every else content.replace(old, new, 1)
    return content


def _file_check(tool_name: str, tool_input: dict, real: str) -> str | None:
    try:
        with open(real, encoding="utf-8") as fh:
            current = fh.read()
    except (OSError, UnicodeDecodeError):
        current = None
    if tool_name == "Write":
        new = tool_input.get("content")
        if not isinstance(new, str):
            return None
    else:
        if current is None:
            return READ_FAIL
        if tool_name == "Edit":
            steps = [(tool_input.get("old_string"), tool_input.get("new_string"),
                      bool(tool_input.get("replace_all")))]
        else:
            edits = tool_input.get("edits")
            if not isinstance(edits, list) or not all(isinstance(e, dict) for e in edits):
                return READ_FAIL
            steps = [(e.get("old_string"), e.get("new_string"), bool(e.get("replace_all")))
                     for e in edits]
        new = _apply(current, steps)
    try:
        after = _entries(json.loads(new))
    except ValueError:
        return READ_FAIL
    try:
        before = _entries(json.loads(current)) if current else {}
    except ValueError:
        before = {}
    return MESSAGE if _violation(before, after) else None


def _is_candidate(word: str) -> bool:
    """Could this word name a findings file?"""
    low = word.lower().rsplit("=", 1)[-1]
    base = low.rsplit("/", 1)[-1]
    if base.endswith(_TARGET):
        return True
    if any(c in base for c in "*?[") and fnmatch.fnmatch(_TARGET, base):
        return "json" in base or "sec" in base or "/builds/" in "/" + low
    return False


def _segments(text: str):
    """(words, redirect targets) per command segment; LexError propagates."""
    words: list[str] = []
    targets: list[str] = []
    items = shelltext.lex(text)
    k = 0
    while k < len(items):
        kind, val = items[k]
        if kind == "word":
            words.append(val)
        elif ">" in val and "<" not in val:
            if k + 1 < len(items) and items[k + 1][0] == "word":
                targets.append(items[k + 1][1])
                k += 1
        elif "<" in val:
            if k + 1 < len(items) and items[k + 1][0] == "word":
                k += 1
        else:
            yield words, targets
            words, targets = [], []
        k += 1
    yield words, targets


def _protected_parts(parts: list[str]) -> bool:
    for part in parts:
        if part in _PROTECTED_DIRS:
            return True
        if any(c in part for c in "*?[") and any(fnmatch.fnmatch(d, part) for d in _PROTECTED_DIRS):
            return True
    return False


def _protected(word: str, cwd: str | None) -> bool:
    """Does the word name (or glob into) a path under `.cta/` or a `builds/` folder? A relative
    word counts when the working directory is itself under one."""
    w = word.lower().replace("\\", "/").rsplit("=", 1)[-1]
    if _protected_parts([p for p in w.split("/") if p]):
        return True
    if cwd and not w.startswith(("/", "~")):
        return _protected_parts([p for p in str(cwd).lower().replace("\\", "/").split("/") if p])
    return False


def _segment_writes(words: list[str], targets: list[str], cwd: str | None = None) -> bool:
    def guarded(w: str) -> bool:
        return _is_candidate(w) or _protected(w, cwd)

    if any(guarded(t) for t in targets):
        return True
    names = {PurePosixPath(w).name for w in words}
    flags = [w for w in words if w.startswith("-")]
    cands = [w for w in words if _is_candidate(w)]
    guards = [w for w in words if guarded(w)]
    if guards:
        if names & {"tee", "sponge", "mv", "rsync", "ex", "ed", "patch", "vim", "vi", "nvim"}:
            return True
        if names & {"cp", "install"} and words and guarded(words[-1]):
            return True
        if "dd" in names and any(w.lower().startswith("of=") and guarded(w) for w in words):
            return True
        if names & {"sed", "perl", "ruby", "gawk", "awk"}:
            if any(_IN_PLACE.match(f) for f in flags) or "inplace" in words:
                return True
        if "git" in names and "apply" in names:
            return True
        if "find" in names and names & {"-exec", "-execdir", "-ok", "-okdir", "-delete"}:
            return True
        if "cp" in names and any(f == "--link" or re.fullmatch(r"-[A-Za-z]*l[A-Za-z]*", f) for f in flags):
            return True  # hard links into a protected tree can be edited freely afterwards
    if cands:
        if names & {"ln", "link", "rm", "unlink", "truncate", "shred"}:
            return True
        if "cp" in names and any(f == "--link" or re.fullmatch(r"-[A-Za-z]*l[A-Za-z]*", f) for f in flags):
            return True
    if not cands and not any(_TARGET in w.lower() for w in words):
        return False
    return _interpreter_writes(words, " ".join(words))


def _interpreter_writes(words: list[str], text: str) -> bool:
    names = {PurePosixPath(w).name.rstrip("0123456789.") for w in words}
    if not names & _INTERPRETERS or not any(_TARGET in w.lower() for w in words):
        return False
    return bool(_WRITE_CALL.search(text))


def _bash_blocked(text: str, cwd: str | None = None) -> bool:
    low = text.lower()
    if _TARGET in low and _MENTION.search(low):
        return True
    try:
        segs = list(_segments(text))
        # a heredoc body is code for the interpreter on an earlier line: judge the whole text too
        return any(_segment_writes(w, t, cwd) for w, t in segs) or _interpreter_writes(
            [w for words, _ in segs for w in words], text)
    except shelltext.LexError:
        return bool(("security" in low or "builds" in low or ".cta" in low) and re.search(
            r">|\b(?:tee|sed|perl|mv|cp|ln|link|dd|rsync|sponge|python3?|node|ruby|ex|ed|vim?|patch|"
            r"find|rm|unlink|truncate)\b", low))


def check(tool_name: str, tool_input: dict, cwd=None) -> str | None:
    """Return the block reason, or None to allow."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool_name in ("Write", "Edit", "MultiEdit"):
        hit, real = _target_path(tool_input, cwd)
        return _file_check(tool_name, tool_input, real) if hit else None
    if tool_name == "Bash":
        command = str(tool_input.get("command") or "")
        where = str(cwd) if cwd else None
        if any(_bash_blocked(v, where) for v in shelltext.variants(command)):
            return MESSAGE
    return None


def _mentions_findings(data) -> bool:
    try:
        tool_input = data.get("tool_input") or {}
        text = str(tool_input.get("file_path") or "") + " " + str(tool_input.get("command") or "")
        return _TARGET in text.lower().replace("\\", "/")
    except Exception:
        return False


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        reason = check(data.get("tool_name", ""), data.get("tool_input") or {}, data.get("cwd"))
    except Exception as exc:  # fail closed when a findings file is involved
        if _mentions_findings(data):
            print(f"{MESSAGE} (finding guard error: {type(exc).__name__})", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
