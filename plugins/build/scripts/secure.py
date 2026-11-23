#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Branch security scan for `/build:secure`: run the scanners, write or refresh the findings record.

  secure.py scan --repo R --base B --out FILE   full_scan of B..HEAD; writes head and diff_hash
  secure.py verify --repo R --base B --file FILE  record current and everything resolved (exit 0, 4, 5, 6)

Exit 0 ok, 2 bad input, 3 STOP: a scanner is missing or failed (the install command is printed,
nothing is written, nothing is skipped). A rescan is the only way head and diff_hash change, so they
always describe a tree the scanners saw. Rescan rules for findings already in FILE: a rediscovered
`fixed` reopens to `open`; `false-positive`, `accepted-risk` and `proposed-false-positive` are never
changed; entries not rediscovered are kept as they are and listed as "not rediscovered".
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import findings
import scan

INSTALL = {
    "semgrep": "brew install semgrep",
    "gitleaks": "brew install gitleaks",
    "pip-audit": "uv tool install pip-audit",
    "osv-scanner": "brew install osv-scanner",
    "npm": "install Node.js (npm)",
}
REQUIRED = ("semgrep", "gitleaks")


def _stop(msg: str) -> int:
    print(f"secure.py: STOP: {msg}", file=sys.stderr)
    return 3


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True, env=findings.git_env()).stdout.strip()


def verify(repo: Path, base: str, path: Path) -> int:
    """What `pr` checks: the record describes the branch as it is now and nothing waits.
    0 clean; 4 missing, unreadable or stale (diff_hash differs); 5 findings still open (or closed
    without `closed_by`); 6 only `proposed-false-positive` entries wait on the owner (JSON on stdout)."""
    try:
        rec = findings.load(path)
        current = findings.diff_hash(repo, base, "HEAD")
        entries = rec["findings"]
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as err:
        print(f"secure.py: no usable security record at {path} ({err}); run /build:secure", file=sys.stderr)
        return 4
    if rec.get("diff_hash") != current:
        print("secure.py: security.json diff_hash does not match the branch head; re-run /build:secure",
              file=sys.stderr)
        return 4
    blocking = [f for f in entries if f.get("status") == "open"
                or (f.get("status") in findings.MATT_ONLY and not f.get("closed_by"))
                or f.get("status") not in findings.ASSISTANT_STATUSES | findings.MATT_ONLY]
    if blocking:
        print("secure.py: findings still open: " + ", ".join(str(f.get("id")) for f in blocking), file=sys.stderr)
        return 5
    proposed = [f for f in entries if f.get("status") == "proposed-false-positive"]
    if proposed:
        print(json.dumps({"proposed": proposed}, indent=2))
        return 6
    return 0


def main(argv=None, which=shutil.which, scan_fn=scan.full_scan) -> int:
    ap = argparse.ArgumentParser(prog="secure.py", description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["scan", "verify"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out")
    ap.add_argument("--file")
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        if not a.file:
            ap.error("verify needs --file")
        return verify(Path(a.repo), a.base, Path(a.file))
    if not a.out:
        ap.error("scan needs --out")
    repo, out = Path(a.repo), Path(a.out)
    try:
        dhash, head = findings.diff_hash(repo, a.base, "HEAD"), _head(repo)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as err:
        print(f"secure.py: {err}", file=sys.stderr)
        return 2
    missing = scan.missing_scanners(list(REQUIRED), which)
    if missing:
        return _stop("install " + "; ".join(f"{m}: {INSTALL[m]}" for m in missing))
    try:
        found = scan_fn(repo, a.base)
    except scan.ScanError as err:
        tip = INSTALL.get(err.tool)
        return _stop(f"{err}" + (f" (install: {tip})" if tip else ""))
    rec = findings.new_record(a.base, head, dhash, found)
    lost: list[str] = []
    if out.is_file():
        try:
            old = {f["id"]: f for f in findings.load(out)["findings"]}
        except (ValueError, KeyError, TypeError):
            print(f"secure.py: {out} is not valid JSON in the findings format; fix or remove it",
                  file=sys.stderr)
            return 2
        merged = []
        for f in rec["findings"]:
            prev = old.get(f["id"])
            if prev is None:
                merged.append(f)
            else:
                merged.append({**prev, "status": "open"} if prev.get("status") == "fixed" else prev)
        fresh = {f["id"] for f in rec["findings"]}
        kept = [f for i, f in old.items() if i not in fresh]
        lost = [f["id"] for f in kept]
        rec["findings"] = merged + kept
    findings.save(out, rec)
    if lost:
        print("not rediscovered (left as they are): " + ", ".join(lost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
