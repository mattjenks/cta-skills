import plistlib
import re
from pathlib import Path

LD = Path(__file__).resolve().parent.parent / "launchd"
EXPECT = {
    "net.cta.telemetry-backup": ({"Hour": 2, "Minute": 30}, "backup.py", []),
    "net.cta.drift-enrich": ({"Hour": 2, "Minute": 0}, "enrich_drift.py", ["--since", "26h"]),
    "net.cta.telemetry-health": (None, "health_check.py", []),
}


def load(label):
    with open(LD / f"{label}.plist", "rb") as fh:
        return plistlib.load(fh)


def test_plists():
    for label, (interval, script, extra) in EXPECT.items():
        p = load(label)
        assert p["Label"] == label
        env = p["EnvironmentVariables"]
        assert env["CTA_UNATTENDED"] == "1"
        assert "/opt/homebrew/bin" in env["PATH"]
        assert "__HOME__/.local/bin" in env["PATH"]
        assert p["StandardOutPath"] == f"__HOME__/.local/share/cta/logs/{label}.log"
        assert p["StandardErrorPath"] == p["StandardOutPath"]
        args = p["ProgramArguments"]
        assert args[:2] == ["/usr/bin/env", "uv"]
        assert args[1:] == ["uv", "run", "--script", f"__REPO__/telemetry/{script}", *extra]
        if interval is None:
            assert p["RunAtLoad"] is True
            assert "StartCalendarInterval" not in p
        else:
            assert p["StartCalendarInterval"] == interval
            assert not p.get("RunAtLoad")


def test_no_personal_paths():
    for f in LD.iterdir():
        text = f.read_text()
        assert not re.search(r"/Users/|/home/|@", text), f.name
