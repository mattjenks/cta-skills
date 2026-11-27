"""Data shapes for the weekly report. Plain dataclasses, JSON-serializable via dataclasses.asdict."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


@dataclass
class SkillUsage:
    skill: str
    plugin: str | None
    marketplace: str | None
    invocations: int | None
    sessions: int | None
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
        "tool_decision": [], "tool_result": [], "mcp_server_connection": [],
        "plugin_loaded": []})
    freshness: dict[str, str | None] = field(default_factory=lambda: {
        "prometheus": None, "loki": None, "drift": None, "backup": None})
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    skill: str
    signal: str
    fingerprint: str
    metric: str
    value: float
    threshold: float
    sessions: int
    evidence: list[str]
    panel: str


@dataclass
class RotItem:
    kind: Literal["broken", "stale", "permission"]
    location: str
    problem: str
    fix: str
    fingerprint: str = ""
    id: str = ""
    accept: bool = True
    repo: str = ""  # a GitHub `owner/name`, or "" when the issue has no known home


@dataclass
class Recommendation:
    id: str
    candidate: Candidate
    problem: str = ""
    why: str = ""
    change: str = ""
    measure: str = ""


@dataclass
class Followup:
    id: str
    skill: str
    metric: str
    before: float
    now: float | None
    moved: Literal["better", "worse", "flat", "no data"]
    reports_left: int


@dataclass
class Report:
    date: str
    status: Literal["green", "amber", "red"]
    headline: str
    top: list[SkillUsage]
    total_cost: float | None
    total_prev_cost: float | None
    recommendations: list[Recommendation]
    followups: list[Followup]
    builds: dict
    rot: dict[str, list[RotItem]]
    rot_totals: dict[str, int]
    health: dict[str, str | None]
    errors: list[str]
    links: dict[str, str]
