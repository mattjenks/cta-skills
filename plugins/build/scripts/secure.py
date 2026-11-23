#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Branch security scan for `/build:secure`: run the scanners, write or refresh the findings record.

  secure.py scan  --repo R --base B --out FILE   full_scan of B..HEAD, record with diff_hash
  secure.py stamp --repo R --base B --out FILE   refresh head and diff_hash after fixes

Exit 0 ok, 2 bad input, 3 STOP: a scanner is missing or failed (the install command is printed,
nothing is written, nothing is skipped). Findings already in FILE keep their status; this script
only ever writes `open` for new findings (the assistant may not write the owner-only statuses).
"""

from __future__ import annotations

import argparse
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


def main(argv=None, which=shutil.which, scan_fn=scan.full_scan) -> int:
    ap = argparse.ArgumentParser(prog="secure.py", description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["scan", "stamp"])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    repo, out = Path(a.repo), Path(a.out)
    try:
        dhash, head = findings.diff_hash(repo, a.base, "HEAD"), _head(repo)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as err:
        print(f"secure.py: {err}", file=sys.stderr)
        return 2
    if a.cmd == "stamp":
        if not out.is_file():
            print(f"secure.py: no record at {out}", file=sys.stderr)
            return 2
        rec = findings.load(out)
        rec.update(base=a.base, head=head, diff_hash=dhash)
        findings.save(out, rec)
        return 0
    missing = scan.missing_scanners(list(REQUIRED), which)
    if missing:
        return _stop("install " + "; ".join(f"{m}: {INSTALL[m]}" for m in missing))
    try:
        found = scan_fn(repo, a.base)
    except scan.ScanError as err:
        tip = INSTALL.get(err.tool)
        return _stop(f"{err}" + (f" (install: {tip})" if tip else ""))
    rec = findings.new_record(a.base, head, dhash, found)
    if out.is_file():
        old = {f["id"]: f for f in findings.load(out)["findings"]}
        fresh = {f["id"] for f in rec["findings"]}
        rec["findings"] = [old.get(f["id"], f) for f in rec["findings"]] + [
            f for i, f in old.items() if i not in fresh]
    findings.save(out, rec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
