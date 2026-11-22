#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Derive per-skill episodes from Claude Code transcripts and post them to the local
Collector as OTLP log events (`event.name=cta.skill_episode`).

An episode runs from a skill's invocation (a Skill tool call, or a slash command that loads a
skill) to the end of that turn: the next prompt, the next skill, or the end of the transcript.

Outcome:
  abandoned  the skill's last tool call never completed before the episode ended
  drifted    a correction, interruption or redirect within the skill or in the next two prompts
  success    otherwise

It never calls a model; it only reads `~/.claude/projects/**/*.jsonl`. The per-transcript
high-water mark in `<state>/drift.json` advances only after the Collector accepts the POST.

Usage: uv run telemetry/enrich_drift.py [--since 26h]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

OTLP = "http://127.0.0.1:4318"
PROJECTS = Path.home() / ".claude/projects"
SETTLE_S = 300  # a transcript idle this long is treated as finished
SERVICE = "claude-code"  # episodes sit next to Claude Code's own events in Loki
CORE_SKILLS_DIR = Path(__file__).resolve().parent.parent / "plugins/core/skills"
CORE_SKILLS_FALLBACK = {"create-skill", "create-hook", "config-audit"}

INTERRUPT = "[Request interrupted by user"
SKILL_BASE = "Base directory for this skill"
CORRECTION = re.compile(r"^(?:no|not that|that's wrong|stop|wrong)\b")
REDIRECT = re.compile(r"\binstead\b|\bactually,|\blet's not\b")
COMMAND = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
NOT_A_PROMPT = ("<local-command", "<task-notification", "<system-reminder")


def default_state_path() -> Path:
    override = os.environ.get("CTA_STATE_DIR")
    base = Path(override) if override else Path.home() / ".local/share/cta/state"
    return base / "drift.json"


def classify(prompt: str) -> str | None:
    """Return "interruption", "correction", "redirect" or None for one user prompt."""
    if INTERRUPT in prompt:
        return "interruption"
    text = prompt.replace("’", "'").lower()
    if CORRECTION.match(re.sub(r"^[\W_]+", "", text)):
        return "correction"
    if REDIRECT.search(text):
        return "redirect"
    return None


def core_skills() -> set[str]:
    try:
        names = {p.name for p in CORE_SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file()}
    except OSError:
        names = set()
    return names or CORE_SKILLS_FALLBACK


def normalize(skill: str) -> str:
    """Plugin-namespaced name where known (core skills), otherwise as written."""
    skill = skill.lstrip("/")
    if ":" not in skill and skill in core_skills():
        return f"core:{skill}"
    return skill


@dataclass
class Episode:
    session_id: str
    skill: str
    start: datetime
    end: datetime
    turns: int = 0
    signals: list[str] = field(default_factory=list)
    outcome: str = "success"
    followups: int = 0  # prompts seen after the episode, up to 2

    @property
    def skill_short(self) -> str:
        return self.skill.split(":", 1)[-1]

    @property
    def duration_ms(self) -> int:
        return int((self.end - self.start).total_seconds() * 1000)


@dataclass
class _Open:
    ep: Episode
    msg_ids: set = field(default_factory=set)
    last_tool: str | None = None
    unresolved: set = field(default_factory=set)


def _when(line: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(line["timestamp"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        return None


def _blocks(line: dict) -> list:
    content = (line.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(blocks: list) -> str:
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, list):
        return _text([b for b in c if isinstance(b, dict)])
    return c if isinstance(c, str) else ""


def _add(signals: list[str], signal: str | None) -> None:
    if signal and signal not in signals:
        signals.append(signal)


def episodes(transcript_lines: Iterable[dict]) -> list[Episode]:
    done: list[Episode] = []
    waiting: list[Episode] = []  # closed episodes still collecting their next two prompts
    cur: _Open | None = None
    slash: tuple[str, datetime, str] | None = None  # a slash command that may load a skill

    def close() -> None:
        nonlocal cur
        if cur is None:
            return
        ep = cur.ep
        ep.turns = len(cur.msg_ids)
        if cur.last_tool in cur.unresolved:
            ep.outcome = "abandoned"
        done.append(ep)
        waiting.append(ep)
        cur = None

    def signal(name: str) -> None:
        if cur is not None:
            _add(cur.ep.signals, name)
        for ep in waiting:
            _add(ep.signals, name)

    for line in transcript_lines:
        kind = line.get("type")
        when = _when(line)
        if kind not in ("user", "assistant") or when is None:
            continue
        sid = line.get("sessionId", "")
        blocks = _blocks(line)

        if kind == "assistant":
            slash = None
            for b in blocks:
                if b.get("type") != "tool_use":
                    continue
                if b.get("name") == "Skill" and (b.get("input") or {}).get("skill"):
                    close()
                    skill = normalize(b["input"]["skill"])
                    cur = _Open(Episode(sid, skill, when, when))
                if cur is not None:
                    cur.last_tool = b.get("id")
                    cur.unresolved.add(b.get("id"))
            if cur is not None:
                cur.msg_ids.add((line.get("message") or {}).get("id") or line.get("uuid"))
                cur.ep.end = max(cur.ep.end, when)
            continue

        # user lines
        text = _text(blocks)
        results = [b for b in blocks if b.get("type") == "tool_result"]
        if line.get("isMeta"):
            if slash and text.startswith(SKILL_BASE):
                close()
                name, start, ssid = slash
                cur = _Open(Episode(ssid, normalize(name), start, when))
                slash = None
            continue
        if results:
            for b in results:
                if cur is not None:
                    cur.unresolved.discard(b.get("tool_use_id"))
                if INTERRUPT in _result_text(b):
                    signal("interruption")
            if cur is not None:
                cur.ep.end = max(cur.ep.end, when)
            continue
        if INTERRUPT in text:
            signal("interruption")
            if cur is not None:
                cur.ep.end = max(cur.ep.end, when)
            continue
        if (not text.strip() or line.get("isCompactSummary") or line.get("promptSource") == "system"
                or text.lstrip().startswith(NOT_A_PROMPT)):
            continue

        # a human prompt: it ends the open episode and counts as a follow-up for earlier ones
        close()
        kind_of = classify(text)
        for ep in waiting:
            _add(ep.signals, kind_of)
            ep.followups += 1
        waiting = [ep for ep in waiting if ep.followups < 2]
        m = COMMAND.search(text)
        slash = (m.group(1), when, sid) if m else None

    close()
    for ep in done:
        if ep.outcome != "abandoned" and ep.signals:
            ep.outcome = "drifted"
    return done


# --- posting ------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _attr(key: str, value) -> dict:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def otlp_body(eps: list[Episode], now_ns: int) -> dict:
    # Records are stamped with the run time, not the episode time: Loki rejects entries that are
    # more than about an hour older than the newest in their stream. The episode's own window is
    # in the `start`, `end` and `duration_ms` attributes.
    records = [{
        "timeUnixNano": str(now_ns + i),
        "observedTimeUnixNano": str(now_ns + i),
        "severityText": "INFO",
        "body": {"stringValue": f"cta.skill_episode {ep.skill} {ep.outcome}"},
        "attributes": [
            _attr("event.name", "cta.skill_episode"),
            _attr("session.id", ep.session_id),
            _attr("skill", ep.skill),
            _attr("skill_short", ep.skill_short),
            _attr("start", _iso(ep.start)),
            _attr("end", _iso(ep.end)),
            _attr("duration_ms", ep.duration_ms),
            _attr("turns", ep.turns),
            _attr("signals", ",".join(ep.signals) or "none"),
            _attr("outcome", ep.outcome),
        ],
    } for i, ep in enumerate(eps)]
    return {"resourceLogs": [{
        "resource": {"attributes": [_attr("service.name", SERVICE),
                                    _attr("cta.source", "enrich_drift")]},
        "scopeLogs": [{"scope": {"name": "cta.enrich_drift"}, "logRecords": records}],
    }]}


def post(endpoint: str, body: dict) -> None:
    req = urllib.request.Request(endpoint.rstrip("/") + "/v1/logs", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


# --- state and main -----------------------------------------------------------

def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "files": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_lines(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if isinstance(line, dict):
                yield line


def _parse_mark(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def main(since: datetime, *, projects: Path = PROJECTS, state_path: Path | None = None,
         endpoint: str = OTLP, now: datetime | None = None) -> int:
    state_path = state_path or default_state_path()
    now = now or datetime.now(timezone.utc)
    state = load_state(state_path)
    batch: list[Episode] = []
    marks: dict[str, str] = {}

    for path in sorted(projects.rglob("*.jsonl")):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < since.timestamp():
            continue
        idle = now.timestamp() - mtime >= SETTLE_S
        mark = _parse_mark(state["files"].get(str(path)))
        try:
            found = sorted(episodes(read_lines(path)), key=lambda e: e.start)
        except OSError as e:
            print(f"drift: skipped unreadable transcript ({e})", file=sys.stderr)
            continue
        for ep in found:
            if ep.start < since or (mark and ep.start <= mark):
                continue
            if ep.followups < 2 and not idle:
                break  # still in progress; this and later episodes wait for the next run
            batch.append(ep)
            marks[str(path)] = _iso(ep.start)

    if not batch:
        print("drift: no new episodes")
        return 0
    try:
        post(endpoint, otlp_body(batch, time.time_ns()))
    except urllib.error.HTTPError as e:
        print(f"drift: collector at {endpoint} rejected the episodes (HTTP {e.code}); "
              "high-water mark unchanged", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        print(f"drift: collector unreachable at {endpoint} ({reason}); "
              "high-water mark unchanged", file=sys.stderr)
        return 1

    state["files"].update(marks)
    state["version"] = 1
    save_state(state_path, state)
    counts: dict[str, int] = {}
    for ep in batch:
        counts[ep.outcome] = counts.get(ep.outcome, 0) + 1
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"drift: posted {len(batch)} episodes from {len(marks)} transcripts ({summary})")
    return 0


def parse_since(value: str, now: datetime | None = None) -> datetime:
    m = re.fullmatch(r"(\d+)([mhd])", value.strip())
    if not m:
        raise ValueError(f"--since must look like 30m, 26h or 7d, not {value!r}")
    unit = {"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
    return (now or datetime.now(timezone.utc)) - timedelta(**{unit: int(m.group(1))})


def cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default="26h", help="look back this far: 30m, 26h, 7d (default 26h)")
    args = ap.parse_args(argv)
    try:
        since = parse_since(args.since)
    except ValueError as e:
        ap.error(str(e))
    return main(since)


if __name__ == "__main__":
    sys.exit(cli())
