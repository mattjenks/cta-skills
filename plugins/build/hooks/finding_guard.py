#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse guard: the assistant never closes a security finding.

Only the owner sets a finding's status to `false-positive` or `accepted-risk`
(findings.MATT_ONLY). The assistant may set `proposed-false-positive` with its
reasoning. Rules:

Write / Edit / MultiEdit, for a path ending in `security.json` (case-insensitive):
  the NEW content (Write `content`, Edit `new_string`, each MultiEdit
  `edits[].new_string`) is blocked when
  - it parses as JSON and any string anywhere in it, once stripped and
    lowercased, is one of the two closing statuses; or
  - it does not parse (an Edit fragment) and matches `"status": "<closing>"`
    or a bare quoted `"<closing>"` value.
  `"proposed-false-positive"` never matches: the quote must touch the word.
  A Write that rewrites a file Matt already closed findings in is blocked too;
  the assistant should Edit around those entries.

Bash (after folding quotes and backslashes, and looking inside `$(...)` and
backticks):
  1. the command mentions `security.json` together with `false-positive` or
     `accepted-risk` not directly preceded by `proposed-`; or
  2. the command mentions `security.json` and `status` (or `proposed`) and
     writes through the shell: a redirection into a path ending in
     `security.json`; `tee`; `sed -i`/`--in-place`; an interpreter (`python`,
     `node`, `perl`, `ruby`); `jq` or `awk` together with a redirection, `mv`,
     `cp`, `tee` or `sponge`; or `mv`/`cp`/`install` aimed at it. The assistant
     edits findings with Write/Edit; reads (`jq ... security.json`, `cat`) pass.

Known gaps: a script file that edits the findings, written by a tool call that
does not touch a `security.json` path; paths assembled at runtime.

Exit 2 with the reason on stderr blocks; anything else exits 0. Malformed input
and unexpected errors fail open (the commit gate, not this guard, fails closed).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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

_CLOSING = "|".join(sorted(re.escape(s) for s in MATT_ONLY))
_STATUS_VALUE = re.compile(rf'"status"\s*:\s*"\s*({_CLOSING})\s*"', re.IGNORECASE)
_QUOTED_VALUE = re.compile(rf'"\s*({_CLOSING})\s*"', re.IGNORECASE)
_MENTION = re.compile(rf"(?<!proposed-)({_CLOSING})", re.IGNORECASE)
_TARGET = "security.json"
_REDIRECT = re.compile(r">[>|]?\s*[^\s;&|<>]*security\.json", re.IGNORECASE)
_TEE = re.compile(r"\btee\b[^;&|\n]*security\.json", re.IGNORECASE)
_MOVE = re.compile(r"\b(?:mv|cp|install)\b[^;&|\n]*security\.json", re.IGNORECASE)
_SED_I = re.compile(r"\bsed\b[^;&|\n]*\s(?:-[A-Za-z]*i|--in-place)", re.IGNORECASE)
_INTERPRETER = re.compile(r"\b(?:python[0-9.]*|node|perl|ruby)\b", re.IGNORECASE)
_JQ_LIKE = re.compile(r"\b(?:jq|awk|gawk)\b", re.IGNORECASE)
_SINK = re.compile(r">|\b(?:mv|cp|tee|sponge)\b", re.IGNORECASE)


def _closing_in_json(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in MATT_ONLY
    if isinstance(value, dict):
        return any(_closing_in_json(v) for v in value.values())
    if isinstance(value, list):
        return any(_closing_in_json(v) for v in value)
    return False


def _content_closes(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    try:
        return _closing_in_json(json.loads(text))
    except ValueError:
        pass
    return bool(_STATUS_VALUE.search(text) or _QUOTED_VALUE.search(text))


def _is_target(path) -> bool:
    return isinstance(path, str) and path.replace("\\", "/").lower().endswith(_TARGET)


def _new_contents(tool_name: str, tool_input: dict) -> list:
    if tool_name == "Write":
        return [tool_input.get("content")]
    if tool_name == "Edit":
        return [tool_input.get("new_string")]
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        return [e.get("new_string") for e in edits if isinstance(e, dict)] if isinstance(edits, list) else []
    return []


def _bash_blocked(text: str) -> bool:
    low = text.lower()
    if _TARGET not in low:
        return False
    if _MENTION.search(low):
        return True
    if "status" not in low and "proposed" not in low:
        return False
    if _REDIRECT.search(low) or _TEE.search(low) or _MOVE.search(low):
        return True
    if _SED_I.search(low) or _INTERPRETER.search(low):
        return True
    return bool(_JQ_LIKE.search(low) and _SINK.search(low))


def check(tool_name: str, tool_input: dict) -> str | None:
    """Return the block reason, or None to allow."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool_name in ("Write", "Edit", "MultiEdit"):
        if not _is_target(tool_input.get("file_path")):
            return None
        if any(_content_closes(c) for c in _new_contents(tool_name, tool_input)):
            return MESSAGE
        return None
    if tool_name == "Bash":
        command = str(tool_input.get("command") or "")
        if any(_bash_blocked(v) for v in shelltext.variants(command)):
            return MESSAGE
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
        reason = check(data.get("tool_name", ""), data.get("tool_input") or {})
    except Exception:
        sys.exit(0)
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
