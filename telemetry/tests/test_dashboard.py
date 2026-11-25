"""Static checks on the provisioned Grafana dashboard (no live stack needed)."""
import json
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "grafana" / "dashboards" / "cta-skills.json"


def _panels() -> dict:
    return {p["title"]: p for p in json.loads(DASHBOARD.read_text())["panels"]}


def test_build_panels_present():
    panels = _panels()
    for title in ("Builds per week", "Fix rounds per build"):
        assert title in panels, title
        exprs = [t["expr"] for t in panels[title]["targets"]]
        assert exprs and all("cta.build" in e for e in exprs), exprs
        assert all(t["datasource"]["uid"] == "cta-loki" for t in panels[title]["targets"])
    assert "by (size)" in panels["Builds per week"]["targets"][0]["expr"]
    fix = " ".join(t["expr"] for t in panels["Fix rounds per build"]["targets"])
    assert "fix_rounds" in fix and "avg_over_time" in fix and "max_over_time" in fix


def test_panel_ids_unique():
    ids = [p["id"] for p in json.loads(DASHBOARD.read_text())["panels"]]
    assert len(ids) == len(set(ids))


def test_learn_decisions_panel_present():
    panels = _panels()
    title = "Learn decisions by type (range)"
    assert title in panels, title
    targets = panels[title]["targets"]
    assert targets and all("cta.learn.decision" in t["expr"] for t in targets)
    assert all("by (decision)" in t["expr"] for t in targets)
    assert all(t["datasource"]["uid"] == "cta-loki" for t in targets)
