import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import gather
import learn_config
from gather import GatherError

END = date(2026, 11, 23)
ORG = "org-a"


def _cfg(tmp_path, owners=("Corp",)):
    return learn_config.LearnConfig(kb=tmp_path, organization_ids=(ORG,), exclude_owners=owners)


def _row(skill, org, value, **extra):
    return {"metric": {"skill_name": skill, "organization_id": org, **extra},
            "value": [0, str(value)]}


def _known(tmp_path, repo="Corp/market"):
    path = tmp_path / "known_marketplaces.json"
    path.write_text(json.dumps({"corp-market": {"source": {"repo": repo}}}))
    return path


def _install(monkeypatch, tmp_path, prom=None, loki=None, known=True):
    """prom(promql, at, is_prev) -> rows; loki(logql, start, end) -> rows."""
    if known:
        monkeypatch.setattr(gather, "KNOWN_MARKETPLACES", _known(tmp_path))
    else:
        monkeypatch.setattr(gather, "KNOWN_MARKETPLACES", tmp_path / "none.json")
    end_dt = gather.week_end(END)

    def fake_prom(url, promql, at):
        if callable(prom):
            return prom(promql, at, at < end_dt)
        return []

    def fake_loki(url, logql, start, end, limit=5000):
        if callable(loki):
            return loki(logql, start, end)
        return []

    monkeypatch.setattr(gather, "prom_query", fake_prom)
    monkeypatch.setattr(gather, "loki_query", fake_loki)


def _cost_prom(rows, prev_rows=()):
    def prom(promql, at, is_prev):
        if "cost_usage" not in promql or "timestamp" in promql:
            return []
        return list(prev_rows if is_prev else rows)
    return prom


def test_personal_filter_drops_other_orgs_and_owners(tmp_path, monkeypatch):
    rows = [
        _row("cta:kept", ORG, 2.0),
        _row("other:dropped-org", "org-b", 3.0),
        _row("corp:dropped-owner", ORG, 4.0),
    ]

    def loki(logql, start, end):
        if "plugin_loaded" in logql:
            return [{"event_name": "plugin_loaded", "organization_id": ORG,
                     "plugin_name": "corp", "marketplace_name": "corp-market"},
                    {"event_name": "plugin_loaded", "organization_id": ORG,
                     "plugin_name": "cta", "marketplace_name": "unknown-market"}]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom(rows), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    assert [s.skill for s in week.skills] == ["cta:kept"]
    blob = json.dumps(asdict(week), default=str)
    assert "dropped-org" not in blob and "dropped-owner" not in blob


def test_previous_week_values(tmp_path, monkeypatch):
    rows = [_row("cta:old", ORG, 2.0), _row("cta:new", ORG, 1.0)]
    prev = [_row("cta:old", ORG, 1.5)]
    _install(monkeypatch, tmp_path, prom=_cost_prom(rows, prev))
    week = gather.gather(_cfg(tmp_path), END)
    by = {s.skill: s for s in week.skills}
    assert by["cta:old"].cost_usd == 2.0
    assert by["cta:old"].prev_cost_usd == 1.5
    assert by["cta:new"].prev_cost_usd is None


def test_prometheus_down_is_missing_not_zero(tmp_path, monkeypatch):
    def prom(promql, at, is_prev):
        raise GatherError("prometheus", "connection refused")

    _install(monkeypatch, tmp_path, prom=prom)
    week = gather.gather(_cfg(tmp_path), END)
    assert week.skills == []
    assert "prometheus" in week.missing
    assert len([e for e in week.errors if "prometheus" in e]) == 1
    assert week.freshness["prometheus"] is None


def test_freshness_none_when_silent(tmp_path, monkeypatch):
    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]))
    week = gather.gather(_cfg(tmp_path), END)
    assert week.freshness["loki"] is None
    assert "loki" in week.missing
    assert "prometheus" not in week.missing


def test_episodes_keep_personal_skills_only(tmp_path, monkeypatch):
    def loki(logql, start, end):
        if "cta.skill_episode" in logql:
            return [{"event_name": "cta.skill_episode", "skill": "cta:kept", "outcome": "ok",
                     "duration_ms": "10", "ts": "1763900000000000000"},
                    {"event_name": "cta.skill_episode", "skill": "work:secret", "outcome": "ok",
                     "duration_ms": "10", "ts": "1763900000000000001"}]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    assert [e["skill"] for e in week.episodes] == ["cta:kept"]
    assert "work:secret" not in json.dumps(asdict(week), default=str)
    assert week.freshness["drift"] is not None


def test_work_events_dropped(tmp_path, monkeypatch):
    def loki(logql, start, end):
        if "tool_decision" in logql:
            return [{"event_name": "tool_decision", "organization_id": ORG, "tool_name": "Bash",
                     "ts": "1763900000000000000"},
                    {"event_name": "tool_decision", "organization_id": "org-b",
                     "tool_name": "work-tool", "ts": "1763900000000000001"},
                    {"event_name": "tool_decision", "tool_name": "no-org",
                     "ts": "1763900000000000002"}]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    assert [e["tool_name"] for e in week.events["tool_decision"]] == ["Bash"]
    assert set(week.events) == {"tool_decision", "mcp_server_connection", "plugin_loaded"}
    assert "work-tool" not in json.dumps(asdict(week), default=str)
    assert week.freshness["loki"] is not None


def test_hostile_names_become_inert(tmp_path, monkeypatch):
    hostile = "<script>x</script>|\nrow"
    rows = [_row(hostile, ORG, 1.0)]

    def loki(logql, start, end):
        if "mcp_server_connection" in logql:
            return [{"event_name": "mcp_server_connection", "organization_id": ORG,
                     "server_name": hostile, "ts": "1763900000000000000"}]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom(rows), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    blob = json.dumps(asdict(week), default=str)
    assert "<script>" not in blob and "|" not in blob.replace("\\|", "")
    assert "\\n" not in blob


def test_window_is_seven_days_ending_end(tmp_path, monkeypatch):
    seen = []

    def loki(logql, start, end_):
        seen.append((start, end_))
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    assert week.end == END and week.start == END - timedelta(days=7)
    end_dt = gather.week_end(END)
    assert isinstance(end_dt, datetime) and end_dt.tzinfo is not None
    assert (end_dt - timedelta(days=7), end_dt) in seen


def test_personal_helper(tmp_path):
    cfg = _cfg(tmp_path)
    assert gather.personal(cfg, ORG, None) is True
    assert gather.personal(cfg, ORG, "Other/x") is True
    assert gather.personal(cfg, ORG, "Corp/x") is False
    assert gather.personal(cfg, "org-b", None) is False
    assert gather.personal(cfg, None, None) is False
