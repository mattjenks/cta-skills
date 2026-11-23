import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import retro_event

FIELDS = {
    "slug": "app", "topic": "login", "size": "normal", "tasks": 4, "fix_rounds": 2,
    "findings_critical": 0, "findings_important": 1, "findings_minor": 3,
    "gates": ["secure", "validate"], "rating": 4,
}


def attrs(event):
    rec = event["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    return rec, {a["key"]: a["value"] for a in rec["attributes"]}


def test_build_event_fields():
    rec, a = attrs(retro_event.build_event(FIELDS))
    assert a["event.name"] == {"stringValue": "cta.build"}
    assert a["slug"] == {"stringValue": "app"}
    assert a["topic"] == {"stringValue": "login"}
    assert a["size"] == {"stringValue": "normal"}
    assert a["tasks"] == {"intValue": "4"}
    assert a["fix_rounds"] == {"intValue": "2"}
    assert a["findings_critical"] == {"intValue": "0"}
    assert a["findings_important"] == {"intValue": "1"}
    assert a["findings_minor"] == {"intValue": "3"}
    assert a["gates"] == {"stringValue": "secure,validate"}
    assert a["rating"] == {"stringValue": "4"}
    assert rec["timeUnixNano"].isdigit()


def test_rating_empty_when_declined_and_gates_string_kept():
    _, a = attrs(retro_event.build_event({**FIELDS, "rating": None, "gates": "a,b"}))
    assert a["rating"] == {"stringValue": ""}
    assert a["gates"] == {"stringValue": "a,b"}


@pytest.mark.parametrize("bad", [{"size": "huge"}, {"rating": 6}, {"rating": 0}, {"tasks": -1}, {"slug": ""}])
def test_invalid_fields_rejected(bad):
    with pytest.raises(ValueError):
        retro_event.build_event({**FIELDS, **bad})


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_send_unreachable_exits_1(tmp_path, capsys):
    f = tmp_path / "retro.json"
    f.write_text(json.dumps(FIELDS))
    rc = retro_event.main(["--file", str(f), "--endpoint", f"http://127.0.0.1:{free_port()}/v1/logs"])
    assert rc == 1
    assert "collector" in capsys.readouterr().err.lower()


def test_send_posts_json_to_logs_path(tmp_path):
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got["path"] = self.path
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.handle_request)
    t.start()
    f = tmp_path / "retro.json"
    f.write_text(json.dumps(FIELDS))
    rc = retro_event.main(["--file", str(f), "--endpoint", f"http://127.0.0.1:{srv.server_port}/v1/logs"])
    t.join(5)
    srv.server_close()
    assert rc == 0 and got["path"] == "/v1/logs"
    assert "resourceLogs" in got["body"]


def test_default_endpoint_is_local_collector():
    assert retro_event.ENDPOINT == "http://127.0.0.1:4318/v1/logs"


def test_bad_file_exits_2(tmp_path):
    f = tmp_path / "retro.json"
    f.write_text("not json")
    assert retro_event.main(["--file", str(f)]) == 2
