import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import gather
import learn_config
from gather import GatherError

END = date(2026, 11, 23)
ORG = "org-a"
WORK = "org-work"


def _cfg(tmp_path, owners=("Corp",)):
    return learn_config.LearnConfig(kb=tmp_path, exclude_organization_ids=(WORK,), exclude_owners=owners)


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
        _row("other:dropped-org", WORK, 3.0),
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
                    {"event_name": "tool_decision", "organization_id": WORK,
                     "tool_name": "work-tool", "ts": "1763900000000000001"},
                    {"event_name": "tool_decision", "tool_name": "no-org",
                     "ts": "1763900000000000002"}]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    assert [e["tool_name"] for e in week.events["tool_decision"]] == ["Bash", "no-org"]
    assert set(week.events) == {"tool_decision", "tool_result", "mcp_server_connection",
                                "plugin_loaded"}
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
    assert gather.personal(cfg, WORK, None) is False
    assert gather.personal(cfg, "org-b", None) is True
    assert gather.personal(cfg, None, None) is True
    assert gather.personal(cfg, None, "Corp/x") is False


def test_empty_config_keeps_every_org(tmp_path, monkeypatch):
    rows = [_row("cta:a", ORG, 2.0), _row("cta:b", "org-b", 1.0), _row("cta:c", "", 1.0)]

    def loki(logql, start, end):
        if "tool_decision" in logql:
            return [{"event_name": "tool_decision", "organization_id": o, "tool_name": n,
                     "ts": "1763900000000000000"}
                    for o, n in ((ORG, "A"), ("org-b", "B"), (None, "C"))]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom(rows), loki=loki)
    cfg = learn_config.LearnConfig(kb=tmp_path)
    assert gather.personal(cfg, "anything", "Corp/x") is True
    week = gather.gather(cfg, END)
    assert {s.skill for s in week.skills} == {"cta:a", "cta:b", "cta:c"}
    assert [e["tool_name"] for e in week.events["tool_decision"]] == ["A", "B", "C"]


def test_events_carry_no_identity_fields(tmp_path, monkeypatch):
    def loki(logql, start, end):
        row = {"organization_id": ORG, "user_email": "a@example.test", "user_id": "u1",
               "user_account_uuid": "x", "prompt": "secret text", "line": "raw body",
               "ts": "1763900000000000000"}
        if "tool_decision" in logql:
            return [{**row, "event_name": "tool_decision", "tool_name": "Bash"}]
        if "cta.skill_episode" in logql:
            return [{**row, "event_name": "cta.skill_episode", "skill": "cta:kept"}]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    blob = json.dumps(asdict(week), default=str)
    for leaked in ("a@example.test", "u1", "secret text", "raw body", "user_email"):
        assert leaked not in blob
    assert week.events["tool_decision"][0]["tool_name"] == "Bash"


def test_cost_and_token_queries_mirror_dashboard_panels(tmp_path, monkeypatch):
    calls = []

    def prom(promql, at, is_prev):
        calls.append((promql, at))
        return []

    _install(monkeypatch, tmp_path, prom=prom)
    gather.gather(_cfg(tmp_path), END)
    end_dt = gather.week_end(END)
    prev_dt = end_dt - timedelta(days=7)
    for metric in ("claude_code_cost_usage_USD_total", "claude_code_token_usage_tokens_total"):
        qs = [(q, at) for q, at in calls if metric in q and "timestamp" not in q]
        assert qs, metric
        for q, _ in qs:
            assert f"max_over_time({metric}{{" in q and "[7d]" in q
            assert "increase(" not in q
        assert {at for _, at in qs} >= {end_dt}
    cost_ats = {at for q, at in calls if "cost_usage" in q and "timestamp" not in q}
    assert cost_ats == {end_dt, prev_dt}


def _activated(skill, session, ts="1763900000000000000", org=ORG):
    return {"event_name": "skill_activated", "organization_id": org, "skill_name": skill,
            "session_id": session, "ts": ts}


def test_invocations_sessions_and_previous_week(tmp_path, monkeypatch):
    end_dt = gather.week_end(END)

    def loki(logql, start, end):
        if "skill_activated" not in logql:
            return []
        if end <= end_dt - timedelta(days=7):
            return [_activated("cta:kept", "s0")]
        return [_activated("cta:kept", "s1"), _activated("cta:kept", "s1"),
                _activated("cta:kept", "s2"), _activated("work:other", "s3"),
                _activated("cta:kept", "s9", org=WORK)]

    rows = [_row("cta:kept", ORG, 2.0), _row("cta:quiet", ORG, 1.0)]
    _install(monkeypatch, tmp_path, prom=_cost_prom(rows), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    by = {s.skill: s for s in week.skills}
    assert (by["cta:kept"].invocations, by["cta:kept"].sessions) == (3, 2)
    assert by["cta:kept"].prev_invocations == 1
    assert by["cta:quiet"].invocations == 0
    assert by["cta:quiet"].prev_invocations == 0


def test_prev_invocations_none_when_prior_week_has_no_rows(tmp_path, monkeypatch):
    end_dt = gather.week_end(END)

    def loki(logql, start, end):
        if "skill_activated" in logql and end > end_dt - timedelta(days=7):
            return [_activated("cta:kept", "s1")]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 2.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    assert week.skills[0].invocations == 1
    assert week.skills[0].prev_invocations is None


def _result(session, ts, success="false", org=ORG, **extra):
    return {"event_name": "tool_result", "organization_id": org, "session_id": session,
            "success": success, "tool_name": "Bash", "ts": str(ts), **extra}


def _attrib_loki(activations, results):
    def loki(logql, start, end):
        if 'event_name="skill_activated"' in logql and end > gather.week_end(END) - timedelta(days=1):
            return activations
        if 'event_name="tool_result"' in logql:
            return results
        return []
    return loki


def _by_ts(week):
    return {int(r["ts"]): r.get("skill_name") for r in week.events["tool_result"]}


def test_tool_results_attributed_to_latest_activation_in_session(tmp_path, monkeypatch):
    acts = [_activated("cta:first", "s1", ts=100), _activated("cta:second", "s1", ts=200)]
    results = [_result("s1", 150), _result("s1", 200), _result("s1", 250)]
    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:first", ORG, 1.0)]),
             loki=_attrib_loki(acts, results))
    week = gather.gather(_cfg(tmp_path), END)
    assert _by_ts(week) == {150: "cta:first", 200: "cta:second", 250: "cta:second"}


def test_tool_result_before_any_activation_is_unattributed(tmp_path, monkeypatch):
    acts = [_activated("cta:first", "s1", ts=100)]
    results = [_result("s1", 50, skill_name="cta:first")]
    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:first", ORG, 1.0)]),
             loki=_attrib_loki(acts, results))
    week = gather.gather(_cfg(tmp_path), END)
    assert _by_ts(week) == {50: None}


def test_other_sessions_activation_is_never_used(tmp_path, monkeypatch):
    acts = [_activated("cta:first", "s1", ts=100)]
    results = [_result("s2", 150), _result("s1", 150), _result(None, 150)]
    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:first", ORG, 1.0)]),
             loki=_attrib_loki(acts, results))
    week = gather.gather(_cfg(tmp_path), END)
    got = {r.get("session_id") or None: r.get("skill_name") for r in week.events["tool_result"]}
    assert got == {"s2": None, "s1": "cta:first", None: None}


def test_excluded_org_activation_is_not_used_for_attribution(tmp_path, monkeypatch):
    acts = [_activated("work:x", "s1", ts=100, org=WORK)]
    results = [_result("s1", 150)]
    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:first", ORG, 1.0)]),
             loki=_attrib_loki(acts, results))
    week = gather.gather(_cfg(tmp_path), END)
    assert _by_ts(week) == {150: None}
    assert "work:x" not in json.dumps(asdict(week), default=str)


def test_tool_result_events_fetched_filtered_and_stripped(tmp_path, monkeypatch):
    def loki(logql, start, end):
        if 'event_name="tool_result"' in logql:
            return [{"event_name": "tool_result", "organization_id": ORG, "session_id": "s1",
                     "success": "false", "tool_name": "Bash", "tool_parameters": "PARAMTEXT",
                     "tool_input": "CMDTEXT", "user_email": "a@example.test",
                     "ts": "1763900000000000000"},
                    {"event_name": "tool_result", "organization_id": WORK,
                     "skill_name": "work:x", "success": "false", "ts": "1763900000000000001"}]
        if 'event_name="skill_activated"' in logql:
            return [_activated("cta:kept", "s1", ts="1763899999000000000")]
        return []

    _install(monkeypatch, tmp_path, prom=_cost_prom([_row("cta:kept", ORG, 1.0)]), loki=loki)
    week = gather.gather(_cfg(tmp_path), END)
    rows = week.events["tool_result"]
    assert len(rows) == 1
    assert rows[0]["skill_name"] == "cta:kept" and rows[0]["success"] == "false"
    blob = json.dumps(rows)
    for leaked in ("PARAMTEXT", "CMDTEXT", "a@example.test", "tool_parameters", "tool_input", "work:x"):
        assert leaked not in blob
