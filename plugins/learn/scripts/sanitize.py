"""Make external strings inert before they enter a report: names, paths, lines, markdown, HTML."""

from __future__ import annotations

import html as _html
import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_UNSAFE_NAME = re.compile(r"[^\w:.\-/ @+]")
_SPACE = re.compile(r"\s+")


def _text(s: object) -> str:
    return "" if s is None else str(s)


def name(s: object) -> str:
    """A skill, plugin or server name: word characters and `:.-/ @+` only, at most 80 characters."""
    out = _UNSAFE_NAME.sub("_", _CONTROL.sub("_", _text(s)))
    return out.strip()[:80]


def path(s: object) -> str:
    """A filesystem path: no markup, pipes, backticks, brackets or control characters."""
    out = _CONTROL.sub("_", _text(s))
    return re.sub(r"[<>|`\[\]()*]", "_", out)[:300]


def line(s: object) -> str:
    """One line of free text, whitespace collapsed, at most 200 characters."""
    out = _CONTROL.sub(" ", _text(s))
    return _SPACE.sub(" ", out).strip()[:200]


def md(s: object) -> str:
    """Text safe inside a markdown table cell or issue title."""
    out = line(s)
    out = out.replace("\\", "\\\\")
    out = re.sub(r"([|`\[\]*_~#])", r"\\\1", out)
    return out.replace("<", "&lt;").replace(">", "&gt;")


def html(s: object) -> str:
    """Text safe in HTML element content or a quoted attribute."""
    return _html.escape(_CONTROL.sub(" ", _text(s)), quote=True)
