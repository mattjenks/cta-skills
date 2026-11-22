"""Tests for the drift enricher. Every transcript here is synthetic."""
import json
import os
import socket
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import enrich_drift
from enrich_drift import classify, episodes

SID = "sess-1"
T0 = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)


def ts(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def prompt(text, t):
    return {"type": "user", "sessionId": SID, "timestamp": ts(t),
            "message": {"role": "user", "content": text}}


def skill_call(name, t, tid="sk1"):
    return {"type": "assistant", "sessionId": SID, "timestamp": ts(t),
            "message": {"id": f"msg-{tid}", "role": "assistant", "content": [
                {"type": "tool_use", "id": tid, "name": "Skill", "input": {"skill": name}}]}}


def tool_use(tid, t, name="Read"):
    return {"type": "assistant", "sessionId": SID, "timestamp": ts(t),
            "message": {"id": f"msg-{tid}", "role": "assistant", "content": [
                {"type": "tool_use", "id": tid, "name": name, "input": {}}]}}


def tool_result(tid, t, text="ok"):
    return {"type": "user", "sessionId": SID, "timestamp": ts(t),
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def skill_base(t):
    return {"type": "user", "isMeta": True, "sessionId": SID, "timestamp": ts(t),
            "message": {"role": "user", "content": [
                {"type": "text", "text": "Base directory for this skill: /skills/x"}]}}


def say(text, t, mid):
    return {"type": "assistant", "sessionId": SID, "timestamp": ts(t),
            "message": {"id": mid, "role": "assistant", "content": [{"type": "text", "text": text}]}}


def interrupted(t):
    return {"type": "user", "sessionId": SID, "timestamp": ts(t),
            "message": {"role": "user", "content": [
                {"type": "text", "text": "[Request interrupted by user]"}]}}


def skill_turn(name="create-skill", start=10):
    """A complete skill turn: invoke, load, one tool call that completes, a closing reply."""
    return [
        skill_call(name, start),
        tool_result("sk1", start + 1, "Launching skill"),
        skill_base(start + 1),
        tool_use("t1", start + 2),
        tool_result("t1", start + 3),
        say("Here is the skill.", start + 4, "m-end"),
    ]


# --- classify ---------------------------------------------------------------

def test_classify_correction():
    assert classify("No, use the other file") == "correction"
    assert classify("  ...no") == "correction"
    assert classify("Not that one") == "correction"
    assert classify("that's wrong, try again") == "correction"
    assert classify("That’s wrong") == "correction"
    assert classify("STOP") == "correction"
    assert classify("Wrong file.") == "correction"


def test_classify_ignores_no_inside_sentence():
    assert classify("I have no idea") is None
    assert classify("nothing else, thanks") is None
    assert classify("stopwatch skill please") is None
    assert classify("looks good") is None


def test_classify_interruption_and_redirect():
    assert classify("[Request interrupted by user for tool use]") == "interruption"
    assert classify("Use the yaml one instead") == "redirect"
    assert classify("Actually, make it shorter") == "redirect"
    assert classify("let's not do that yet") == "redirect"


# --- episodes ---------------------------------------------------------------

def test_episode_success():
    lines = [prompt("make a skill", 0), *skill_turn(), prompt("great, thanks", 60),
             say("ok", 61, "m2"), prompt("commit it", 70)]
    [ep] = episodes(lines)
    assert ep.session_id == SID
    assert ep.skill == "core:create-skill"
    assert ep.skill_short == "create-skill"
    assert ep.start == T0 + timedelta(seconds=10)
    assert ep.end == T0 + timedelta(seconds=14)
    assert ep.turns == 3
    assert ep.signals == []
    assert ep.outcome == "success"
    assert ep.followups == 2


def test_episode_drifted_by_next_prompt():
    lines = [prompt("make a skill", 0), *skill_turn(), prompt("fine", 60),
             say("ok", 61, "m2"), prompt("Actually, call it differently", 70)]
    [ep] = episodes(lines)
    assert ep.outcome == "drifted"
    assert ep.signals == ["redirect"]


def test_episode_not_drifted_by_third_prompt():
    lines = [prompt("make a skill", 0), *skill_turn(), prompt("fine", 60),
             prompt("ok", 70), prompt("no, wait", 80)]
    [ep] = episodes(lines)
    assert ep.outcome == "success"


def test_episode_drifted_by_interruption_within_skill():
    lines = [prompt("make a skill", 0), skill_call("create-skill", 10),
             tool_result("sk1", 11, "Launching skill"), skill_base(11), tool_use("t1", 12),
             tool_result("t1", 13, "[Request interrupted by user for tool use]"),
             interrupted(13), prompt("keep going", 30)]
    [ep] = episodes(lines)
    assert ep.outcome == "drifted"
    assert ep.signals == ["interruption"]


def test_episode_abandoned():
    # The skill's last tool call never got a result before the session ended.
    lines = [prompt("make a skill", 0), skill_call("create-skill", 10),
             tool_result("sk1", 11, "Launching skill"), skill_base(11), tool_use("t1", 12)]
    [ep] = episodes(lines)
    assert ep.outcome == "abandoned"


def test_episode_abandoned_by_topic_change():
    lines = [prompt("make a skill", 0), skill_call("create-skill", 10),
             tool_result("sk1", 11, "Launching skill"), skill_base(11), tool_use("t1", 12),
             prompt("<command-name>/clear</command-name>", 20), prompt("what's the weather", 30)]
    [ep] = episodes(lines)
    assert ep.outcome == "abandoned"


def test_episode_from_user_slash_command_and_other_plugins():
    lines = [prompt("<command-name>/superpowers:brainstorming</command-name>", 0),
             skill_base(0.5), say("Let's brainstorm.", 1, "m1"), prompt("sounds good", 20),
             prompt("<command-name>/clear</command-name>", 30)]
    [ep] = episodes(lines)
    assert ep.skill == "superpowers:brainstorming"
    assert ep.skill_short == "brainstorming"
    assert ep.start == T0
    assert ep.outcome == "success"


def test_builtin_slash_command_is_not_an_episode():
    assert episodes([prompt("<command-name>/clear</command-name>", 0), say("ok", 1, "m1")]) == []


def test_next_skill_closes_previous_episode():
    lines = [prompt("go", 0), *skill_turn("create-skill", 10),
             skill_call("config-audit", 20, "sk2"), tool_result("sk2", 21), say("done", 22, "m9")]
    first, second = episodes(lines)
    assert first.skill == "core:create-skill" and first.end == T0 + timedelta(seconds=14)
    assert second.skill == "core:config-audit"


# --- main -------------------------------------------------------------------

def write_transcript(projects, lines, age_s=3600):
    path = projects / "-proj" / f"{SID}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    old = datetime.now(timezone.utc).timestamp() - age_s
    os.utime(path, (old, old))
    return path


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def collector():
    """A tiny local OTLP/HTTP stand-in that records posted bodies."""
    bodies = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", bodies
    server.shutdown()


def since_far_past():
    return datetime(2020, 1, 1, tzinfo=timezone.utc)


def lines_one_episode():
    return [prompt("make a skill", 0), *skill_turn(), prompt("thanks", 60)]


def test_collector_down_keeps_high_water_mark(tmp_path, capsys):
    projects = tmp_path / "projects"
    write_transcript(projects, lines_one_episode())
    state = tmp_path / "state" / "drift.json"
    state.parent.mkdir()
    state.write_text('{"version": 1, "files": {}}', encoding="utf-8")
    before = state.read_bytes()

    rc = enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                           endpoint=f"http://127.0.0.1:{closed_port()}")

    assert rc != 0
    assert "collector unreachable" in capsys.readouterr().err
    assert state.read_bytes() == before
    assert sorted(p.name for p in state.parent.iterdir()) == ["drift.json"]


def test_collector_down_without_state_writes_nothing(tmp_path):
    projects = tmp_path / "projects"
    write_transcript(projects, lines_one_episode())
    state = tmp_path / "state" / "drift.json"
    rc = enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                           endpoint=f"http://127.0.0.1:{closed_port()}")
    assert rc != 0
    assert not state.exists()


def test_posts_episode_then_advances_high_water_mark(tmp_path, collector):
    endpoint, bodies = collector
    projects = tmp_path / "projects"
    path = write_transcript(projects, lines_one_episode())
    state = tmp_path / "state" / "drift.json"

    assert enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                             endpoint=endpoint) == 0

    [(url_path, body)] = bodies
    assert url_path == "/v1/logs"
    resource = body["resourceLogs"][0]["resource"]["attributes"]
    assert {"key": "service.name", "value": {"stringValue": "claude-code"}} in resource
    [record] = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    attrs = {a["key"]: next(iter(a["value"].values())) for a in record["attributes"]}
    assert attrs["event.name"] == "cta.skill_episode"
    assert attrs["session.id"] == SID
    assert attrs["skill"] == "core:create-skill"
    assert attrs["skill_short"] == "create-skill"
    assert attrs["outcome"] == "success"
    assert attrs["signals"] == "none"
    assert attrs["turns"] == "3"
    assert attrs["duration_ms"] == "4000"
    assert attrs["start"] == "2026-01-05T10:00:10.000Z"
    assert attrs["end"] == "2026-01-05T10:00:14.000Z"

    saved = json.loads(state.read_text())
    assert saved["files"][str(path)] == "2026-01-05T10:00:10.000Z"

    # A second run finds nothing new and posts nothing.
    assert enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                             endpoint=endpoint) == 0
    assert len(bodies) == 1


def test_unsettled_episode_waits(tmp_path, collector):
    """A fresh transcript whose skill has no follow-up prompts yet is held for a later run."""
    endpoint, bodies = collector
    projects = tmp_path / "projects"
    write_transcript(projects, [prompt("make a skill", 0), *skill_turn()], age_s=10)
    state = tmp_path / "state" / "drift.json"
    assert enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                             endpoint=endpoint) == 0
    assert bodies == []
    assert not state.exists()


def test_files_older_than_since_are_skipped(tmp_path, collector):
    endpoint, bodies = collector
    projects = tmp_path / "projects"
    write_transcript(projects, lines_one_episode(), age_s=7200)
    state = tmp_path / "state" / "drift.json"
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    assert enrich_drift.main(since, projects=projects, state_path=state, endpoint=endpoint) == 0
    assert bodies == []


def test_parse_since():
    now = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
    assert enrich_drift.parse_since("1h", now) == now - timedelta(hours=1)
    assert enrich_drift.parse_since("26h", now) == now - timedelta(hours=26)
    assert enrich_drift.parse_since("7d", now) == now - timedelta(days=7)
    assert enrich_drift.parse_since("30m", now) == now - timedelta(minutes=30)
    with pytest.raises(ValueError):
        enrich_drift.parse_since("yesterday", now)


# --- fix round 1 ------------------------------------------------------------

@pytest.mark.parametrize("content", [b"{not json", b"[]", b'{"files": []}', b"\xff\xfe\x00"])
def test_corrupt_state_fails_loud_and_posts_nothing(tmp_path, collector, capsys, content):
    endpoint, bodies = collector
    projects = tmp_path / "projects"
    write_transcript(projects, lines_one_episode())
    state = tmp_path / "state" / "drift.json"
    state.parent.mkdir()
    state.write_bytes(content)

    rc = enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                           endpoint=endpoint)

    assert rc != 0
    err = capsys.readouterr().err
    assert "unreadable state" in err and str(state) in err
    assert bodies == []
    assert state.read_bytes() == content
    assert sorted(p.name for p in state.parent.iterdir()) == ["drift.json"]


@pytest.fixture
def failing_collector():
    """An OTLP stand-in that answers every POST with HTTP 500."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_collector_http_error_keeps_high_water_mark(tmp_path, failing_collector, capsys):
    projects = tmp_path / "projects"
    write_transcript(projects, lines_one_episode())
    state = tmp_path / "state" / "drift.json"
    state.parent.mkdir()
    state.write_text('{"version": 1, "files": {}}', encoding="utf-8")
    before = state.read_bytes()

    rc = enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                           endpoint=failing_collector)

    assert rc == 1
    assert "rejected" in capsys.readouterr().err
    assert state.read_bytes() == before
    assert sorted(p.name for p in state.parent.iterdir()) == ["drift.json"]


def test_partial_batch_marks_settled_episode_then_posts_rest(tmp_path, collector):
    endpoint, bodies = collector
    projects = tmp_path / "projects"
    # First skill has two follow-ups (settled); the second has none and the file is fresh.
    lines = [prompt("make a skill", 0), *skill_turn("create-skill", 10), prompt("thanks", 60),
             prompt("now audit", 70), skill_call("config-audit", 80, "sk2"),
             tool_result("sk2", 81), say("audited", 82, "m9")]
    path = write_transcript(projects, lines, age_s=10)
    state = tmp_path / "state" / "drift.json"

    assert enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                             endpoint=endpoint) == 0
    [(_, body)] = bodies
    [record] = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    assert {"key": "skill", "value": {"stringValue": "core:create-skill"}} in record["attributes"]
    assert json.loads(state.read_text())["files"][str(path)] == "2026-01-05T10:00:10.000Z"

    # Later, once the transcript has gone idle, the held episode posts on its own.
    old = datetime.now(timezone.utc).timestamp() - 3600
    os.utime(path, (old, old))
    assert enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                             endpoint=endpoint) == 0
    assert len(bodies) == 2
    [record] = bodies[1][1]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    assert {"key": "skill", "value": {"stringValue": "core:config-audit"}} in record["attributes"]
    assert json.loads(state.read_text())["files"][str(path)] == "2026-01-05T10:01:20.000Z"


def test_prompt_and_response_text_never_posted(tmp_path, collector):
    endpoint, bodies = collector
    canary = "CANARY-7f3a91c2"
    projects = tmp_path / "projects"
    lines = [prompt(f"make a skill {canary}", 0), skill_call("create-skill", 10),
             tool_result("sk1", 11, f"Launching {canary}"), skill_base(11),
             tool_use("t1", 12), tool_result("t1", 13, f"file says {canary}"),
             say(f"Here you go {canary}", 14, "m-end"), prompt(f"no, {canary}", 60),
             prompt(f"ok {canary}", 70)]
    write_transcript(projects, lines)
    state = tmp_path / "state" / "drift.json"

    assert enrich_drift.main(since_far_past(), projects=projects, state_path=state,
                             endpoint=endpoint) == 0
    [(_, body)] = bodies
    assert canary not in json.dumps(body)
    assert "drifted" in json.dumps(body)
