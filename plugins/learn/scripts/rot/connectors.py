"""MCP servers that did not connect this week."""

from __future__ import annotations

from collections import Counter

import sanitize
from model import RotItem
from rot import _common

KIND = "broken"


def check(week, cfg) -> list[RotItem]:
    counts: Counter[tuple[str, str]] = Counter()
    for event in week.events.get("mcp_server_connection", []):
        status = str(event.get("status", "")).strip().lower()
        server = sanitize.name(event.get("server_name"))
        if server and status and status != "connected":
            counts[(server, status)] += 1
    return [_common.item("broken", server, f"{n} connection attempts ended {sanitize.name(status)}",
                         "check the server's configuration or sign in again")
            for (server, status), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
