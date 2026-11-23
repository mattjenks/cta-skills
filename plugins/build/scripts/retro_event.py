#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Send the `cta.build` retro event to the local OTLP collector.

Usage: retro_event.py --file <retro-fields.json> [--endpoint URL]

Stdlib only. Exit 0 sent; 1 collector unreachable or it rejected the event with an HTTP error (the build is not blocked); 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:4318/v1/logs"
INT_FIELDS = ("tasks", "fix_rounds", "findings_critical", "findings_important", "findings_minor")


def _text(key: str, value) -> dict:
    return {"key": key, "value": {"stringValue": str(value)}}


def _int(key: str, value) -> dict:
    return {"key": key, "value": {"intValue": str(value)}}


def build_event(fields: dict) -> dict:
    """OTLP/HTTP JSON log body for one build. Raises ValueError on a bad field."""
    for key in ("slug", "topic"):
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if fields.get("size") not in ("small", "normal"):
        raise ValueError("size must be small or normal")
    counts = {}
    for key in INT_FIELDS:
        value = fields.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        counts[key] = value
    gates = fields.get("gates") or []
    gates = gates if isinstance(gates, str) else ",".join(str(g) for g in gates)
    rating = fields.get("rating")
    if rating in (None, ""):
        rating = ""
    elif isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValueError("rating must be 1 to 5 or empty")
    attributes = [
        _text("event.name", "cta.build"),
        _text("slug", fields["slug"]),
        _text("topic", fields["topic"]),
        _text("size", fields["size"]),
        *(_int(k, v) for k, v in counts.items()),
        _text("gates", gates),
        _text("rating", rating),
    ]
    return {"resourceLogs": [{
        "resource": {"attributes": [_text("service.name", "cta-build")]},
        "scopeLogs": [{"logRecords": [{
            "timeUnixNano": str(time.time_ns()),
            "severityText": "INFO",
            "body": {"stringValue": "cta build retro"},
            "attributes": attributes,
        }]}],
    }]}


def send(event: dict, endpoint: str = ENDPOINT, timeout: float = 5.0) -> None:
    req = urllib.request.Request(
        endpoint, data=json.dumps(event).encode(), headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=timeout).read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="retro_event.py", description=__doc__.splitlines()[0])
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--endpoint", default=ENDPOINT)
    a = ap.parse_args(argv)
    try:
        event = build_event(json.loads(a.file.read_text()))
    except (OSError, ValueError, AttributeError) as err:
        print(f"retro_event.py: {err}", file=sys.stderr)
        return 2
    try:
        send(event, a.endpoint)
    except urllib.error.HTTPError as err:
        print(f"retro_event.py: collector rejected the event: HTTP {err.code} ({err.reason}) at {a.endpoint}",
              file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, TimeoutError) as err:
        print(f"retro_event.py: collector unreachable at {a.endpoint} ({err}); event not sent",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
