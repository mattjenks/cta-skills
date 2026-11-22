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
  and parsed as JSON. The call is blocked when a finding (any object with a
  `status`) has a MATT_ONLY status in the result but did not have one, under the
  same `id`, in the current file. Entries already closed stay editable. The call
  is blocked (fail closed) when the current file cannot be read for an Edit, or
  the result is not valid JSON.

Bash (after folding quotes and backslashes, and looking inside `$(...)` and
backticks), per command segment:
  1. the command mentions `security.json` together with `false-positive` or
     `accepted-risk` not directly preceded by `proposed-`; or
  2. a shell write whose target could be a findings file: a redirection
     (`>`, `>>`, `>|`), `tee`, `sponge`, `sed -i`/`--in-place`, `perl -i`,
     `ruby -i`, `gawk -i inplace`, `mv`, `ln`, `rsync`, `dd of=`, `cp`/`install`
     with the target last, or an interpreter (python, node, perl, ruby) whose
     code mentions `security.json` and calls a write. A target "could be" a
     findings file when its name ends in `security.json`, or is a glob that
     matches `security.json` and also contains `json` or `sec`, or sits under a
     `builds` directory. No surrounding words are needed. Reads (`jq ... security.json
     > /tmp/x.json`, `cat`, an interpreter that only reads) pass.

Known gaps: a script file that edits the findings, written by a tool call that
does not touch a `security.json` path; paths assembled at runtime.

Exit 2 with the reason on stderr blocks; anything else exits 0. Malformed input
and unexpected errors fail open (the commit gate, not this guard, fails closed).
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
    from findings import MATT_ONLY  # noqa: E402
except Exception:
    MATT_ONLY = {"false-positive", "accepted-risk"}

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


def _closed(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in MATT_ONLY


def _status_map(doc) -> dict:
    """{finding id: closed?} for every object carrying a `status`; id-less entries get a unique key."""
    out: dict = {}

    def walk(node):
        if isinstance(node, dict):
            keys = {str(k).lower(): k for k in node}
            if "status" in keys:
                ident = node.get("id")
                key = ident if isinstance(ident, (str, int)) and ident != "" else object()
                out[key] = out.get(key, False) or _closed(node[keys["status"]])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return out


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
        after = _status_map(json.loads(new))
    except ValueError:
        return READ_FAIL
    try:
        before = _status_map(json.loads(current)) if current else {}
    except ValueError:
        before = {}
    for key, closed in after.items():
        if closed and not before.get(key, False):
            return MESSAGE
    return None


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
    items = shelltext.lex(text, skip_heredocs=False)
    k = 0
    while k < len(items):
        kind, val = items[k]
        if kind == "word":
            words.append(val)
        elif val == "<<heredoc":
            pass
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


def _segment_writes(words: list[str], targets: list[str]) -> bool:
    if any(_is_candidate(t) for t in targets):
        return True
    cands = [w for w in words if _is_candidate(w)]
    mentions = any(_TARGET in w.lower() for w in words)
    if not cands and not mentions:
        return False
    names = {PurePosixPath(w).name for w in words}
    flags = [w for w in words if w.startswith("-")]
    if names & {"tee", "sponge", "mv", "ln", "rsync"} and cands:
        return True
    if names & {"cp", "install"} and words and _is_candidate(words[-1]):
        return True
    if "dd" in names and any(w.lower().startswith("of=") and _is_candidate(w) for w in words):
        return True
    if names & {"sed", "perl", "ruby", "gawk", "awk"} and cands:
        if any(_IN_PLACE.match(f) for f in flags) or "inplace" in words:
            return True
    return _interpreter_writes(words, " ".join(words))


def _interpreter_writes(words: list[str], text: str) -> bool:
    names = {PurePosixPath(w).name.rstrip("0123456789.") for w in words}
    if not names & _INTERPRETERS or not any(_TARGET in w.lower() for w in words):
        return False
    return bool(_WRITE_CALL.search(text))


def _bash_blocked(text: str) -> bool:
    low = text.lower()
    if _TARGET in low and _MENTION.search(low):
        return True
    try:
        segs = list(_segments(text))
        # a heredoc body is code for the interpreter on an earlier line: judge the whole text too
        return any(_segment_writes(w, t) for w, t in segs) or _interpreter_writes(
            [w for words, _ in segs for w in words], text)
    except shelltext.LexError:
        return bool(("security" in low or "builds" in low) and re.search(
            r">|\b(?:tee|sed|perl|mv|cp|ln|dd|rsync|sponge|python3?|node|ruby)\b", low))


def check(tool_name: str, tool_input: dict, cwd=None) -> str | None:
    """Return the block reason, or None to allow."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool_name in ("Write", "Edit", "MultiEdit"):
        hit, real = _target_path(tool_input, cwd)
        return _file_check(tool_name, tool_input, real) if hit else None
    if tool_name == "Bash":
        command = str(tool_input.get("command") or "")
        if any(_bash_blocked(v) for v in shelltext.variants(command)):
            return MESSAGE
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
        reason = check(data.get("tool_name", ""), data.get("tool_input") or {}, data.get("cwd"))
    except Exception:
        sys.exit(0)
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
