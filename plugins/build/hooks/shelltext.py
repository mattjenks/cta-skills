"""Shell-text helpers shared by the build hooks. Stdlib only.

`unify_newlines`, `normalize`, `substitutions` and `bases` are adapted from this
repository's plugins/core/hooks/secrets_guard.py (plugins cannot import each
other, so the approach is copied). `lex` is a small quote-aware command lexer
used to find `git` invocations.
"""

from __future__ import annotations

OPERATOR_CHARS = ";&|<>"


def unify_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize(command: str) -> str:
    """Fold quoting and whitespace so split-quote spellings match."""
    return " ".join(command.replace("'", "").replace('"', "").split())


def bases(command: str) -> list[str]:
    """Backslash as a path separator, and backslash deleted (`sec\\urity` reads as `security`)."""
    return [command.replace("\\", "/"), command.replace("\\", "")]


def substitutions(text: str) -> list[str]:
    """Body of every $(...) and backtick span, nested ones included (one linear pass)."""
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


def variants(command: str) -> list[str]:
    """Every spelling of the command worth matching: raw, quote-folded, and each
    substitution body in both forms. Smallest substitution bodies last."""
    out: list[str] = []
    seen: set[str] = set()
    base_list = bases(unify_newlines(command))
    texts = list(base_list)
    for b in base_list:
        texts += sorted(set(substitutions(b)), key=len)
    for t in texts:
        for v in (t, normalize(t)):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


class LexError(ValueError):
    """Unbalanced quote or substitution."""


def _skip_group(text: str, i: int, open_c: str, close_c: str) -> int:
    """Index just past the group opened at text[i-1]; nesting counted."""
    depth = 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise LexError("unbalanced group")


def lex(text: str) -> list[tuple[str, str]]:
    """Split a command into ("word", value) and ("op", value) items.

    Quotes and backslashes are resolved. A `$(...)` or backtick span stays inside
    its word. Newlines are `;`. Raises LexError on an unbalanced quote or span.
    """
    items: list[tuple[str, str]] = []
    cur: list[str] = []
    has = False
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal cur, has
        if has:
            items.append(("word", "".join(cur)))
        cur, has = [], False

    while i < n:
        c = text[i]
        if c in " \t":
            flush()
        elif c == "\n":
            flush()
            items.append(("op", ";"))
        elif c == "\\":
            if i + 1 < n and text[i + 1] != "\n":
                cur.append(text[i + 1])
                has = True
            i += 1
        elif c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                raise LexError("unterminated quote")
            cur.append(text[i + 1:end])
            has = True
            i = end
        elif c == '"':
            j = i + 1
            while True:
                if j >= n:
                    raise LexError("unterminated quote")
                d = text[j]
                if d == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    cur.append(nxt if nxt in '"\\$`' else "\\" + nxt)
                    j += 2
                elif d == "$" and text.startswith("$(", j):
                    end = _skip_group(text, j + 2, "(", ")")
                    cur.append(text[j:end])
                    j = end
                elif d == "`":
                    end = text.find("`", j + 1)
                    if end < 0:
                        raise LexError("unterminated substitution")
                    cur.append(text[j:end + 1])
                    j = end + 1
                elif d == '"':
                    break
                else:
                    cur.append(d)
                    j += 1
            has = True
            i = j
        elif c == "$" and text.startswith("$(", i):
            end = _skip_group(text, i + 2, "(", ")")
            cur.append(text[i:end])
            has = True
            i = end - 1
        elif c == "`":
            end = text.find("`", i + 1)
            if end < 0:
                raise LexError("unterminated substitution")
            cur.append(text[i:end + 1])
            has = True
            i = end
        elif c == "#" and not has:
            end = text.find("\n", i)
            i = n if end < 0 else end - 1
        elif c in "()":
            flush()
            items.append(("op", c))
        elif c in OPERATOR_CHARS:
            flush()
            j = i
            while j < n and text[j] in OPERATOR_CHARS:
                j += 1
            items.append(("op", text[i:j]))
            i = j - 1
        else:
            cur.append(c)
            has = True
        i += 1
    flush()
    return items
