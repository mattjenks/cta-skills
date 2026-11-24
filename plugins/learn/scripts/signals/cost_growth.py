"""Cost growth: this week's cost against the week before."""

from __future__ import annotations

from model import Candidate, SkillUsage, Week

NAME = "cost_growth"
PANEL = "Cost by skill"
THRESHOLD = 1.5
MIN_COST_USD = 1.00


def evaluate(week: Week, skill: SkillUsage) -> Candidate | None:
    if "prometheus" in week.missing or not skill.prev_cost_usd or skill.prev_cost_usd <= 0:
        return None  # no earlier week to compare: not a ratio, and never infinity
    if skill.cost_usd < MIN_COST_USD:
        return None
    ratio = skill.cost_usd / skill.prev_cost_usd
    if ratio < THRESHOLD:
        return None
    return Candidate(
        skill=skill.skill, signal=NAME, fingerprint=f"{skill.skill}|{NAME}",
        metric="cost_ratio", value=ratio, threshold=THRESHOLD, sessions=skill.sessions,
        evidence=[f"cost ${skill.cost_usd:.2f} against ${skill.prev_cost_usd:.2f} the week before",
                  f"threshold {THRESHOLD:.1f}x", f"sessions {skill.sessions}"],
        panel=PANEL)
