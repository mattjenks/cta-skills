"""Make external strings inert before they enter a report: names, paths, lines, markdown, HTML."""

from __future__ import annotations

import hashlib
import html as _html
import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_NAME = re.compile(r"[A-Za-z0-9:_.@/-]{1,100}")
_LINE_STRIP = re.compile(r"[<>\[\]()`!]")
_SPACE = re.compile(r"\s+")


def _text(s: object) -> str:
    return "" if s is None else str(s)


def name(s: object) -> str:
    """A skill, plugin or server name: `^[A-Za-z0-9:_.@/-]{1,100}$`, else `invalid-name-<sha256[:8]>`."""
    text = _text(s)
    if not text:
        return ""
    if _NAME.fullmatch(text):
        return text
    return "invalid-name-" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]


def path(s: object) -> str:
    """A filesystem path: no markup, pipes, backticks, brackets or control characters, at most 200."""
    out = _CONTROL.sub("", _text(s))
    return re.sub(r"[<>|`\[\]()*]", "_", out)[:200]


def line(s: object, keep: str = "") -> str:
    """One line of free text: single line, `<>[]()` backticks and `!` removed, at most 160 characters.

    `keep` names characters of that set to leave in (a rule such as `Bash(git:*)`)."""
    strip = _LINE_STRIP if not keep else re.compile(
        "[" + "".join(c for c in "<>[]()`!" if c not in keep).replace("[", r"\[").replace("]", r"\]") + "]")
    out = strip.sub("", _CONTROL.sub(" ", _text(s)))
    return _SPACE.sub(" ", out).strip()[:160]


def md(s: object) -> str:
    """Text safe inside a markdown table cell or issue title."""
    out = line(s)
    out = out.replace("\\", "\\\\")
    out = re.sub(r"([|`\[\]*_~#])", r"\\\1", out)
    return out.replace("<", "&lt;").replace(">", "&gt;")


def html(s: object) -> str:
    """Text safe in HTML element content or a quoted attribute."""
    return _html.escape(_CONTROL.sub(" ", _text(s)), quote=True)
