#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Send one OTLP log and one counter metric to the local collector and assert
they land in Loki and Prometheus, and that today's archive grew.

Exit 0 on success, 1 on any failure.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

OTLP = "http://127.0.0.1:4318"
LOKI = "http://127.0.0.1:3100"
PROM = "http://127.0.0.1:9090"
DATA = Path(os.environ.get("CTA_DATA", Path.home() / ".local/share/cta/telemetry"))
ARCHIVE = DATA / "archive"
TIMEOUT_S = 60


def post(path: str, body: dict) -> None:
    req = urllib.request.Request(
        OTLP + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10).read()


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def archive_size() -> int:
    """Total bytes of archive files last modified today."""
    today = date.today()
    total = 0
    for p in ARCHIVE.glob("otel*"):
        try:
            if date.fromtimestamp(p.stat().st_mtime) == today:
                total += p.stat().st_size
        except OSError:
            pass
    return total


def attrs(**kv):
    return [{"key": k, "value": {"stringValue": v}} for k, v in kv.items()]


def main() -> int:
    marker = f"smoke-{int(time.time())}"
    now_ns = time.time_ns()
    resource = {"attributes": attrs(**{"service.name": "cta-smoke"})}
    before = archive_size()
    try:
        post("/v1/logs", {"resourceLogs": [{
            "resource": resource,
            "scopeLogs": [{"logRecords": [{
                "timeUnixNano": str(now_ns),
                "severityText": "INFO",
                "body": {"stringValue": "cta smoke"},
                "attributes": attrs(**{"event.name": "cta.smoke", "marker": marker}),
            }]}],
        }]})
        post("/v1/metrics", {"resourceMetrics": [{
            "resource": resource,
            "scopeMetrics": [{"metrics": [{
                "name": "cta_smoke",
                "sum": {
                    "aggregationTemporality": 2,
                    "isMonotonic": True,
                    "dataPoints": [{
                        "timeUnixNano": str(now_ns),
                        "startTimeUnixNano": str(now_ns - 1_000_000_000),
                        "asInt": "1",
                    }],
                },
            }]}],
        }]})
    except (urllib.error.URLError, OSError) as e:
        print(f"FAIL: collector unreachable at {OTLP} ({e})")
        return 1

    found_log = found_metric = grew = False
    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        if not found_log:
            q = urllib.parse.urlencode({
                "query": '{service_name="cta-smoke"} | event_name="cta.smoke"'
                         f' | marker="{marker}"',
                "start": str(now_ns - 60_000_000_000),
                "end": str(time.time_ns() + 60_000_000_000),
                "limit": "5",
            })
            try:
                res = get_json(f"{LOKI}/loki/api/v1/query_range?{q}")
                found_log = bool(res["data"]["result"])
            except (urllib.error.URLError, OSError, KeyError, ValueError):
                pass
        if not found_metric:
            q = urllib.parse.urlencode({"query": "cta_smoke_total"})
            try:
                res = get_json(f"{PROM}/api/v1/query?{q}")
                found_metric = bool(res["data"]["result"])
            except (urllib.error.URLError, OSError, KeyError, ValueError):
                pass
        grew = grew or archive_size() > before
        if found_log and found_metric and grew:
            print("OK: log in Loki, metric in Prometheus, archive grew")
            return 0
        time.sleep(2)

    missing = [n for n, ok in (("log not in Loki", found_log),
                               ("metric not in Prometheus", found_metric),
                               (f"archive did not grow ({ARCHIVE})", grew)) if not ok]
    print("FAIL: " + "; ".join(missing))
    return 1


if __name__ == "__main__":
    sys.exit(main())
