"""Drift: the share of a skill's episodes that carried any drift signal."""

from __future__ import annotations

from model import Candidate, SkillUsage, Week

NAME = "drift"
PANEL = "Skill drift"
THRESHOLD = 0.30


def evaluate(week: Week, skill: SkillUsage) -> Candidate | None:
    if "loki" in week.missing:
        return None
    eps = [e for e in week.episodes if e.get("skill") == skill.skill]
    if not eps:
        return None
    hit = sum(1 for e in eps if str(e.get("signals", "none")).strip() not in ("", "none"))
    share = hit / len(eps)
    if share < THRESHOLD:
        return None
    return Candidate(
        skill=skill.skill, signal=NAME, fingerprint=f"{skill.skill}|{NAME}",
        metric="episode_drift_share", value=share, threshold=THRESHOLD, sessions=skill.sessions,
        evidence=[f"{hit} of {len(eps)} episodes showed a drift signal ({share * 100:.1f}%)",
                  f"threshold {THRESHOLD * 100:.1f}%", f"sessions {skill.sessions}"],
        panel=PANEL)
