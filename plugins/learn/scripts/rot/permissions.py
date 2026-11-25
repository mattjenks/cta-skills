"""Permission prompts that a rule should settle, and rules that keep blocking."""

from __future__ import annotations

import re
from collections import Counter

from model import RotItem
from rot import _common

KIND = "permission"
BLOCKED_MIN = 3
PROMPTED_MIN = 5
SAFE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
COMMAND_TOOLS = {"Bash"}  # a bare rule for these would allow every command
PROMPTED_SOURCES = {"user_temporary", "user_permanent"}


def _rule(tool: str, word: str | None) -> str | None:
    """Tool name plus a first word, both plain words (S2); else None and the item is dropped."""
    if not SAFE.fullmatch(tool) or (word is not None and not SAFE.fullmatch(word)):
        return None
    if word is None:
        return None if tool in COMMAND_TOOLS else tool
    return f"{tool}({word}:*)"


def check(week, cfg) -> list[RotItem]:
    blocked: Counter[tuple[str, str | None]] = Counter()
    prompted: Counter[tuple[str, str | None]] = Counter()
    for event in week.events.get("tool_decision", []):
        key = (str(event.get("tool_name", "")), event.get("command_word"))
        decision, source = event.get("decision"), event.get("source")
        if decision == "reject" and source == "config":
            blocked[key] += 1
        elif decision == "accept" and source in PROMPTED_SOURCES:
            prompted[key] += 1
    rows: list[tuple[int, str, RotItem]] = []
    for counter, minimum in ((blocked, BLOCKED_MIN), (prompted, PROMPTED_MIN)):
        for (tool, word), n in counter.items():
            rule = _rule(tool, word)
            if rule is None or n < minimum:
                continue
            if counter is blocked:
                made = _common.item("permission", rule, f"blocked by a rule {n} times",
                                    f"review the deny rule for {rule} if it should be allowed")
            else:
                made = _common.item("permission", rule, f"prompted {n} times",
                                    f"add an allow rule: {rule}")
            rows.append((-n, rule, made))
    return [row[2] for row in sorted(rows, key=lambda r: r[:2])]
