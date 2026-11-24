#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Gather one week of skill usage from Prometheus and Loki into a `Week`.

Missing data is reported (`missing`, `errors`), never turned into a zero. Every string that
enters the `Week` goes through `sanitize`. Events and skills of an excluded organization_id
(`exclude_organization_ids`) or marketplace owner are dropped (personal scope).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import learn_config
import sanitize
from model import SkillUsage, Week

KNOWN_MARKETPLACES = Path.home() / ".claude" / "plugins" / "known_marketplaces.json"
SELECTOR = '{service_name="claude-code"}'
EVENT_TYPES = ("tool_decision", "tool_result", "mcp_server_connection", "plugin_loaded")
NAME_KEYS = {"skill", "skill_short", "skill_name", "plugin_name", "marketplace_name",
             "server_name", "tool_name"}
TIMEOUT = 10


class GatherError(Exception):
    def __init__(self, source: str, detail: str):
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail


# An opener with only the http and https handlers: file:// and other schemes cannot be opened.
_OPENER = urllib.request.build_opener(urllib.request.HTTPHandler, urllib.request.HTTPSHandler)


def _get_json(source: str, url: str) -> dict:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise GatherError(source, "URL must be http or https")
    try:
        with _OPENER.open(url, timeout=TIMEOUT) as r:
            body = json.load(r)
    except urllib.error.HTTPError as exc:
        raise GatherError(source, f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise GatherError(source, str(getattr(exc, "reason", exc))) from exc
    except ValueError as exc:
        raise GatherError(source, "response was not JSON") from exc
    if not isinstance(body, dict) or body.get("status") not in (None, "success"):
        raise GatherError(source, "query failed")
    return body


def prom_query(url: str, promql: str, at: datetime) -> list[dict]:
    qs = urllib.parse.urlencode({"query": promql, "time": f"{at.timestamp():.3f}"})
    body = _get_json("prometheus", f"{url.rstrip('/')}/api/v1/query?{qs}")
    result = (body.get("data") or {}).get("result")
    return result if isinstance(result, list) else []


def loki_query(url: str, logql: str, start: datetime, end: datetime,
               limit: int = 5000) -> list[dict]:
    """Log lines as flat dicts: stream labels, structured metadata, `ts` (ns) and `line`."""
    qs = urllib.parse.urlencode({
        "query": logql, "limit": limit, "direction": "backward",
        "start": int(start.timestamp() * 1e9), "end": int(end.timestamp() * 1e9)})
    body = _get_json("loki", f"{url.rstrip('/')}/loki/api/v1/query_range?{qs}")
    out: list[dict] = []
    for stream in (body.get("data") or {}).get("result") or []:
        labels = stream.get("stream") or {}
        for value in stream.get("values") or []:
            row = dict(labels)
            if len(value) > 2 and isinstance(value[2], dict):
                row.update(value[2].get("structuredMetadata") or value[2])
            row["ts"], row["line"] = value[0], value[1]
            out.append(row)
    return out


def week_end(end: date) -> datetime:
    """`end` 00:00 in the local time zone."""
    return datetime.combine(end, time.min).astimezone()


def _owner(repo: str | None) -> str | None:
    return repo.split("/")[0] if repo and "/" in repo else None


def personal(cfg: learn_config.LearnConfig, org_id: str | None,
             marketplace_owner: str | None) -> bool:
    if org_id and org_id in cfg.exclude_organization_ids:
        return False
    owner = marketplace_owner.split("/")[0] if marketplace_owner else None
    if owner and owner.lower() in {o.lower() for o in cfg.exclude_owners}:
        return False
    return True


def _marketplace_repos() -> dict[str, str]:
    try:
        data = json.loads(KNOWN_MARKETPLACES.read_text())
    except (OSError, ValueError):
        return {}
    repos = {}
    if isinstance(data, dict):
        for key, entry in data.items():
            repo = ((entry or {}).get("source") or {}).get("repo") if isinstance(entry, dict) else None
            if isinstance(repo, str):
                repos[key] = repo
    return repos


def _num(value) -> float | None:
    try:
        x = float(value[1])
    except (TypeError, ValueError, IndexError):
        return None
    return x if math.isfinite(x) else None


def _iso_ns(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat(timespec="seconds")


KEEP_KEYS = {"event_name", "ts", "skill", "skill_short", "skill_name", "plugin_name",
             "marketplace_name", "server_name", "tool_name", "decision", "source", "outcome",
             "signals", "duration_ms", "turns", "start", "end", "session_id", "organization_id",
             "invocation_trigger", "skill_source", "transport", "status", "success", "command_word"}
SAFE_WORD = re.compile(r"[A-Za-z0-9_.-]{1,40}")


def _command_word(row: dict) -> str | None:
    """First word of the command in `tool_parameters`, only if it is a plain word (S2)."""
    params = row.get("tool_parameters")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            return None
    command = params.get("command") if isinstance(params, dict) else None
    words = command.split() if isinstance(command, str) else []
    return words[0] if words and SAFE_WORD.fullmatch(words[0]) else None


def _clean_event(row: dict) -> dict:
    """Allow-listed fields only: no identity, prompt or raw log text reaches the Week."""
    out = {}
    if row.get("event_name") == "tool_decision":
        word = _command_word(row)
        if word:
            out["command_word"] = word
    for key, value in row.items():
        if key in KEEP_KEYS and key != "command_word":
            out[key] = sanitize.name(value) if key in NAME_KEYS else sanitize.line(value)
    return out


def _ts(row: dict) -> int | None:
    try:
        return int(row.get("ts"))
    except (TypeError, ValueError):
        return None


def _activation_index(rows: list[dict]) -> dict[str, list[tuple[int, str]]]:
    """Per session, the (timestamp, skill) activations in time order."""
    index: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        session, skill, ts = row.get("session_id"), row.get("skill_name"), _ts(row)
        if session and skill and ts is not None:
            index.setdefault(session, []).append((ts, sanitize.name(skill)))
    for entries in index.values():
        entries.sort()
    return index


def _attribute(event: dict, index: dict[str, list[tuple[int, str]]]) -> dict:
    """Name the skill of the latest activation in the event's session at or before it.

    No such activation: the event is unattributed (no `skill_name`) and no skill counts it.
    """
    out = {k: v for k, v in event.items() if k != "skill_name"}
    ts = _ts(event)
    if ts is None:
        return out
    for at, skill in reversed(index.get(event.get("session_id"), ())):
        if at <= ts:
            out["skill_name"] = skill
            break
    return out


class _Run:
    """One gather pass: tracks errors and which sources are unreachable."""

    def __init__(self, cfg: learn_config.LearnConfig, week: Week):
        self.cfg, self.week, self.down = cfg, week, set()

    def prom(self, promql: str, at: datetime) -> list[dict]:
        if "prometheus" in self.down:
            return []
        try:
            return prom_query(self.cfg.prometheus_url, promql, at)
        except GatherError as exc:
            self._fail(exc)
            return []

    def loki(self, logql: str, start: datetime, end: datetime) -> list[dict]:
        if "loki" in self.down:
            return []
        try:
            return loki_query(self.cfg.loki_url, logql, start, end)
        except GatherError as exc:
            self._fail(exc)
            return []

    def _fail(self, exc: GatherError) -> None:
        self.down.add(exc.source)
        self.week.errors.append(f"{exc.source}: {sanitize.line(exc.detail)}")
        if exc.source not in self.week.missing:
            self.week.missing.append(exc.source)


def _sum_rows(rows: list[dict]) -> dict[tuple[str, str], dict[str, float]]:
    out: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        metric = row.get("metric") or {}
        value = _num(row.get("value"))
        skill = metric.get("skill_name")
        if not skill or value is None:
            continue
        key = (skill, metric.get("organization_id") or "")
        out.setdefault(key, {})
        kind = metric.get("type", "")
        out[key][kind] = out[key].get(kind, 0.0) + value
    return out


def gather(cfg: learn_config.LearnConfig, end: date) -> Week:
    end_dt = week_end(end)
    start_dt = end_dt - timedelta(days=7)
    prev_end = start_dt
    prev_start = prev_end - timedelta(days=7)
    week = Week(start=end - timedelta(days=7), end=end)
    run = _Run(cfg, week)

    # Same expressions as the dashboard panels (max_over_time over the range, [7d] for
    # $__range), plus organization_id in the grouping for the personal filter.
    cost_q = ('sum by (skill_name, organization_id) '
              '(max_over_time(claude_code_cost_usage_USD_total{skill_name!=""}[7d]))')
    tok_q = ('sum by (skill_name, organization_id, type) '
             '(max_over_time(claude_code_token_usage_tokens_total{skill_name!=""}[7d]))')
    cost = _sum_rows(run.prom(cost_q, end_dt))
    tokens = _sum_rows(run.prom(tok_q, end_dt))
    prev_cost = _sum_rows(run.prom(cost_q, prev_end))
    stamp = run.prom("max(timestamp(claude_code_cost_usage_USD_total))", end_dt)
    if stamp and _num(stamp[0].get("value")) is not None:
        week.freshness["prometheus"] = datetime.fromtimestamp(
            _num(stamp[0]["value"]), tz=timezone.utc).isoformat(timespec="seconds")
    if "prometheus" not in run.down and not (cost or tokens):
        week.missing.append("prometheus")

    newest_ns = 0
    saw_loki = False

    def fetch(event: str, start: datetime, stop: datetime) -> list[dict]:
        nonlocal newest_ns, saw_loki
        rows = run.loki(f'{SELECTOR} | event_name="{event}"', start, stop)
        rows = [r for r in rows if r.get("organization_id") not in cfg.exclude_organization_ids]
        for row in rows:
            try:
                newest_ns = max(newest_ns, int(row.get("ts", 0)))
            except (TypeError, ValueError):
                pass
        saw_loki = saw_loki or bool(rows)
        return rows

    loaded = fetch("plugin_loaded", start_dt, end_dt)
    repos = _marketplace_repos()
    plugin_market: dict[str, str] = {}
    for row in loaded:
        if row.get("plugin_name") and row.get("marketplace_name"):
            plugin_market[row["plugin_name"]] = row["marketplace_name"]

    def plugin_of(skill: str) -> str | None:
        return skill.split(":", 1)[0] if ":" in skill else None

    keep: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    for key in set(cost) | set(tokens):
        skill, org = key
        plugin = plugin_of(skill)
        market = plugin_market.get(plugin) if plugin else None
        if personal(cfg, org, _owner(repos.get(market)) if market else None):
            keep[key] = (plugin, market)
    personal_skills = {skill for skill, _ in keep}

    activated = fetch("skill_activated", start_dt, end_dt)
    prev_activated = fetch("skill_activated", prev_start, prev_end)
    inv: dict[str, int] = {}
    sess: dict[str, set] = {}
    for row in activated:
        skill = row.get("skill_name")
        if skill in personal_skills:
            inv[skill] = inv.get(skill, 0) + 1
            sess.setdefault(skill, set()).add(row.get("session_id") or row.get("session.id"))
    prev_inv: dict[str, int] = {}
    for row in prev_activated:
        skill = row.get("skill_name")
        if skill in personal_skills:
            prev_inv[skill] = prev_inv.get(skill, 0) + 1

    merged: dict[str, SkillUsage] = {}
    for key, (plugin, market) in sorted(keep.items()):
        skill = key[0]
        c = sum(cost.get(key, {}).values())
        t = tokens.get(key, {})
        pc = prev_cost.get(key)
        usage = SkillUsage(
            skill=sanitize.name(skill),
            plugin=sanitize.name(plugin) if plugin else None,
            marketplace=sanitize.name(market) if market else None,
            invocations=inv.get(skill, 0),
            sessions=len(sess.get(skill, ())),
            input_tokens=int(t.get("input", 0)),
            output_tokens=int(t.get("output", 0)),
            cost_usd=c,
            prev_cost_usd=sum(pc.values()) if pc is not None else None,
            prev_invocations=(prev_inv.get(skill, 0) if prev_activated else None),
        )
        if usage.skill in merged:  # same skill under two organizations of the personal set
            m = merged[usage.skill]
            m.invocations += usage.invocations
            m.sessions += usage.sessions
            m.input_tokens += usage.input_tokens
            m.output_tokens += usage.output_tokens
            m.cost_usd += usage.cost_usd
            if usage.prev_cost_usd is not None:
                m.prev_cost_usd = (m.prev_cost_usd or 0.0) + usage.prev_cost_usd
        else:
            merged[usage.skill] = usage
    week.skills = sorted(merged.values(), key=lambda s: (-s.cost_usd, s.skill))

    episodes = run.loki(f'{SELECTOR} | event_name="cta.skill_episode"', start_dt, end_dt)
    drift_ns = 0
    for row in episodes:
        if row.get("skill") not in personal_skills:
            continue
        week.episodes.append(_clean_event(row))
        try:
            drift_ns = max(drift_ns, int(row.get("ts", 0)))
        except (TypeError, ValueError):
            pass
        saw_loki = True
    if drift_ns:
        week.freshness["drift"] = _iso_ns(drift_ns)

    starts = _activation_index(activated)
    for event in EVENT_TYPES:
        rows = [_clean_event(r) for r in fetch(event, start_dt, end_dt)]
        if event == "tool_result":
            rows = [_attribute(r, starts) for r in rows]
        week.events[event] = rows

    if newest_ns:
        week.freshness["loki"] = _iso_ns(newest_ns)
    if "loki" not in run.down and not saw_loki:
        week.missing.append("loki")
    return week


def _jsonable(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(type(value))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gather one week of skill usage as JSON.")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD, exclusive end of the 7-day window")
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("--out", required=True, help="file to write the Week JSON to")
    args = ap.parse_args(argv)
    try:
        end = date.fromisoformat(args.end)
    except ValueError:
        print("--end must be YYYY-MM-DD", file=sys.stderr)
        return 2
    cfg = learn_config.load_learn_config(Path(args.config) if args.config else None)
    week = gather(cfg, end)
    Path(args.out).write_text(json.dumps(asdict(week), default=_jsonable, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
