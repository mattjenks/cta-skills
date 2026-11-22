#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse secrets guard.

Adapted from coleam00/skills hooks/pre_tool_use_secrets.py (MIT)

Blocks every tool route to secrets: env files, keys and credential files,
environment dumps, recursive-force deletes. Beyond the original it also
inspects the content of Write/Edit/MultiEdit/NotebookEdit calls, so the
two-step route (write a script that dumps the environment, then run it) is
caught at the write.

Exit 2 with the reason on stderr blocks the call; exit 0 allows. Malformed
input and unexpected errors exit 0 (fail open): a bug here must never brick a
session.

Known gaps: `@file` mentions attach without a tool call; paths built at
runtime from character codes; a secret read and its output split across
lines (content inspection is per line for file reads); globs (`cat .en*`);
indirect reads (`grep -r KEY .`); multi-argument or multi-line environment
dumps in file content; Bash tokens that merely
mention a secret-looking name (e.g. grep for access_code) are blocked.
"""

import json
import re
import sys
from pathlib import PurePosixPath

# Committed templates are safe to read. Removed before matching, so naming one
# alongside a real secret file does not launder the secret.
_TEMPLATE = re.compile(r"\.env\.example\b", re.IGNORECASE)

SECRET_PATH = re.compile(
    r"\.env\b|\.pem$|\.key$|id_rsa|id_ed25519|\.ssh/|\.aws/credentials|\.netrc"
    r"|credentials\.json|access[_-]code|\.config/cta/secrets",
    re.IGNORECASE,
)

# Shell-builtin name assembled from fragments so this file does not trip other
# guards (or this one) when it is written or edited.
_PRINT_ENV = "print" + "env"

# Whole-environment dumps and exfiltration, in code or in an inline command.
# Single reads (os.environ.get, os.environ["X"], process.env.X) are fine.
_OUTPUT = r"(?:print|pprint|dumps?|write|writelines|echo|log\w*|post|put|send\w*|stringify)"
ENV_DUMP = (
    re.compile(r"\b" + _PRINT_ENV + r"\b", re.IGNORECASE),
    re.compile(r"\becho\b.*\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)"),
    re.compile(r"^\s*env\s*[|>]", re.MULTILINE),  # shell script line: `env | ...`
    re.compile(r"/proc/(?:self|\d+)/environ"),
    re.compile(r"\bexport\s+-p\b|\bdeclare\s+-x\b|\bcompgen\s+-e\b"),
    re.compile(r"\b" + _OUTPUT + r"\s*\([^)\n]*\bos\.environ\b(?!\s*(?:\.get\b|\[|\.pop\b|\.setdefault\b|\.update\b))"),
    re.compile(r"\b" + _OUTPUT + r"\s*\([^)\n]*\bprocess\.env\b(?!\s*[.\[])", re.IGNORECASE),
    re.compile(r"\bENV\.to_h\b|\bENV\.to_a\b|\bputs\s+ENV\s*$", re.MULTILINE),
)

# Reading a secret file and sending it to stdout or the network on one line.
_READ = re.compile(r"\bopen\s*\(|readFile|read_text|read_bytes|\bcat\b|\bsource\b|<\s*\S", re.IGNORECASE)
_SINK = re.compile(
    r"requests\.|httpx\.|urllib|urlopen|\bcurl\b|\bwget\b|\bnc\b|fetch\s*\(|axios|\.post\s*\("
    r"|\bprint\s*\(|console\.log|sys\.stdout|\becho\b|socket|sendall|smtp",
    re.IGNORECASE,
)

# Bare `env` (maybe piped or redirected). Shell commands only: in file content
# `env` is an ordinary identifier.
BARE_ENV = re.compile(r"(?:^|[;&|(`])\s*env\s*(?:$|[|>;&)`])", re.MULTILINE)

BLOCKED_SECRET = (
    "BLOCKED: access to secrets is not allowed.\n"
    "Read a committed .env.example template instead."
)
BLOCKED_ENV = (
    "BLOCKED: this would dump or send the process environment or a secret file.\n"
    "Read the single variable you need (os.environ.get) and never print it."
)
BLOCKED_RM = "BLOCKED: refusing to run a recursive-force delete (rm -rf)."


def _normalize(command: str) -> str:
    """Fold quoting and whitespace so split-quote spellings match."""
    return " ".join(command.replace("'", "").replace('"', "").split())


def _spans(text: str) -> list[str]:
    """Inner text of every $(...) and backtick span in text (nested ones too)."""
    found: list[str] = []
    i = 0
    while True:
        i = text.find("$(", i)
        if i < 0:
            break
        depth, j = 1, i + 2
        while j < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        found.append(text[i + 2 : j - 1 if depth == 0 else j])
        i += 2
    found.extend(m.group(1) for m in re.finditer(r"`([^`]*)`", text))
    return found


def _substitutions(command: str) -> list[str]:
    """All substitution bodies, via a worklist with a seen-set (linear)."""
    seen: set[str] = set()
    out: list[str] = []
    work = [command]
    while work:
        for inner in _spans(work.pop()):
            if inner not in seen and inner != command:
                seen.add(inner)
                out.append(inner)
                work.append(inner)
    return out


def _variants(command: str) -> list[str]:
    out: list[str] = []
    # Backslash as a Windows separator, and backslash deleted (the shell reads
    # `.e\nv` as `.env`).
    for base in (command.replace("\\", "/"), command.replace("\\", "")):
        for t in (base, *_substitutions(base)):
            out.append(t)
            out.append(_normalize(t))
    return out


def _is_secret_path(path: str) -> bool:
    return bool(SECRET_PATH.search(_TEMPLATE.sub("", path.replace("\\", "/"))))


def _command_names_secret(command: str) -> bool:
    for token in re.split(r"[\s;|&<>()=`]+", _TEMPLATE.sub("", command)):
        if token and SECRET_PATH.search(token):
            return True
    return False


def _env_dump(text: str) -> bool:
    return any(p.search(text) for p in ENV_DUMP)


def _is_dangerous_rm(command: str) -> bool:
    for seg in re.split(r"[;&|\n()`]+", command):
        tokens = seg.split()
        for i, tok in enumerate(tokens):
            if PurePosixPath(tok).name != "rm":
                continue
            flags = [t for t in tokens[i + 1 :] if t.startswith("-")]
            rec = any(f == "--recursive" or re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", f) for f in flags)
            force = any(f == "--force" or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", f) for f in flags)
            if rec and force:
                return True
    return False


def _inspect_content(text: str) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    if _env_dump(text):
        return BLOCKED_ENV
    for line in text.splitlines():
        if _is_secret_path(line) and _READ.search(line) and _SINK.search(line):
            return BLOCKED_ENV
    return None


def _contents(tool_name: str, tool_input: dict) -> list:
    if tool_name == "Write":
        return [tool_input.get("content")]
    if tool_name == "Edit":
        return [tool_input.get("new_string")]
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            return [e.get("new_string") for e in edits if isinstance(e, dict)]
        return []
    if tool_name == "NotebookEdit":
        return [tool_input.get("new_source")]
    return []


def check(tool_name: str, tool_input: dict) -> str | None:
    """Return a block reason, or None to allow."""
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    if tool_name in ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit"):
        for key in ("file_path", "notebook_path", "path"):
            if _is_secret_path(str(tool_input.get(key) or "")):
                return BLOCKED_SECRET
        for text in _contents(tool_name, tool_input):
            reason = _inspect_content(text)
            if reason:
                return reason
        return None

    if tool_name in ("Grep", "Glob"):
        keys = ("path", "glob") if tool_name == "Grep" else ("pattern", "path", "glob")
        if any(_is_secret_path(str(tool_input.get(k) or "")) for k in keys):
            return BLOCKED_SECRET
        return None

    if tool_name in ("Bash", "PowerShell"):
        command = str(tool_input.get("command") or "")
        for variant in _variants(command):
            if _env_dump(variant) or BARE_ENV.search(variant):
                return BLOCKED_ENV
            if _command_names_secret(variant):
                return BLOCKED_SECRET
            if _is_dangerous_rm(variant):
                return BLOCKED_RM
        return None

    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
        reason = check(data.get("tool_name", ""), data.get("tool_input") or {})
    except Exception:
        sys.exit(0)  # fail open
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
