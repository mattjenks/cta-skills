#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Scanner wrapper: language detection, scanner argv, normalized findings.

Stdlib only. Scanners run as argv lists (never a shell). A scanner that fails
or prints unparseable output raises ScanError; it is never "no findings".
Matched secret values from gitleaks are dropped at normalization.

Output formats relied on (tool documentation):
  semgrep --json         results[].check_id, path, start.line, extra.severity, extra.message
  gitleaks --report-format json   [ {RuleID, File, StartLine, Description, ...} ]
  pip-audit -f json      dependencies[].name/version/vulns[].id/description
  osv-scanner --format json   results[].source.path, packages[].package, vulnerabilities[]
  npm audit --json       vulnerabilities{name: {severity, via[]}}
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from findings import Finding

SCANNERS = {
    "semgrep": ["semgrep", "--config", "p/default", "--error", "--json"],
    "gitleaks": [
        "gitleaks", "git", "--report-format", "json", "--report-path", "-",
        "--redact", "--no-banner", "--no-color",
    ],
    "pip-audit": ["pip-audit", "-f", "json"],
    "osv-scanner": ["osv-scanner", "--format", "json"],
    "npm": ["npm", "audit", "--json"],
}

_EXT = {
    ".py": "python",
    ".js": "node", ".jsx": "node", ".ts": "node", ".tsx": "node", ".mjs": "node", ".cjs": "node",
    ".go": "go",
    ".rb": "ruby",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
}
_MANIFEST = {
    "pyproject.toml": "python", "setup.py": "python", "setup.cfg": "python",
    "package.json": "node", "package-lock.json": "node", "yarn.lock": "node", "pnpm-lock.yaml": "node",
    "go.mod": "go", "go.sum": "go",
    "Gemfile": "ruby", "Gemfile.lock": "ruby",
}

_SEVERITY = {
    "critical": "critical", "high": "high", "error": "high",
    "moderate": "medium", "medium": "medium", "warning": "medium",
    "low": "low", "info": "info", "informational": "info", "note": "info",
}
_STDERR_TAIL = 2000


class ScanError(Exception):
    def __init__(self, tool: str, stderr_tail: str):
        self.tool = tool
        self.stderr_tail = (stderr_tail or "")[-_STDERR_TAIL:]
        super().__init__(f"{tool} failed: {self.stderr_tail.strip()}")


def normalize_severity(raw, default: str = "medium") -> str:
    return _SEVERITY.get(str(raw or "").strip().lower(), default)


def detect_languages(repo: Path, paths: list[str]) -> set[str]:
    """Languages by file extension and manifest (in `paths` or at the repo root)."""
    langs: set[str] = set()
    for p in paths:
        pp = Path(p)
        name = pp.name
        if name in _MANIFEST:
            langs.add(_MANIFEST[name])
        elif name.startswith("requirements") and name.endswith(".txt"):
            langs.add("python")
        elif pp.suffix in _EXT:
            langs.add(_EXT[pp.suffix])
    repo = Path(repo)
    for name, lang in _MANIFEST.items():
        if (repo / name).is_file():
            langs.add(lang)
    if any(repo.glob("requirements*.txt")):
        langs.add("python")
    return langs


def missing_scanners(needed: list[str], which=shutil.which) -> list[str]:
    return [n for n in needed if which(n) is None]


def _git(repo: Path, args: list[str], run) -> str:
    proc = run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScanError("git", proc.stderr)
    return proc.stdout


def _names(out: str) -> list[str]:
    return [n for n in out.split("\0") if n]


def _scannable(repo: Path, paths: list[str]) -> list[str]:
    """Existing, non-binary files; deleted and binary paths are skipped."""
    keep = []
    for p in paths:
        fp = Path(repo) / p
        if not fp.is_file():
            continue
        try:
            with open(fp, "rb") as fh:
                if b"\0" in fh.read(8192):
                    continue
        except OSError:
            continue
        keep.append(p)
    return keep


def _exec(tool: str, argv: list[str], repo: Path, run, ok_empty: bool = False):
    """Run a scanner; return parsed JSON. Exit 0/1 with JSON is success."""
    try:
        proc = run(argv, cwd=str(repo), capture_output=True, text=True)
    except FileNotFoundError:
        raise ScanError(tool, f"{argv[0]} is not installed") from None
    out = (proc.stdout or "").strip()
    if proc.returncode not in (0, 1):
        raise ScanError(tool, proc.stderr or out)
    if not out:
        if ok_empty and proc.returncode == 0:
            return None
        raise ScanError(tool, proc.stderr or "empty output")
    try:
        return json.loads(out)
    except ValueError:
        raise ScanError(tool, proc.stderr or "unparseable output") from None


def _semgrep(repo: Path, paths: list[str], run) -> list[Finding]:
    if not paths:
        return []
    data = _exec("semgrep", [*SCANNERS["semgrep"], *paths], repo, run)
    if not isinstance(data, dict) or "results" not in data:
        raise ScanError("semgrep", "unexpected output shape")
    found = []
    for r in data["results"]:
        extra = r.get("extra", {})
        found.append(Finding.create(
            "semgrep", r.get("check_id", "unknown"), r.get("path", ""),
            r.get("start", {}).get("line", 0),
            normalize_severity(extra.get("severity")), extra.get("message", ""),
        ))
    return found


def _gitleaks(repo: Path, run, log_opts: str | None = None) -> list[Finding]:
    argv = list(SCANNERS["gitleaks"])
    if log_opts:
        argv += ["--log-opts", log_opts]
    else:
        argv.append("--staged")
    argv.append(str(repo))
    data = _exec("gitleaks", argv, repo, run, ok_empty=True)
    if data is None:
        data = []
    if not isinstance(data, list):
        raise ScanError("gitleaks", "unexpected output shape")
    # Only rule, file, line and the rule description are read: Secret/Match are dropped.
    return [
        Finding.create("gitleaks", r.get("RuleID", "unknown"), r.get("File", ""),
                       r.get("StartLine", 0), "high", r.get("Description", ""))
        for r in data
    ]


def fast_scan(repo: Path, staged: bool = True, run=subprocess.run) -> list[Finding]:
    """Pre-commit scan: semgrep on the staged files plus gitleaks over the staged diff."""
    repo = Path(repo)
    if not staged:
        raise ValueError("fast_scan scans staged changes only; use full_scan for a branch")
    names = _names(_git(repo, ["diff", "--cached", "--name-only", "-z",
                               "--diff-filter=ACMR"], run))
    return [*_semgrep(repo, _scannable(repo, names), run), *_gitleaks(repo, run)]


def _pip_audit(repo: Path, run) -> list[Finding]:
    argv = list(SCANNERS["pip-audit"])
    reqs = sorted(p.name for p in repo.glob("requirements*.txt"))
    if reqs:
        for r in reqs:
            argv += ["-r", r]
        manifest = reqs[0]
    else:
        argv.append(".")
        manifest = "pyproject.toml"
    data = _exec("pip-audit", argv, repo, run)
    deps = data.get("dependencies") if isinstance(data, dict) else None
    if deps is None:
        raise ScanError("pip-audit", "unexpected output shape")
    found = []
    for d in deps:
        for v in d.get("vulns", []):
            fixes = ", ".join(v.get("fix_versions") or [])
            msg = f"{d.get('name')} {d.get('version')}: {v.get('description') or v.get('id')}"
            if fixes:
                msg += f" (fix: {fixes})"
            found.append(Finding.create("pip-audit", v.get("id", "unknown"), manifest, 0, "high", msg))
    return found


def _npm_audit(repo: Path, run) -> list[Finding]:
    data = _exec("npm", SCANNERS["npm"], repo, run)
    if not isinstance(data, dict) or "error" in data or "vulnerabilities" not in data:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise ScanError("npm", str(err.get("summary") or err or "unexpected output shape"))
    found = []
    for name, v in data["vulnerabilities"].items():
        titles = [x.get("title") for x in v.get("via", []) if isinstance(x, dict) and x.get("title")]
        msg = f"{name}: {titles[0] if titles else 'vulnerable dependency'}"
        found.append(Finding.create("npm", name, "package.json", 0,
                                    normalize_severity(v.get("severity"), "high"), msg))
    return found


def _osv(repo: Path, run) -> list[Finding]:
    data = _exec("osv-scanner", [*SCANNERS["osv-scanner"], "-r", "."], repo, run)
    if not isinstance(data, dict):
        raise ScanError("osv-scanner", "unexpected output shape")
    found = []
    for res in data.get("results") or []:
        src = res.get("source", {}).get("path", "")
        for pk in res.get("packages", []):
            pkg = pk.get("package", {})
            for v in pk.get("vulnerabilities", []):
                sev = (v.get("database_specific") or {}).get("severity")
                msg = f"{pkg.get('name')} {pkg.get('version')}: {v.get('summary') or v.get('id')}"
                found.append(Finding.create("osv-scanner", v.get("id", "unknown"), src, 0,
                                            normalize_severity(sev, "high"), msg))
    return found


def full_scan(repo: Path, base: str, run=subprocess.run, which=shutil.which) -> list[Finding]:
    """Branch scan: semgrep on the diff's files, gitleaks over base..HEAD, dependency audit."""
    repo = Path(repo)
    names = _names(_git(repo, ["diff", "--name-only", "-z", "--diff-filter=ACMR",
                               f"{base}..HEAD"], run))
    found = [*_semgrep(repo, _scannable(repo, names), run),
             *_gitleaks(repo, run, log_opts=f"{base}..HEAD")]
    langs = detect_languages(repo, names)
    if "python" in langs:
        found += _pip_audit(repo, run)
    need_osv = bool(langs & {"go", "ruby"})
    if "node" in langs:
        if which("npm"):
            found += _npm_audit(repo, run)
        else:
            need_osv = True
    if need_osv:
        found += _osv(repo, run)
    return found
