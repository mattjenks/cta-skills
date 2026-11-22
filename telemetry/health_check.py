#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Login health check: wait up to 5 minutes for Docker, then run smoke_test.py.

Exit 0 and print one line on success. On any failure, raise a macOS notification
and exit 1. Never notifies on success.
"""
import subprocess
import sys
import time
from pathlib import Path

WAIT_S = 300
POLL_S = 10
SMOKE = Path(__file__).resolve().parent / "smoke_test.py"


def notify(run, reason: str) -> None:
    script = f'display notification "{reason}" with title "CTA telemetry"'
    try:
        run(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def docker_ready(run) -> bool:
    try:
        r = run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(run=subprocess.run, sleep=time.sleep, clock=time.monotonic) -> int:
    start = clock()
    while not docker_ready(run):
        if clock() - start >= WAIT_S:
            notify(run, "Docker did not start within 5 minutes")
            print("docker not ready after 5 minutes", file=sys.stderr)
            return 1
        sleep(POLL_S)
    try:
        r = run(["uv", "run", "--script", str(SMOKE)], capture_output=True, text=True, timeout=180)
        rc, err = r.returncode, (r.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        rc, err = 1, str(exc)
    if rc != 0:
        notify(run, "Smoke test failed; stack is not healthy")
        print(f"smoke test failed (exit {rc}): {err}", file=sys.stderr)
        return 1
    print("CTA telemetry healthy: docker up, smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
