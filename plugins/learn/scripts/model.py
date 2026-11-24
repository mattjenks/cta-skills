"""Data shapes for the weekly report. Plain dataclasses, JSON-serializable via dataclasses.asdict."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SkillUsage:
    skill: str
    plugin: str | None
    marketplace: str | None
    invocations: int
    sessions: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    prev_cost_usd: float | None
    prev_invocations: int | None


@dataclass
class Week:
    start: date
    end: date
    skills: list[SkillUsage] = field(default_factory=list)
    episodes: list[dict] = field(default_factory=list)
    events: dict[str, list[dict]] = field(default_factory=lambda: {
        "tool_decision": [], "mcp_server_connection": [], "plugin_loaded": []})
    freshness: dict[str, str | None] = field(default_factory=lambda: {
        "prometheus": None, "loki": None, "drift": None, "backup": None})
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
