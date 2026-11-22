#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
# Adapted from coleam00/skills hooks/stop_notify.py (MIT)
"""Stop and Notification hook: raise a macOS notification titled with the persona name.

Stop: "Done". Notification: the event's own message, truncated to 120 characters.
The title is the first `# ` heading of the configured persona file, or "CTA".

Always exits 0 and never blocks. Does nothing outside macOS, and stands down when
`stop_hook_active` is set so a Stop hook cannot notify in a loop.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FALLBACK_TITLE = "CTA"
MESSAGE_CHARS = 120


def _clean(text: str) -> str:
    """Single line, so the AppleScript string literal stays valid."""
    return text.replace("\r", " ").replace("\n", " ")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _title() -> str:
    try:
        import cta_config

        persona = cta_config.load_config().persona
        for line in persona.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip() or FALLBACK_TITLE
    except Exception:  # missing persona, unreadable file, or no heading
        pass
    return FALLBACK_TITLE


def notification_args(event: dict) -> list[str]:
    """Return the osascript argv that shows the notification for this event."""
    message = "Done"
    if event.get("hook_event_name") == "Notification":
        raw = event.get("message")
        message = raw if isinstance(raw, str) and raw.strip() else "Needs your input"
    message = _clean(message)[:MESSAGE_CHARS]
    title = _clean(_title())
    script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    return ["osascript", "-e", script]


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or data.get("stop_hook_active"):
            return 0
        if platform.system() != "Darwin":
            return 0
        subprocess.run(notification_args(data), timeout=5, check=False)
    except Exception:  # fail open: a notification must never interrupt work
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
