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
dumps in file content; Bash commands over 20,000 characters (e.g. large
heredoc writes) and file content over 2,000,000 characters are blocked
as too complex; in prose files (.md .markdown .txt .rst .adoc) the dump
builtins are caught only at command position (line start, after a separator,
`$(`, a prefix word, or `-c`), with bounded prefix options/assignments, so a
prose file holding a dump elsewhere passes the Write and could later be run
as a script; Bash commands that only mention a builtin are blocked, as are
Bash tokens that merely mention a secret-looking name (e.g. grep for
access_code).
"""

import json
import re
import sys
import time
from pathlib import PurePosixPath

# Committed templates are safe to read. Removed before matching, so naming one
# alongside a real secret file does not launder the secret.
_TEMPLATE = re.compile(r"\.env\.example\b", re.IGNORECASE)

SECRET_PATH = re.compile(
    r"\.env\b|\.pem$|\.key$|id_rsa|id_ed25519|\.ssh/|\.aws/credentials|\.netrc"
    r"|credentials\.json|access[_-]code|\.config/cta/secrets",
    re.IGNORECASE,
)
# Same pattern for multi-line content: `$` must also match at each line end.
_SECRET_LINE = re.compile(SECRET_PATH.pattern, re.IGNORECASE | re.MULTILINE)

# Shell-builtin name assembled from fragments so this file does not trip other
# guards (or this one) when it is written or edited.
_PRINT_ENV = "print" + "env"

# Whole-environment dumps and exfiltration, in code or in an inline command.
# Single reads (os.environ.get, os.environ["X"], process.env.X) are fine.
# Every pattern is linear: a whitespace run that must not cross a line uses
# [ \t], never \s, and no pattern carries an unbounded gap between two parts.
_BUILTIN_ANY = re.compile(r"\bexport[ \t]+-p\b|\bdeclare[ \t]+-x\b|\bcompgen[ \t]+-e\b")
ENV_DUMP = (
    re.compile(r"\b" + _PRINT_ENV + r"\b", re.IGNORECASE),
    re.compile(r"^[ \t]*env[ \t]*[|>]", re.MULTILINE),  # shell script line: `env | ...`
    re.compile(r"/proc/(?:self|\d+)/environ"),
    # The three env-dump builtins anywhere: a dump held in a string (piped to a
    # shell, `trap`, `os.system("...")`, a Dockerfile RUN) cannot be anchored.
    _BUILTIN_ANY,
    re.compile(r"\bENV\.to_h\b|\bENV\.to_a\b|\bputs[ \t]+ENV[ \t]*$", re.MULTILINE),
)

# Prose files (notes, plans) may name a builtin, so their content is checked
# for it only at command position (line start, after a separator, `!`, `)` or
# `$(`, a command-prefix word, or a `-c` flag token, then optional prefix
# options and env assignments).
PROSE_SUFFIXES = (".md", ".markdown", ".txt", ".rst", ".adoc")
_BUILTIN_COMMAND = re.compile(
    r"(?:^|[;&|({!)]|\$\("
    r"|\b(?:then|do|else|eval|exec|command|builtin|if|while|until|sudo|nohup|time|env|xargs)\b"
    r"|(?<![\w-])-[A-Za-z]*c[ \t]*['\"]?)[ \t]*"
    r"(?:-[A-Za-z]+[ \t]+){0,4}"
    r"(?:\b[A-Za-z_]\w*=[^ \t\n]*[ \t]+){0,8}"
    r"(?:export[ \t]+-p\b|declare[ \t]+-x\b|compgen[ \t]+-e\b)",
    re.MULTILINE,
)

# Output and secret are matched up by one token scan per rule instead of a
# regex with a gap between them, so padding cannot push them apart.
_OUTPUT = r"(?:print|pprint|dumps?|write|writelines|echo|log\w*|post|put|send\w*|stringify)"
_SECRET_VAR = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API")

# `echo` then `$..KEY` (or TOKEN, SECRET...) later on the same line.
_ECHO_SCAN = re.compile(r"(\becho\b)|\$\{?([A-Z_]+)|(\n)")

# An output call `name(` then the whole environment before any `)` or line
# break: `print(dict(os.environ))`, `console.log('x', process.env)`.
_CALL_SCAN = (
    re.compile(
        r"(\b" + _OUTPUT + r"\s*\()|([)\n])"
        r"|(\bos\.environ\b(?!\s*(?:\.get\b|\[|\.pop\b|\.setdefault\b|\.update\b)))"
    ),
    re.compile(
        r"(\b" + _OUTPUT + r"\s*\()|([)\n])|(\bprocess\.env\b(?!\s*[.\[]))",
        re.IGNORECASE,
    ),
)


def _echo_secret(text: str) -> bool:
    echo = False
    for m in _ECHO_SCAN.finditer(text):
        if m.group(1):
            echo = True
        elif m.group(3):
            echo = False
        elif echo and any(w in m.group(2) for w in _SECRET_VAR):
            return True
    return False


def _output_env(text: str) -> bool:
    for scan in _CALL_SCAN:
        open_call = False
        for m in scan.finditer(text):
            if m.group(1):
                open_call = True
            elif m.group(2):
                open_call = False
            elif open_call:
                return True
    return False


_DUMP_CHECKS = (*(p.search for p in ENV_DUMP), _echo_secret, _output_env)
# Prose files swap the unanchored builtin pattern for the command-position one.
_PROSE_CHECKS = (
    *(p.search for p in ENV_DUMP if p is not _BUILTIN_ANY),
    _BUILTIN_COMMAND.search,
    _echo_secret,
    _output_env,
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
BARE_ENV = re.compile(r"(?:^|[;&|(`])[ \t]*env[ \t]*(?:$|[|>;&)`])", re.MULTILINE)

BLOCKED_SECRET = (
    "BLOCKED: access to secrets is not allowed.\n"
    "Read a committed .env.example template instead."
)
BLOCKED_ENV = (
    "BLOCKED: this would dump or send the process environment or a secret file.\n"
    "Read the single variable you need (os.environ.get) and never print it."
)
BLOCKED_COMPLEX = "BLOCKED: command too complex for the secrets guard to inspect"
MAX_COMMAND = 20_000
MAX_OPENERS = 256
MAX_INSPECTED = 200_000
MAX_CONTENT = 2_000_000  # total characters across one call's file content
DEADLINE_SECONDS = 2.0
BLOCKED_RM = "BLOCKED: refusing to run a recursive-force delete (rm -rf)."


def _normalize(command: str) -> str:
    """Fold quoting and whitespace so split-quote spellings match."""
    return " ".join(command.replace("'", "").replace('"', "").split())


def _substitutions(text: str) -> list[str]:
    """Body of every $(...) and backtick span, nested ones included.

    One stack-based pass over the original string; every nested span is already
    a substring of it, so bodies are never re-scanned. Unclosed spans run to
    the end of the string.
    """
    out: list[str] = []
    stack: list[int] = []  # body start for $( ; -1 for a plain "(" group
    tick = -1
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "$" and text.startswith("$(", i):
            stack.append(i + 2)
            i += 2
            continue
        if c == "(":
            stack.append(-1)
        elif c == ")" and stack:
            start = stack.pop()
            if start >= 0:
                out.append(text[start:i])
        elif c == "`":
            if tick < 0:
                tick = i + 1
            else:
                out.append(text[tick:i])
                tick = -1
        i += 1
    out.extend(text[st:] for st in stack if st >= 0)
    if tick >= 0:
        out.append(text[tick:])
    return out


def _bases(command: str) -> list[str]:
    # Backslash as a Windows separator, and backslash deleted (the shell reads
    # `.e\nv` as `.env`).
    return [command.replace("\\", "/"), command.replace("\\", "")]


def _is_secret_path(path: str) -> bool:
    return bool(SECRET_PATH.search(_TEMPLATE.sub("", path.replace("\\", "/"))))


def _command_names_secret(command: str) -> bool:
    for token in re.split(r"[\s;|&<>()=`]+", _TEMPLATE.sub("", command)):
        if token and SECRET_PATH.search(token):
            return True
    return False


def _env_dump(text: str) -> bool:
    return any(c(text) for c in _DUMP_CHECKS)


def _short_flags(tok: str) -> str:
    """Letters of a short-option cluster such as `-rf`, else ""."""
    body = tok[1:]
    return body if body.isascii() and body.isalpha() else ""


def _is_dangerous_rm(command: str) -> bool:
    """rm with recursive and force flags after it in the same segment (linear)."""
    for seg in re.split(r"[;&|\n()`]+", command):
        rec = force = False
        for tok in reversed(seg.split()):  # suffix flags, so no per-rm slicing
            if tok.startswith("-"):
                flags = _short_flags(tok)
                rec = rec or tok == "--recursive" or "r" in flags or "R" in flags
                force = force or tok == "--force" or "f" in flags
            elif rec and force and PurePosixPath(tok).name == "rm":
                return True
    return False


def _bash_reason(variant: str) -> str | None:
    if _env_dump(variant) or BARE_ENV.search(variant):
        return BLOCKED_ENV
    if _command_names_secret(variant):
        return BLOCKED_SECRET
    if _is_dangerous_rm(variant):
        return BLOCKED_RM
    return None


def _unify_newlines(text: str) -> str:
    """CRLF and lone CR become LF, so `$` and line scans see Windows and old-Mac files."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_prose_path(tool_input: dict) -> bool:
    return any(
        str(tool_input.get(k) or "").lower().endswith(PROSE_SUFFIXES)
        for k in ("file_path", "notebook_path")
    )


def _inspect_content(text: str, deadline: float, prose: bool = False) -> str | None:
    if not isinstance(text, str) or not text:
        return None
    text = _unify_newlines(text)
    for dump in _PROSE_CHECKS if prose else _DUMP_CHECKS:
        if time.monotonic() > deadline:
            return BLOCKED_COMPLEX
        if dump(text):
            return BLOCKED_ENV
    # Only lines naming a secret path need the read and sink checks. Template
    # removal and slash folding never touch a newline, so lines line up.
    folded = _TEMPLATE.sub("", text.replace("\\", "/"))
    pos = 0
    while (m := _SECRET_LINE.search(folded, pos)) is not None:
        if time.monotonic() > deadline:
            return BLOCKED_COMPLEX
        start = folded.rfind("\n", 0, m.start()) + 1
        end = folded.find("\n", m.end())
        end = len(folded) if end < 0 else end
        line = folded[start:end]
        if _READ.search(line) and _SINK.search(line):
            return BLOCKED_ENV
        pos = end + 1
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
    return _check(tool_name, tool_input, time.monotonic() + DEADLINE_SECONDS)


def _check(tool_name: str, tool_input: dict, deadline: float) -> str | None:
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    if tool_name in ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit"):
        for key in ("file_path", "notebook_path", "path"):
            if _is_secret_path(str(tool_input.get(key) or "")):
                return BLOCKED_SECRET
        texts = [t for t in _contents(tool_name, tool_input) if isinstance(t, str)]
        if sum(len(t) for t in texts) > MAX_CONTENT:
            return BLOCKED_COMPLEX
        prose = _is_prose_path(tool_input)
        for text in texts:
            reason = _inspect_content(text, deadline, prose)
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
        if len(command) > MAX_COMMAND or command.count("$(") + command.count("`") > MAX_OPENERS:
            return BLOCKED_COMPLEX
        bases = _bases(_unify_newlines(command))
        # Unexpanded forms first, then substitution bodies, smallest first.
        for base in bases:
            for variant in (base, _normalize(base)):
                if time.monotonic() > deadline:
                    return BLOCKED_COMPLEX
                reason = _bash_reason(variant)
                if reason:
                    return reason
        bodies = [sorted(set(_substitutions(b)), key=len) for b in bases]
        if sum(2 * len(t) for ts in bodies for t in ts) > MAX_INSPECTED:
            return BLOCKED_COMPLEX
        for ts in bodies:
            for text in ts:
                for variant in (text, _normalize(text)):
                    if time.monotonic() > deadline:
                        return BLOCKED_COMPLEX
                    reason = _bash_reason(variant)
                    if reason:
                        return reason
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
