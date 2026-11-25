#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Build the weekly report and render it as markdown, HTML and JSON.

One `Report` object, three views. Every external string passes through one escape helper
(`_esc`); the only link is the Grafana URL from config. Missing data is printed as missing,
never as zero.
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import string
import sys
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import candidates
import gather
import learn_config
import rot
import sanitize
from model import (Candidate, Followup, Recommendation, Report, RotItem, SkillUsage, Week)

SECTIONS = ("Status", "Top skills", "Recommendations", "Follow-ups", "Builds", "Rot audit",
            "Telemetry health", "Run errors")
KINDS = ("broken", "stale", "permission")
KIND_TITLES = {"broken": "Broken skills and connectors", "stale": "Stale rules",
               "permission": "Permission problems"}
PROSE = ("problem", "why", "change", "measure")
INDEX_CAP = 52
NO_EXCLUDE_NOTE = "no excluded organizations configured"
TEMPLATE = Path(__file__).resolve().parent / "templates" / "report.html"
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPACE = re.compile(r"\s+")
_UNREACHABLE = re.compile(r"^(\w+) unreachable$")


# ---------------------------------------------------------------- escaping

@dataclass(frozen=True)
class Link:
    text: str
    url: str


def _clean(s: object) -> str:
    return _SPACE.sub(" ", _CONTROL.sub(" ", "" if s is None else str(s))).strip()


def _esc(s: object, fmt: str) -> str:
    """The one escape helper: text safe in a markdown cell or in HTML content and attributes."""
    text = _clean(s)
    if fmt == "html":
        return _html.escape(text, quote=True)
    text = text.replace("\\", "\\\\")
    text = re.sub(r"([|`\[\]*_~#])", r"\\\1", text)
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _href(url: str) -> str | None:
    if not re.fullmatch(r"https?://\S+", url or ""):
        return None
    return urllib.parse.quote(url, safe=":/?&=#%@+,;~!*'")


def _inline(cell: object, fmt: str) -> str:
    if isinstance(cell, Link):
        href = _href(cell.url)
        text = _esc(cell.text, fmt)
        if href is None:
            return text
        if fmt == "html":
            return f'<a href="{_esc(href, fmt)}">{text}</a>'
        return f"[{text}]({href})"
    return _esc(cell, fmt)


# ---------------------------------------------------------------- content

def _money(v: float) -> str:
    return f"${v:,.2f}"


def _change(now: float | None, prev: float | None) -> str:
    if now is None:
        return "no data"
    if prev is None or prev <= 0:
        return "new"
    return f"{(now - prev) / prev * 100:+.0f}%"


def _unreachable(r: Report) -> list[str]:
    out = []
    for err in r.errors:
        m = _UNREACHABLE.match(err)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _count(n: int | None) -> str:
    return "no data" if n is None else str(n)


def _more(r: Report, extra: int) -> Link:
    return Link(f"+{extra} more", r.links.get("grafana", ""))


def _panel_link(r: Report, cand: Candidate) -> Link | str:
    url = r.links.get(f"panel:{cand.panel}")
    return Link(cand.panel, url) if url else cand.panel


def _sections(r: Report) -> list[tuple[str, list[tuple]]]:
    """Blocks per section: ("p", text), ("li", cells), ("table", header, rows), ("h3", text)."""
    down = _unreachable(r)
    out: list[tuple[str, list[tuple]]] = []

    out.append(("Status", [("status", r.status, r.headline)]))

    top: list[tuple] = []
    if "prometheus" in down:
        top.append(("p", "No data (prometheus unreachable)"))
    elif not r.top:
        top.append(("p", "None."))
    else:
        rows = [[s.skill, _count(s.invocations), str(s.input_tokens), str(s.output_tokens),
                 _money(s.cost_usd), _change(s.cost_usd, s.prev_cost_usd)] for s in r.top]
        top.append(("table", ["Skill", "Invocations", "Input tokens", "Output tokens", "Cost",
                              "Change"], rows))
        if r.total_cost is not None:
            top.append(("p", f"Total, all personal skills: {_money(r.total_cost)} "
                             f"({_change(r.total_cost, r.total_prev_cost)})"))
        top.append(("p", Link("Usage in Grafana", r.links.get("grafana", ""))))
    out.append(("Top skills", top))

    recs: list[tuple] = []
    if r.recommendations:
        for rec in r.recommendations:
            c = rec.candidate
            recs.append(("h3", f"{rec.id}: {c.skill} ({c.signal})"))
            recs.append(("li", ["Problem: " + rec.problem]))
            recs.append(("li", ["Why it matters: " + rec.why]))
            recs.append(("li", ["Change: " + rec.change]))
            recs.append(("li", ["Measure: " + rec.measure]))
            recs.append(("li", ["Evidence: " + "; ".join(c.evidence)]))
            recs.append(("li", ["Panel: ", _panel_link(r, c)]))
    elif down:
        recs.append(("p", f"No data ({', '.join(down)} unreachable)"))
    else:
        recs.append(("p", "None."))
    out.append(("Recommendations", recs))

    fol: list[tuple] = []
    for f in r.followups:
        now = "no data" if f.now is None else f"{f.now:.2f}"
        fol.append(("li", [f"{f.id} ({f.skill}): {f.metric} was {f.before:.2f}, now {now}: "
                           f"{f.moved}; {f.reports_left} reports left"]))
    out.append(("Follow-ups", fol or [("p", "None.")]))

    b = r.builds or {}
    builds: list[tuple] = []
    if b.get("count"):
        ratings = ", ".join(str(x) for x in b.get("ratings", [])) or "none"
        builds.append(("p", f"{b['count']} builds this week. Ratings: {ratings}."))
        for line in b.get("repeated", []):
            builds.append(("li", ["Came up more than once: " + line]))
    else:
        builds.append(("p", "None."))
    out.append(("Builds", builds))

    rotb: list[tuple] = []
    for kind in KINDS:
        items = r.rot.get(kind, [])
        rotb.append(("h3", KIND_TITLES[kind]))
        if not items:
            rotb.append(("p", "None."))
            continue
        for it in items:
            rotb.append(("li", [f"{it.location}: {it.problem}. Fix: {it.fix}"]))
        extra = r.rot_totals.get(kind, len(items)) - len(items)
        if extra > 0:
            rotb.append(("li", [_more(r, extra)]))
    out.append(("Rot audit", rotb))

    health = [("li", [f"{k}: {v or 'no data'}"]) for k, v in r.health.items()]
    out.append(("Telemetry health", health or [("p", "None.")]))

    errs = [("li", [e]) for e in r.errors]
    out.append(("Run errors", errs or [("p", "None.")]))
    return out


# ---------------------------------------------------------------- views

def render_md(r: Report) -> str:
    lines = [f"# Weekly learn report {_esc(r.date, 'md')}", ""]
    for title, blocks in _sections(r):
        lines += [f"## {title}", ""]
        for blk in blocks:
            kind = blk[0]
            if kind == "status":
                lines += [f"**{_esc(blk[1].upper(), 'md')}**: {_esc(blk[2], 'md')}", ""]
            elif kind == "p":
                lines += [_inline(blk[1], "md"), ""]
            elif kind == "h3":
                lines += [f"### {_esc(blk[1], 'md')}", ""]
            elif kind == "li":
                lines.append("- " + "".join(_inline(c, "md") for c in blk[1]))
            elif kind == "table":
                lines.append("| " + " | ".join(blk[1]) + " |")
                lines.append("|" + " --- |" * len(blk[1]))
                for row in blk[2]:
                    lines.append("| " + " | ".join(_inline(c, "md") for c in row) + " |")
                lines.append("")
        if lines[-1] != "":
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(r: Report) -> str:
    parts: list[str] = []
    for title, blocks in _sections(r):
        parts.append(f"<h2>{title}</h2>")
        in_list = False
        for blk in blocks:
            kind = blk[0]
            if kind != "li" and in_list:
                parts.append("</ul>")
                in_list = False
            if kind == "li" and not in_list:
                parts.append("<ul>")
                in_list = True
            if kind == "status":
                css = blk[1] if blk[1] in ("green", "amber", "red") else "red"
                parts.append(f'<p class="status {css}">{_esc(blk[1].upper(), "html")}: '
                             f'{_esc(blk[2], "html")}</p>')
            elif kind == "p":
                parts.append(f"<p>{_inline(blk[1], 'html')}</p>")
            elif kind == "h3":
                parts.append(f"<h3>{_esc(blk[1], 'html')}</h3>")
            elif kind == "li":
                parts.append("<li>" + "".join(_inline(c, "html") for c in blk[1]) + "</li>")
            elif kind == "table":
                head = "".join(f"<th>{_esc(h, 'html')}</th>" for h in blk[1])
                rows = "".join("<tr>" + "".join(f"<td>{_inline(c, 'html')}</td>" for c in row)
                               + "</tr>" for row in blk[2])
                parts.append(f"<table><tr>{head}</tr>{rows}</table>")
        if in_list:
            parts.append("</ul>")
    template = string.Template(TEMPLATE.read_text())
    return template.substitute(date=_esc(r.date, "html"), body="\n".join(parts))


def to_json(r: Report) -> str:
    return json.dumps(asdict(r), indent=2, sort_keys=False)


def from_json(text: str) -> Report:
    d = json.loads(text)
    d["top"] = [SkillUsage(**s) for s in d["top"]]
    d["recommendations"] = [
        Recommendation(**{**x, "candidate": Candidate(**x["candidate"])})
        for x in d["recommendations"]]
    d["followups"] = [Followup(**f) for f in d["followups"]]
    d["rot"] = {k: [RotItem(**i) for i in v] for k, v in d["rot"].items()}
    return Report(**d)


# ---------------------------------------------------------------- CLI

def _reports_dir(cfg: learn_config.LearnConfig) -> Path:
    return learn_config.learn_dir(cfg) / "reports"


def _empty_prose(r: Report) -> list[str]:
    missing = []
    for rec in r.recommendations:
        tag = rec.id.rsplit("-", 1)[-1]
        for field in PROSE:
            if not str(getattr(rec, field)).strip():
                missing.append(f"{tag}.{field}")
    return missing


def _update_index(reports: Path, r: Report) -> None:
    path = reports / "index.json"
    try:
        entries = json.loads(path.read_text())
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError):
        entries = []
    entries = [e for e in entries if isinstance(e, dict) and e.get("date") != r.date]
    entries.append({"date": r.date, "status": r.status, "headline": _clean(r.headline)[:200]})
    entries.sort(key=lambda e: str(e.get("date")), reverse=True)
    path.write_text(json.dumps(entries[:INDEX_CAP], indent=2))


def _parse_date(value: str, flag: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        print(f"{flag} must be YYYY-MM-DD", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draft and render the weekly learn report.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--end", required=True, help="YYYY-MM-DD, exclusive end of the 7-day window")
    d.add_argument("--config")
    p = sub.add_parser("render")
    p.add_argument("--date", required=True, help="YYYY-MM-DD of the drafted report")
    p.add_argument("--config")
    args = ap.parse_args(argv)

    when = _parse_date(args.end if args.cmd == "draft" else args.date,
                       "--end" if args.cmd == "draft" else "--date")
    if when is None:
        return 2
    cfg = learn_config.load_learn_config(Path(args.config) if args.config else None)
    if cfg.kb is None:
        print("kb is not configured", file=sys.stderr)
        return 2
    reports = _reports_dir(cfg)

    if args.cmd == "draft":
        r, over = _build(cfg, when)
        reports.mkdir(parents=True, exist_ok=True)
        out = reports / f"{r.date}.json"
        out.write_text(to_json(r))
        _backlog(reports.parent / "backlog.md", r.date, over)
        print(out)
        return 0

    src = reports / f"{when.isoformat()}.json"
    try:
        r = from_json(src.read_text())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"cannot read {src.name}: {type(exc).__name__}", file=sys.stderr)
        return 2
    empty = _empty_prose(r)
    if empty:
        print("empty prose fields: " + ", ".join(empty), file=sys.stderr)
        return 2
    if r.date != when.isoformat():
        print(f"date in {src.name} is not {when.isoformat()}", file=sys.stderr)
        return 2
    prefix = cfg.grafana_url.rstrip("/") + "/d/cta-skills"
    r.links = {k: v for k, v in r.links.items() if isinstance(v, str) and v.startswith(prefix)}
    name = when.isoformat()
    (reports / f"{name}.md").write_text(render_md(r))
    (reports / f"{name}.html").write_text(render_html(r))
    _update_index(reports, r)
    print(reports / f"{name}.md")
    return 0


DASHBOARD = (Path(__file__).resolve().parents[3] / "telemetry" / "grafana" / "dashboards"
             / "cta-skills.json")
TOLERANCE = 0.05


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _panel_ids() -> dict[str, int]:
    """Panel title -> id from the provisioned dashboard; empty when the file is not there."""
    try:
        data = json.loads(DASHBOARD.read_text())
    except (OSError, ValueError):
        return {}
    found: dict[str, int] = {}

    def walk(panels):
        for p in panels if isinstance(panels, list) else []:
            if isinstance(p, dict):
                if isinstance(p.get("title"), str) and isinstance(p.get("id"), int):
                    found.setdefault(p["title"], p["id"])
                walk(p.get("panels"))

    walk(data.get("panels"))
    return found


def _links(cfg, week: Week, cands: list[Candidate]) -> dict[str, str]:
    stop = gather.week_end(week.end)
    start = gather.week_end(week.start)
    base = (f"{cfg.grafana_url.rstrip('/')}/d/cta-skills"
            f"?from={int(start.timestamp() * 1000)}&to={int(stop.timestamp() * 1000)}")
    links = {"grafana": base}
    ids = _panel_ids()
    for cand in cands:
        if cand.panel in ids:
            links[f"panel:{cand.panel}"] = f"{base}&viewPanel={ids[cand.panel]}"
    return links


def _index_dates(reports: Path) -> list[str]:
    try:
        entries = json.loads((reports / "index.json").read_text())
    except (OSError, ValueError):
        return []
    return [e["date"] for e in entries if isinstance(e, dict)
            and isinstance(e.get("date"), str) and _is_date(e["date"])]


def _previous_report(reports: Path, end: date) -> Report | None:
    for d in sorted((d for d in _index_dates(reports) if d < end.isoformat()), reverse=True):
        try:
            return from_json((reports / f"{d}.json").read_text())
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _delivery_errors(reports: Path, end: date, cfg: learn_config.LearnConfig | None = None) -> list[str]:
    """A Run errors line when the previous report fell back to a notification. Date only.

    The record is looked up in this reports folder, then in the previous date's report worktree
    (its pull request may not be merged yet), then its delivery worktree.
    """
    prior = sorted((d for d in _index_dates(reports) if d < end.isoformat()), reverse=True)
    if not prior:
        return []
    places = [reports]
    if cfg is not None:
        import decide  # deferred: decide imports this module
        for name in (f"learn-report-{prior[0]}", f"learn-delivery-{prior[0]}"):
            places.append(decide.WORKTREE_ROOT / name / cfg.kb_dir / "reports")
    row = None
    for place in places:
        try:
            row = json.loads((place / f"{prior[0]}.delivery.json").read_text())
            break
        except (OSError, ValueError):
            continue
    if isinstance(row, dict) and row.get("result") == "fallback":
        return [f"delivery fallback for {prior[0]}"]
    return []


def _rot_key(item: RotItem) -> tuple[str, str, str]:
    return (item.kind, item.location, item.problem)


def _new_rot(current: dict[str, list[RotItem]], prev: Report | None) -> int:
    if prev is None:
        return 0
    before = {_rot_key(i) for items in prev.rot.values() for i in items}
    return sum(1 for items in current.values() for i in items if _rot_key(i) not in before)


def _current_value(week: Week, skill: str, signal: str) -> float | None:
    """The signal's value for the skill this week, or None when it is not past its bar."""
    import signals
    usage = next((s for s in week.skills if s.skill == skill), None)
    if usage is None:
        return None
    for mod in signals.discover()[0]:
        if mod.NAME == signal:
            try:
                cand = mod.evaluate(week, usage)
            except Exception:
                return None
            return None if cand is None else cand.value
    return None


def _moved(before: float, now: float | None, week: Week, skill: str) -> str:
    if week.missing or not any(s.skill == skill for s in week.skills):
        return "no data"
    if now is None:
        return "better"  # the signal no longer fires: the value is under its bar
    if abs(now - before) <= TOLERANCE * abs(before):
        return "flat"
    return "better" if now < before else "worse"  # every signal so far: lower is better


def _followups(cfg, week: Week, reports: Path, end: date) -> list[Followup]:
    try:
        lines = (reports.parent / "decisions.jsonl").read_text().splitlines()
    except OSError:
        return []
    report_dates = _index_dates(reports)
    out: list[Followup] = []
    seen: set[str] = set()
    for raw in lines:
        try:
            row = json.loads(raw)
            decided = date.fromisoformat(row["date"])
            rid, skill, fp = row["id"], row["skill"], row["fingerprint"]
            before = float(row["value"])
        except (ValueError, KeyError, TypeError):
            continue
        if row.get("decision") != "accept" or rid in seen or not isinstance(fp, str):
            continue
        seen.add(rid)
        since = sum(1 for d in report_dates if decided.isoformat() < d < end.isoformat())
        count = since + 1
        if count > cfg.followup_reports:
            continue
        signal = fp.split("|", 1)[1] if "|" in fp else ""
        now = _current_value(week, skill, signal)
        out.append(Followup(id=sanitize.line(rid), skill=sanitize.name(skill),
                            metric=sanitize.name(row.get("metric", signal)), before=before,
                            now=now, moved=_moved(before, now, week, skill),
                            reports_left=cfg.followup_reports - count))
    return out


def _wrong_lines(text: str) -> list[str]:
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower() == "what went wrong"
        elif inside and line.lstrip().startswith("- "):
            out.append(sanitize.line(line.lstrip()[2:]))
    return out


def _builds(cfg, week: Week) -> dict:
    result: dict = {"count": 0, "ratings": [], "repeated": []}
    if cfg.kb is None:
        return result
    base = cfg.kb / learn_config.cta_config.DEFAULT_PROJECTS_DIR
    seen: dict[str, list] = {}
    for path in sorted(base.glob("*/builds/*/retro.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-", path.parent.name)
        if not m or not _is_date(m.group(1)):
            continue
        if not week.start <= date.fromisoformat(m.group(1)) < week.end:
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        result["count"] += 1
        rating = re.search(r"\*\*(\d)/5\*\*", text)
        if rating:
            result["ratings"].append(int(rating.group(1)))
        here = {l.lower(): l for l in _wrong_lines(text)}
        for key, original in here.items():
            seen.setdefault(key, [original, 0])[1] += 1
    result["repeated"] = sorted(line for line, n in seen.values() if n >= 2)[:5]
    return result


def _backlog(path: Path, day: str, over: list[Candidate]) -> None:
    """Append candidates past the cap, once each: a recurring one is not re-added weekly."""
    if not over:
        return
    try:
        text = path.read_text()
    except FileNotFoundError:
        text = None  # only a missing file means start fresh; any other error propagates
    seen = {key for line in (text or "").splitlines()
            for key in re.findall(r"\(([^()\n]*)\)\s*$", line)}
    new = []
    for c in over:
        fp = _esc(c.fingerprint or c.skill, "md")
        if fp in seen:
            continue
        seen.add(fp)
        new.append(f"- {day} {_esc(c.skill, 'md')}: {_esc(c.signal, 'md')} ({fp})")
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            path.write_text("# Backlog\n\n" + "\n".join(new) + "\n")
        else:
            with path.open("a") as f:
                f.write(("" if text.endswith("\n") or not text else "\n") + "\n".join(new) + "\n")


def build(cfg: learn_config.LearnConfig, end: date) -> Report:
    return _build(cfg, end)[0]


def _build(cfg: learn_config.LearnConfig, end: date) -> tuple[Report, list[Candidate]]:
    week = gather.gather(cfg, end)
    reports = learn_config.learn_dir(cfg) / "reports" if cfg.kb else None
    decisions = reports.parent / "decisions.jsonl" if reports else Path("/nonexistent")
    top = candidates.top_skills(week)
    cands, over, cand_errors = candidates.select(week, cfg, decisions)
    items, totals, rot_errors = rot.run_rot(week, cfg)

    errors = list(week.errors) + list(cand_errors) + list(rot_errors)
    errors += [f"config: {n}" for n in cfg.notes]
    errors += [f"{src} unreachable" for src in week.missing]
    if reports:
        errors += _delivery_errors(reports, end, cfg)
    problems = [e for e in errors if not e.startswith("config: config renamed:")]
    if not cfg.exclude_organization_ids:
        errors.append(NO_EXCLUDE_NOTE)  # a note: it does not turn the status red

    new_rot = _new_rot(items, _previous_report(reports, end)) if reports else 0
    followups = _followups(cfg, week, reports, end) if reports else []
    recs = [Recommendation(id=f"{end.isoformat()}-R{n}", candidate=c)
            for n, c in enumerate(cands, 1)]
    worse = [f for f in followups if f.moved == "worse"]

    if week.missing:
        status, headline = "red", f"No data from {', '.join(week.missing)}"
    elif problems:
        status, headline = "red", f"The run hit {len(problems)} error(s)"
    elif new_rot:
        status, headline = "red", f"{new_rot} new rot item(s) since the last report"
    elif recs:
        status, headline = "amber", f"{len(recs)} recommendation(s) to decide"
    elif worse:
        status, headline = "amber", f"{len(worse)} accepted change(s) moved the wrong way"
    else:
        status, headline = "green", "Nothing needs attention."

    gap = "prometheus" in week.missing or not week.skills
    prevs = [s.prev_cost_usd for s in week.skills if s.prev_cost_usd is not None]
    report = Report(
        date=end.isoformat(), status=status, headline=headline, top=top,
        total_cost=None if gap else sum(s.cost_usd for s in week.skills),
        total_prev_cost=None if gap or not prevs else sum(prevs),
        recommendations=recs, followups=followups, builds=_builds(cfg, week), rot=items,
        rot_totals=totals, health=dict(week.freshness), errors=errors,
        links=_links(cfg, week, cands))
    return report, over


if __name__ == "__main__":
    sys.exit(main())
