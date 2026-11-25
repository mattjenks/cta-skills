#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Pick the recommendation candidates for the week: top skills, backed, not rejected, capped."""

from __future__ import annotations

import json
from pathlib import Path

import signals
from learn_config import LearnConfig
from model import Candidate, SkillUsage, Week

TOP_SKILLS = 5
MAX_CANDIDATES = 5


def top_skills(week: Week, n: int = TOP_SKILLS) -> list[SkillUsage]:
    return sorted(week.skills, key=lambda s: (-s.cost_usd, -(s.invocations or 0), s.skill))[:n]


def suppressed(decisions_path: Path) -> set[str]:
    """Fingerprints the owner rejected. A missing file or a bad line suppresses nothing."""
    out: set[str] = set()
    try:
        text = Path(decisions_path).read_text()
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("decision") == "reject" and isinstance(
                row.get("fingerprint"), str):
            out.add(row["fingerprint"])
    return out


def select(week: Week, cfg: LearnConfig, decisions_path: Path
           ) -> tuple[list[Candidate], list[Candidate], list[str]]:
    mods, errors = signals.discover()
    errors = list(errors)
    rejected = suppressed(decisions_path)
    found: list[Candidate] = []
    for skill in top_skills(week):
        if skill.sessions is None:
            continue  # no session count (Loki missing): nothing can be strongly backed
        for mod in mods:
            try:
                cand = mod.evaluate(week, skill)
            except Exception as exc:  # one failing signal must not hide the others
                err = f"signal {mod.NAME}: evaluate failed ({type(exc).__name__})"
                if err not in errors:
                    errors.append(err)
                continue
            if (cand is None or cand.sessions < cfg.min_sessions or cand.value < cand.threshold
                    or cand.fingerprint in rejected):
                continue
            found.append(cand)
    found.sort(key=lambda c: (-(c.value / c.threshold), c.skill, c.signal))
    return found[:MAX_CANDIDATES], found[MAX_CANDIDATES:], errors
