#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""UserPromptSubmit hook: record when the current turn started.

The notify hook compares this timestamp with the time a turn ends, so it can stay
silent for short turns. Each run also removes turn records older than 24 hours
(stale sessions that never reached Stop), checking at most PRUNE_LIMIT entries.
Prints nothing (UserPromptSubmit stdout is added to the
model's context), always exits 0, and fails open.
"""

from __future__ import annotations

import json
import os
import sys
import time
from itertools import islice
from pathlib import Path
from os import getpid, replace

sys.path.insert(0, str(Path(__file__).resolve().parent))

PRUNE_LIMIT = 200


def _prune(turns: Path, now: float, max_age: float) -> None:
    """Remove turn records older than max_age; examine at most PRUNE_LIMIT entries."""
    with os.scandir(turns) as entries:
        for entry in islice(entries, PRUNE_LIMIT):
            try:
                if entry.is_file(follow_symlinks=False) and now - entry.stat().st_mtime > max_age:
                    os.unlink(entry.path)
            except OSError:
                pass


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
        _prune(target.parent, time.time(), cta_config.TURN_STALE_SECONDS)
    except Exception:  # fail open: recording a timestamp must never interrupt work
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
