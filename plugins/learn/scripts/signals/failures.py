"""Failures: the share of a skill's tool calls that failed."""

from __future__ import annotations

from model import Candidate, SkillUsage, Week

NAME = "failures"
PANEL = "Tool failures"
THRESHOLD = 0.10


def _outcome(event: dict) -> bool | None:
    value = str(event.get("success", "")).strip().lower()
    return {"true": True, "false": False}.get(value)


def evaluate(week: Week, skill: SkillUsage) -> Candidate | None:
    if "loki" in week.missing:
        return None
    known = [_outcome(e) for e in week.events.get("tool_result", [])
             if e.get("skill_name") == skill.skill]
    known = [k for k in known if k is not None]
    if not known:
        return None
    failed = known.count(False)
    share = failed / len(known)
    if share < THRESHOLD:
        return None
    return Candidate(
        skill=skill.skill, signal=NAME, fingerprint=f"{skill.skill}|{NAME}",
        metric="tool_failure_share", value=share, threshold=THRESHOLD, sessions=skill.sessions,
        evidence=[f"{failed} of {len(known)} tool calls failed ({share * 100:.1f}%)",
                  f"threshold {THRESHOLD * 100:.1f}%", f"sessions {skill.sessions}",
                  "tool calls attributed by session"],
        panel=PANEL)
