#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""UserPromptSubmit hook: record when the current turn started.

The notify hook compares this timestamp with the time a turn ends, so it can stay
silent for short turns. Prints nothing (UserPromptSubmit stdout is added to the
model's context), always exits 0, and fails open.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from os import getpid, replace

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    try:
        import cta_config

        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return 0
        target = cta_config.turn_file(data.get("session_id"))
        if target is None:
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{getpid()}.tmp")
        tmp.write_text(repr(time.time()), encoding="utf-8")
        replace(tmp, target)
    except Exception:  # fail open: recording a timestamp must never interrupt work
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
