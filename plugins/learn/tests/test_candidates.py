import importlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import candidates
import learn_config
import signals
from model import Candidate, SkillUsage, Week

CFG = learn_config.LearnConfig(kb=None)


def _skill(name, cost=1.0, inv=5, sessions=5, prev_cost=None, **kw):
    return SkillUsage(skill=name, plugin=None, marketplace=None, invocations=inv,
                      sessions=sessions, input_tokens=0, output_tokens=0, cost_usd=cost,
                      prev_cost_usd=prev_cost, prev_invocations=None, **kw)


def _week(skills=(), episodes=(), events=None, missing=()):
    week = Week(start=date(2026, 11, 16), end=date(2026, 11, 23), skills=list(skills),
                episodes=list(episodes), missing=list(missing))
    if events:
        week.events.update(events)
    return week


def _eps(skill, drifted, total):
    return ([{"skill": skill, "signals": "interruption", "outcome": "drifted"}] * drifted
            + [{"skill": skill, "signals": "none", "outcome": "success"}] * (total - drifted))


def _decisions(tmp_path, *rows):
    path = tmp_path / "decisions.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


# --- top_skills -----------------------------------------------------------------

def test_top_skills_order_and_cap():
    skills = [_skill(f"s{i}", cost=float(i)) for i in range(1, 6)]
    skills += [_skill("tie-low", cost=9.0, inv=1), _skill("tie-high", cost=9.0, inv=7)]
    top = candidates.top_skills(_week(skills))
    assert [s.skill for s in top] == ["tie-high", "tie-low", "s5", "s4", "s3"]


def test_top_skills_name_breaks_full_tie():
    top = candidates.top_skills(_week([_skill("b"), _skill("a")]))
    assert [s.skill for s in top] == ["a", "b"]


def test_fewer_than_five_skills():
    assert len(candidates.top_skills(_week([_skill("a"), _skill("b")]))) == 2


# --- select ---------------------------------------------------------------------

def test_two_sessions_not_backed(tmp_path):
    week = _week([_skill("cta:x", sessions=2)], _eps("cta:x", 8, 10))
    chosen, overflow, errors = candidates.select(week, CFG, tmp_path / "none.jsonl")
    assert (chosen, overflow, errors) == ([], [], [])


def test_backed_drift_is_chosen(tmp_path):
    week = _week([_skill("cta:x", sessions=3)], _eps("cta:x", 8, 10))
    chosen, _, _ = candidates.select(week, CFG, tmp_path / "none.jsonl")
    assert [(c.skill, c.signal, c.fingerprint) for c in chosen] == [("cta:x", "drift", "cta:x|drift")]
    assert chosen[0].sessions == 3 and chosen[0].value == 0.8


def test_below_threshold_not_chosen(tmp_path):
    week = _week([_skill("cta:x")], _eps("cta:x", 1, 10))
    assert candidates.select(week, CFG, tmp_path / "none.jsonl")[0] == []


def test_rejected_fingerprint_suppressed(tmp_path):
    week = _week([_skill("cta:x")], _eps("cta:x", 8, 10))
    path = _decisions(tmp_path, {"fingerprint": "cta:x|drift", "decision": "reject"})
    assert candidates.suppressed(path) == {"cta:x|drift"}
    assert candidates.select(week, CFG, path)[0] == []
    path = _decisions(tmp_path, {"fingerprint": "cta:x|drift", "decision": "defer"})
    assert candidates.suppressed(path) == set()
    assert len(candidates.select(week, CFG, path)[0]) == 1


def test_suppressed_tolerates_missing_and_bad_lines(tmp_path):
    assert candidates.suppressed(tmp_path / "absent.jsonl") == set()
    path = tmp_path / "decisions.jsonl"
    path.write_text('not json\n[1]\n{"fingerprint": "a|b", "decision": "reject"}\n')
    assert candidates.suppressed(path) == {"a|b"}


def test_cap_five_and_overflow(tmp_path):
    skills = [_skill(f"cta:s{i}") for i in range(5)]  # only the top five skills are considered
    episodes = []
    for i, s in enumerate(skills):
        episodes += _eps(s.skill, 4 + i, 10)  # 0.4 .. 0.8
    # cost growth on three of them adds more qualifying candidates (8 total)
    for s in skills[:3]:
        s.prev_cost_usd, s.cost_usd = 1.0, 2.0 + 0.5 * skills.index(s)
    chosen, overflow, errors = candidates.select(_week(skills, episodes), CFG, tmp_path / "n")
    assert (len(chosen), len(overflow), errors) == (5, 3, [])
    ratios = [c.value / c.threshold for c in chosen + overflow]
    assert ratios == sorted(ratios, reverse=True)


def test_candidates_only_for_top_five_skills(tmp_path):
    skills = [_skill(f"cta:s{i}", cost=10.0 - i) for i in range(6)]
    episodes = _eps("cta:s5", 9, 10)  # sixth by cost
    assert candidates.select(_week(skills, episodes), CFG, tmp_path / "n")[0] == []


# --- signals --------------------------------------------------------------------

def test_failures_signal():
    ev = [{"skill_name": "cta:x", "success": "false"}] * 2 + [{"skill_name": "cta:x", "success": "true"}] * 8
    week = _week([_skill("cta:x")], events={"tool_decision": ev})
    from signals import failures
    cand = failures.evaluate(week, week.skills[0])
    assert cand and cand.value == 0.2 and cand.threshold == 0.10 and cand.signal == "failures"


def test_cost_growth_signal():
    from signals import cost_growth
    s = _skill("cta:x", cost=3.0, prev_cost=1.0)
    cand = cost_growth.evaluate(_week([s]), s)
    assert cand and cand.value == 3.0 and cand.threshold == 1.5
    small = _skill("cta:x", cost=0.9, prev_cost=0.1)
    assert cost_growth.evaluate(_week([small]), small) is None
    assert cost_growth.evaluate(_week([_skill("cta:x", cost=3.0, prev_cost=None)]),
                                _skill("cta:x", cost=3.0, prev_cost=None)) is None


def test_missing_source_is_not_a_measured_zero():
    from signals import cost_growth, drift, failures
    s = _skill("cta:x", cost=3.0, prev_cost=0.0)
    assert cost_growth.evaluate(_week([s], missing=["prometheus"]), s) is None
    assert cost_growth.evaluate(_week([s]), s) is None  # prev of zero: no ratio, not infinity
    s2 = _skill("cta:x")
    ev = [{"skill_name": "cta:x", "success": "false"}]
    assert failures.evaluate(_week([s2], events={"tool_decision": ev}, missing=["loki"]), s2) is None
    assert drift.evaluate(_week([s2], _eps("cta:x", 9, 10), missing=["loki"]), s2) is None


def test_no_events_or_episodes_gives_none():
    from signals import drift, failures
    s = _skill("cta:x")
    assert drift.evaluate(_week([s]), s) is None
    assert failures.evaluate(_week([s]), s) is None


def test_evidence_lines_match_template(tmp_path):
    hostile = "cta:<script>|x\n"
    skills = [_skill(hostile, cost=5.0, prev_cost=1.0)]
    episodes = [{"skill": hostile, "signals": "<b>evil</b>", "outcome": "drifted\nx"}] * 4
    ev = [{"skill_name": hostile, "success": "false", "tool_name": "<img>"}] * 3
    week = _week(skills, episodes, events={"tool_decision": ev})
    chosen, overflow, _ = candidates.select(week, CFG, tmp_path / "n")
    assert {c.signal for c in chosen + overflow} == {"drift", "failures", "cost_growth"}
    template = re.compile(r"(\d+ of \d+ (episodes|tool calls) [a-z ]+ \([\d.]+%\))"
                          r"|(threshold [\d.$x%]+)|(cost \$[\d.]+ against \$[\d.]+ the week before)"
                          r"|(sessions \d+)")
    for c in chosen + overflow:
        assert c.evidence
        for line in c.evidence:
            assert template.fullmatch(line), line
            assert not re.search(r"[<>|\n`]", line)


# --- discovery ------------------------------------------------------------------

def test_discover_finds_shipped_modules():
    mods, errors = signals.discover()
    assert [m.NAME for m in mods] == ["cost_growth", "drift", "failures"]
    assert errors == []


def _extend(monkeypatch, tmp_path):
    monkeypatch.setattr(signals, "__path__", [*signals.__path__, str(tmp_path)])
    for name in ("extra", "broken"):
        monkeypatch.delitem(sys.modules, f"signals.{name}", raising=False)
    importlib.invalidate_caches()


def test_new_signal_module_discovered(tmp_path, monkeypatch):
    (tmp_path / "extra.py").write_text(
        "from model import Candidate\n"
        "NAME = 'extra'\nPANEL = 'Extra panel'\n"
        "def evaluate(week, skill):\n"
        "    return Candidate(skill.skill, NAME, skill.skill + '|' + NAME, 'm', 9.0, 1.0,\n"
        "                     skill.sessions, ['9 of 9 episodes x (100.0%)'], PANEL)\n")
    _extend(monkeypatch, tmp_path)
    mods, errors = signals.discover()
    assert "extra" in [m.NAME for m in mods] and errors == []
    week = _week([_skill("cta:x")])
    chosen, overflow, _ = candidates.select(week, CFG, tmp_path / "n")
    assert [c.signal for c in chosen + overflow] == ["extra"]


def test_bad_module_reported_not_fatal(tmp_path, monkeypatch):
    (tmp_path / "broken.py").write_text("NAME = 'broken'\n")  # no PANEL, no evaluate
    _extend(monkeypatch, tmp_path)
    mods, errors = signals.discover()
    assert "broken" not in [m.NAME for m in mods]
    assert len(errors) == 1 and "broken" in errors[0]
    assert len(mods) == 3


def test_raising_signal_is_reported_not_fatal(tmp_path, monkeypatch):
    (tmp_path / "broken.py").write_text(
        "NAME = 'broken'\nPANEL = 'p'\n"
        "def evaluate(week, skill):\n    raise RuntimeError('boom')\n")
    _extend(monkeypatch, tmp_path)
    week = _week([_skill("cta:x")], _eps("cta:x", 9, 10))
    chosen, _, errors = candidates.select(week, CFG, tmp_path / "n")
    assert [c.signal for c in chosen] == ["drift"]
    assert any("broken" in e for e in errors)
