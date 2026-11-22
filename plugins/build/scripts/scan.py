#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Scanner wrapper: language detection, scanner argv, normalized findings.

Stdlib only. Scanners run as argv lists (never a shell) and fail closed: a
scanner that fails, prints unparseable output, reports errors, or reports a
failing exit with no findings raises ScanError. It is never "no findings".

What is scanned:
  fast_scan  the STAGED content (index blobs exported to a temp dir), not the
             working tree; gitleaks reads the staged diff itself.
  full_scan  the committed `head` tree (exported through a temporary index);
             gitleaks reads base..head history.
Binary files (any NUL byte in the first 8 KB, which includes UTF-16 text) and
symlinks are not given to semgrep. A semgrep `.semgrepignore` is always
overwritten with an empty one in the export, so repository content cannot hide
files. Paths are passed as `./<path>` so a file name can never act as an option.

Semgrep: any entry in `errors[]` (any level) raises ScanError; each entry in
`paths.skipped` becomes a `high` finding (rule `semgrep.skipped-target`) so an
unscanned file is visible and must be closed by a person. Error text never
includes stdout (it can hold matched source); only stderr or a fixed string.

Dependency audits: every recognized manifest or lockfile at ANY depth of the
scanned tree is accounted for, each covered only by an auditor that reads it:
  pip-audit      each requirements*.txt (case-insensitive, or any .txt in a
                 requirements/ dir), one run per file; a root pyproject.toml that
                 has a `[project]` table (`pip-audit .`; pip-audit errors without one)
  npm audit      a root package-lock.json / npm-shrinkwrap.json
  osv-scanner -r requirements.txt, poetry/uv/pdm/Pipfile/package/npm-shrinkwrap/
                 yarn/pnpm/Cargo/composer/Gemfile locks, go.mod, pom.xml,
                 gradle.lockfile (pdm.lock and uv.lock support is from memory of
                 osv-scanner's docs, unverified)
Lockfiles are never "covered" by pip-audit. A source manifest (package.json,
pyproject.toml, Gemfile, Cargo.toml, composer.json, Pipfile, build.gradle*,
requirements.in) is covered when a covered lockfile sits in its directory or an
ancestor. Everything else (setup.py, a lone Cargo.toml, any manifest when osv-scanner
is missing) becomes a `high` finding `audit.not-audited:<path>`. Symlinks are
removed from the export before any audit runs; a symlinked manifest is reported
as not audited. A covering tool that fails raises ScanError.

Not scanned but reported: NUL-containing files (this includes UTF-16 text) are
`high` `scan.skipped-binary:<path>`; known media/archive/font extensions are
`info` with the same rule; symlinks are `info` `scan.skipped-symlink:<path>`;
other non-regular entries (submodule gitlinks) are `info` `scan.skipped-other:<path>`.
`.gitignore`/`.semgrepignore`/`.gitleaksignore`/`.gitleaks.toml` files are removed
from the export (any depth). Semgrep runs with `--disable-nosem` so inline
`nosemgrep` comments in the repository cannot hide findings.

gitleaks never uses the user's working tree as its source, because it reads
`<source>/.gitleaksignore` regardless of --config. fast_scan runs `gitleaks dir`
over the index export (ignore/config files deleted); full_scan runs `gitleaks git`
with `--log-opts=<base-sha>..<head-sha>` in a throwaway `git clone --no-checkout
--no-local`. Both use the bundled `gitleaks.toml` (`--config` outranks a repo's own
.gitleaks.toml; it extends the default rules), `--gitleaks-ignore-path` at an empty
dir and `--ignore-gitleaks-allow`. A changed `.gitleaks.toml`/`.gitleaksignore` in the
scanned diff is a `high` finding `gitleaks.config-changed`. From the gitleaks
README: flags --config, --gitleaks-ignore-path, --ignore-gitleaks-allow exist; config
order is flag, GITLEAKS_CONFIG, GITLEAKS_CONFIG_TOML, repo .gitleaks.toml; no
--no-config flag; `[extend] useDefault = true` extends the defaults. gitleaks always
writes its report ("[]" when clean); a missing or empty report is a ScanError.

The git top-level of `repo` is resolved first (a subdirectory is never scanned alone).

Output formats relied on (tool documentation):
  semgrep --json         results[].check_id, path, start.line, extra.severity, extra.message;
                         errors[]; paths.skipped[]
  gitleaks --report-format json   [ {RuleID, File, StartLine, Description, ...} ]
  pip-audit -f json      dependencies[].name/version/vulns[]/skip_reason
  osv-scanner --format json   results[].source.path, packages[].package, vulnerabilities[]
  npm audit --json       vulnerabilities{name: {severity, via[{source,title,url}]}}
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

from findings import Finding, check_ref, toplevel

SCANNERS = {
    "semgrep": ["semgrep", "--config", "p/default", "--error", "--json", "--disable-nosem"],
    "gitleaks": [
        "gitleaks", "git", "--report-format", "json", "--redact", "--no-banner", "--no-color",
        "--ignore-gitleaks-allow",
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
    "uv.lock": "python", "poetry.lock": "python",
    "package.json": "node", "package-lock.json": "node", "npm-shrinkwrap.json": "node",
    "yarn.lock": "node", "pnpm-lock.yaml": "node",
    "go.mod": "go", "go.sum": "go",
    "Gemfile": "ruby", "Gemfile.lock": "ruby",
}

_SEVERITY = {
    "critical": "critical", "high": "high", "error": "high",
    "moderate": "medium", "medium": "medium", "warning": "medium",
    "low": "low", "info": "info", "informational": "info", "note": "info",
}
_STDERR_TAIL = 2000
GITLEAKS_CONFIG = Path(__file__).resolve().parent / "gitleaks.toml"
_GITLEAKS_CONFIG_FILES = (".gitleaks.toml", ".gitleaksignore")
_IGNORE_FILES = (".semgrepignore", ".gitignore", ".gitleaksignore", ".gitleaks.toml")
_REQ_DIRS = ("requirements", "reqs")
_MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".woff",
              ".woff2", ".ttf", ".otf", ".mp4", ".mov", ".mp3", ".wav"}
# lockfiles / manifests osv-scanner reads
_OSV_READS = {"poetry.lock", "uv.lock", "pdm.lock", "Pipfile.lock", "package-lock.json",
              "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "go.mod", "Gemfile.lock",
              "Cargo.lock", "composer.lock", "pom.xml", "gradle.lockfile",
              "buildscript-gradle.lockfile", "requirements.txt"}
_NPM_LOCKS = ("package-lock.json", "npm-shrinkwrap.json")
# source manifest -> lockfiles that make it covered (same dir or an ancestor)
_COMPANIONS = {
    "package.json": ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"),
    "pyproject.toml": ("uv.lock", "poetry.lock", "pdm.lock"),
    "Gemfile": ("Gemfile.lock",),
    "Cargo.toml": ("Cargo.lock",),
    "composer.json": ("composer.lock",),
    "Pipfile": ("Pipfile.lock",),
    "build.gradle": ("gradle.lockfile",),
    "build.gradle.kts": ("gradle.lockfile",),
}
_OTHER_MANIFESTS = {"setup.py", "setup.cfg"} | set(_COMPANIONS)

_SEVERITY = {
    "critical": "critical", "high": "high", "error": "high",
    "moderate": "medium", "medium": "medium", "warning": "medium",
    "low": "low", "info": "info", "informational": "info", "note": "info",
}
_STDERR_TAIL = 2000
GITLEAKS_CONFIG = Path(__file__).resolve().parent / "gitleaks.toml"
_GITLEAKS_CONFIG_FILES = (".gitleaks.toml", ".gitleaksignore")


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


# ---------------------------------------------------------------- git plumbing

def _git(repo: Path, args: list[str], run, input: bytes | None = None, env: dict | None = None) -> bytes:
    kw = {"capture_output": True}
    if input is not None:
        kw["input"] = input
    if env is not None:
        kw["env"] = env
    proc = run(["git", "-C", str(repo), *args], **kw)
    if proc.returncode != 0:
        err = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode(errors="replace")
        raise ScanError("git", err)
    return proc.stdout if isinstance(proc.stdout, bytes) else (proc.stdout or "").encode()


def _toplevel(repo: Path, run) -> Path:
    out = _git(Path(repo), ["rev-parse", "--show-toplevel"], run)
    return Path(os.fsdecode(out.rstrip(b"\n")))


def _names(out: bytes) -> list[bytes]:
    return [n for n in out.split(b"\0") if n]


def _export(repo: Path, dest: Path, run, names: list[bytes] | None, env: dict | None = None) -> None:
    """Write index blobs (all, or `names`) under dest, then neutralise ignore/config files."""
    prefix = f"--prefix={dest}/"
    if names is None:
        _git(repo, ["checkout-index", "-a", prefix], run, env=env)
    elif names:
        _git(repo, ["checkout-index", prefix, "--stdin", "-z"], run,
             input=b"\0".join(names) + b"\0", env=env)
    for dirpath, _dirs, filenames in os.walk(dest):
        for fn in filenames:
            if fn in _IGNORE_FILES:
                try:
                    os.unlink(os.path.join(dirpath, fn))
                except OSError as exc:
                    raise ScanError("semgrep", f"cannot remove exported {fn}: {exc}") from None
    root_ignore = dest / ".semgrepignore"
    if root_ignore.is_symlink() or root_ignore.exists():
        raise ScanError("semgrep", "a .semgrepignore directory or link is in the scanned tree")
    root_ignore.write_text("")


def _remove_symlinks(root: Path) -> list[str]:
    """Delete every symlink in the export (tools must not follow them); return their paths."""
    removed = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                os.unlink(full)
                removed.append(os.path.relpath(full, root))
    return sorted(removed)


def _skip(kind: str, rel: str, severity: str, why: str) -> Finding:
    return Finding.create("scan", f"scan.skipped-{kind}:{rel}", rel, 0, severity,
                          f"{rel} was not scanned: {why}")


def _scannable(root: Path, names: list[bytes]) -> tuple[list[str], list[Finding]]:
    """`./`-prefixed argv paths for regular text files, plus findings for what was skipped."""
    keep: list[str] = []
    skipped: list[Finding] = []
    for raw in names:
        rel = os.fsdecode(raw)
        if os.path.basename(rel) in _IGNORE_FILES:
            continue
        fp = root / rel
        try:
            if fp.is_symlink():
                skipped.append(_skip("symlink", rel, "info", "symlink"))
                continue
            if not fp.is_file():
                skipped.append(_skip("other", rel, "info", "not a regular file (e.g. a submodule)"))
                continue
            with open(fp, "rb") as fh:
                has_nul = b"\0" in fh.read(8192)
        except OSError:
            skipped.append(_skip("other", rel, "info", "unreadable"))
            continue
        if has_nul:
            if os.path.splitext(rel)[1].lower() in _MEDIA_EXT:
                skipped.append(_skip("binary", rel, "info", "known binary media/archive type"))
            else:
                skipped.append(_skip("binary", rel, "high", "contains NUL bytes (binary or UTF-16)"))
            continue
        keep.append("./" + rel)
    return keep, skipped


def _config_changed(names: list[bytes]) -> list[Finding]:
    return [
        Finding.create("gitleaks", "gitleaks.config-changed", os.fsdecode(n), 0, "high",
                       "gitleaks configuration or ignore file changed in the scanned diff")
        for n in names if os.path.basename(os.fsdecode(n)) in (".gitleaks.toml", ".gitleaksignore")
    ]


# ------------------------------------------------------------ scanner plumbing

def _run(tool: str, argv: list[str], cwd: Path, run):
    try:
        proc = run(argv, cwd=str(cwd), capture_output=True, text=True)
    except FileNotFoundError:
        raise ScanError(tool, f"{argv[0]} is not installed") from None
    if proc.returncode not in (0, 1):
        # stdout is never echoed: it may carry matched source text.
        raise ScanError(tool, proc.stderr or f"exit status {proc.returncode}")
    return proc


def _json(tool: str, proc):
    out = (proc.stdout or "").strip()
    if not out:
        raise ScanError(tool, proc.stderr or "empty output")
    try:
        return json.loads(out)
    except ValueError:
        raise ScanError(tool, proc.stderr or "unparseable output") from None


def _clean_path(path: str, root: Path) -> str:
    for base in (str(root), str(root.resolve())):
        if path.startswith(base + "/"):
            path = path[len(base) + 1:]
            break
    while path.startswith("./"):
        path = path[2:]
    return path


def _semgrep(root: Path, paths: list[str], run) -> list[Finding]:
    if not paths:
        return []
    proc = _run("semgrep", [*SCANNERS["semgrep"], *paths], root, run)
    data = _json("semgrep", proc)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ScanError("semgrep", "unexpected output shape")
    errors = data.get("errors") or []
    if errors:
        kinds = sorted({str(e.get("type", "unknown")) if isinstance(e, dict) else "unknown" for e in errors})
        raise ScanError("semgrep", f"{len(errors)} scan error(s): {', '.join(kinds)}")
    if proc.returncode == 1 and not data["results"]:
        raise ScanError("semgrep", proc.stderr or "exit status 1 with no findings")
    found = []
    for r in data["results"]:
        extra = r.get("extra", {})
        found.append(Finding.create(
            "semgrep", r.get("check_id", "unknown"), _clean_path(r.get("path", ""), root),
            r.get("start", {}).get("line", 0),
            normalize_severity(extra.get("severity")), extra.get("message", ""),
        ))
    skipped = (data.get("paths") or {}).get("skipped") or []
    for s in skipped:
        path = _clean_path(s.get("path", "") if isinstance(s, dict) else str(s), root)
        reason = (s.get("reason", "") if isinstance(s, dict) else "") or "skipped"
        found.append(Finding.create(
            "semgrep", "semgrep.skipped-target", path, 0, "high",
            f"semgrep did not scan this file: {reason}",
        ))
    return found


def _gitleaks(mode: str, source: Path, run, log_opts: str | None = None,
              strip: Path | None = None) -> list[Finding]:
    """`gitleaks dir <export>` (mode "dir") or `gitleaks git` in a throwaway clone (mode "git").

    `source` is never the user's working tree: gitleaks would read its .gitleaksignore.
    """
    with tempfile.TemporaryDirectory(prefix="cta-gitleaks-") as tmp:
        report = Path(tmp) / "report.json"  # not pre-created: unwritten means failure
        empty = Path(tmp) / "no-ignore"
        empty.mkdir()
        argv = list(SCANNERS["gitleaks"])
        argv[1] = mode
        argv += ["--config", str(GITLEAKS_CONFIG), "--gitleaks-ignore-path", str(empty),
                 "--report-path", str(report)]
        if log_opts:
            argv.append(f"--log-opts={log_opts}")
        argv.append(str(source))
        proc = _run("gitleaks", argv, source, run)
        try:
            text = report.read_text().strip()
        except FileNotFoundError:
            text = ""
    if not text:
        raise ScanError("gitleaks", proc.stderr or "gitleaks wrote no report")
    try:
        data = json.loads(text)
    except ValueError:
        raise ScanError("gitleaks", proc.stderr or "unparseable report") from None
    if not isinstance(data, list):
        raise ScanError("gitleaks", "unexpected output shape")
    if proc.returncode == 1 and not data:
        raise ScanError("gitleaks", proc.stderr or "exit status 1 with no findings")
    # Only rule, file, line and the rule description are read: Secret/Match are dropped.
    return [
        Finding.create("gitleaks", r.get("RuleID", "unknown"),
                       _clean_path(r.get("File", ""), strip) if strip else r.get("File", ""),
                       r.get("StartLine", 0), "high", r.get("Description", ""))
        for r in data
    ]


def fast_scan(repo: Path, staged: bool = True, run=subprocess.run) -> list[Finding]:
    """Pre-commit scan of the STAGED content: semgrep and `gitleaks dir` over the index export."""
    if not staged:
        raise ValueError("fast_scan scans staged changes only; use full_scan for a branch")
    repo = _toplevel(repo, run)
    names = _names(_git(repo, ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"], run))
    if not names:
        return []
    found: list[Finding] = _config_changed(names)
    with tempfile.TemporaryDirectory(prefix="cta-staged-") as tmp:
        root = Path(tmp)
        _export(repo, root, run, names)
        paths, skipped = _scannable(root, names)
        found += skipped
        _remove_symlinks(root)
        found += _semgrep(root, paths, run)
        found += _gitleaks("dir", root, run, strip=root)
    return found


# ------------------------------------------------------------ dependency audits

def _is_requirements(rel: str) -> bool:
    fn = os.path.basename(rel).lower()
    parent = os.path.basename(os.path.dirname(rel)).lower()
    return fn.endswith(".txt") and (fn.startswith("requirements") or parent in _REQ_DIRS)


def _is_manifest(rel: str) -> bool:
    fn = os.path.basename(rel)
    low = fn.lower()
    parent = os.path.basename(os.path.dirname(rel)).lower()
    return (_is_requirements(rel) or fn in _OSV_READS or fn in _OTHER_MANIFESTS
            or (low.endswith(".in") and (low.startswith("requirements") or parent in _REQ_DIRS)))


def _manifests(root: Path) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if _is_manifest(rel):
                found.append(rel)
    return sorted(found)


def _has_project_table(path: Path) -> bool:
    try:
        return "project" in tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return False


def _pip_audit_run(root: Path, extra: list[str], manifest: str, run) -> list[Finding]:
    data = _json("pip-audit", _run("pip-audit", [*SCANNERS["pip-audit"], *extra], root, run))
    deps = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(deps, list):
        raise ScanError("pip-audit", "unexpected output shape")
    found = []
    for d in deps:
        if d.get("skip_reason"):
            found.append(Finding.create(
                "pip-audit", f"pip-audit.skipped:{d.get('name')}", manifest, 0, "info",
                f"{d.get('name')} not audited: {d['skip_reason']}"))
        for v in d.get("vulns", []):
            fixes = ", ".join(v.get("fix_versions") or [])
            msg = f"{d.get('name')} {d.get('version')}: {v.get('description') or v.get('id')}"
            if fixes:
                msg += f" (fix: {fixes})"
            found.append(Finding.create("pip-audit", v.get("id", "unknown"), manifest, 0, "high", msg))
    return found


def _npm_audit(root: Path, run) -> list[Finding]:
    proc = _run("npm", SCANNERS["npm"], root, run)
    data = _json("npm", proc)
    if not isinstance(data, dict) or "error" in data or "vulnerabilities" not in data:
        # stdout (the npm error object) is not echoed; fixed text plus the exit code
        raise ScanError("npm", proc.stderr or f"npm audit reported an error (exit {proc.returncode})")
    found: dict[str, Finding] = {}
    for name, v in data["vulnerabilities"].items():
        for via in v.get("via", []):
            if not isinstance(via, dict):
                continue  # a name: the advisory is listed under that package
            rule = str(via.get("source") or via.get("url") or f"{name}:{via.get('title', '')}")
            msg = f"{via.get('name') or name}: {via.get('title') or 'vulnerable dependency'}"
            sev = normalize_severity(via.get("severity") or v.get("severity"), "high")
            f = Finding.create("npm", rule, "package.json", 0, sev, msg)
            found.setdefault(f.id, f)
    return list(found.values())


def _osv(root: Path, run) -> list[Finding]:
    data = _json("osv-scanner", _run("osv-scanner", [*SCANNERS["osv-scanner"], "-r", "."], root, run))
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ScanError("osv-scanner", "unexpected output shape")
    found = []
    for res in data["results"]:
        src = res.get("source", {}).get("path", "")
        for pk in res.get("packages", []):
            pkg = pk.get("package", {})
            for v in pk.get("vulnerabilities", []):
                sev = (v.get("database_specific") or {}).get("severity")
                msg = f"{pkg.get('name')} {pkg.get('version')}: {v.get('summary') or v.get('id')}"
                found.append(Finding.create("osv-scanner", v.get("id", "unknown"), _clean_path(src, root), 0,
                                            normalize_severity(sev, "high"), msg))
    return found


def _companion_covered(rel: str, covered: set[str]) -> bool:
    """A source manifest is covered by a covered lockfile in its directory or an ancestor."""
    fn = os.path.basename(rel)
    if fn in _COMPANIONS:
        wanted = _COMPANIONS[fn]
    elif fn.lower().endswith(".in"):  # requirements.in: a covered requirements*.txt beside it
        d = os.path.dirname(rel)
        return any(_is_requirements(c) and os.path.dirname(c) == d for c in covered)
    else:
        return False
    d = os.path.dirname(rel)
    while True:
        if any(os.path.join(d, w) in covered or (not d and w in covered) for w in wanted):
            return True
        if not d:
            return False
        d = os.path.dirname(d)


def _dependency_audit(root: Path, run, which, linked: list[str]) -> list[Finding]:
    found: list[Finding] = []
    manifests = _manifests(root)
    covered: set[str] = set()
    for rel in manifests:
        if _is_requirements(rel):  # one run per file so findings name their file
            found += _pip_audit_run(root, ["-r", rel], rel, run)
            covered.add(rel)
    if _has_project_table(root / "pyproject.toml"):
        found += _pip_audit_run(root, ["."], "pyproject.toml", run)
        covered.add("pyproject.toml")
    if which("npm") and any(m in _NPM_LOCKS for m in manifests):
        found += _npm_audit(root, run)
        covered.update(m for m in manifests if m in _NPM_LOCKS)
    osv_reads = [m for m in manifests if os.path.basename(m) in _OSV_READS]
    if osv_reads and which("osv-scanner"):
        found += _osv(root, run)
        covered.update(osv_reads)
    uncovered = [m for m in manifests if m not in covered and not _companion_covered(m, covered)]
    uncovered += [m for m in linked if _is_manifest(m)]  # symlinked manifests are never followed
    for m in sorted(set(uncovered)):
        found.append(Finding.create("audit", f"audit.not-audited:{m}", m, 0, "high",
                                    f"{m} is not covered by any available dependency auditor"))
    return found


# ------------------------------------------------------------ full scan

def _resolve(repo: Path, ref: str, run) -> str:
    return _git(repo, ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], run).decode().strip()


def _clone_for_history(repo: Path, dest: Path, shas: list[str], run) -> None:
    """A checkout-less copy of the history: no working tree, so no .gitleaksignore."""
    proc = run(["git", "clone", "--quiet", "--no-checkout", "--no-local", str(repo), str(dest)],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScanError("git", proc.stderr)
    for sha in shas:
        have = run(["git", "-C", str(dest), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True)
        if have.returncode != 0:  # e.g. a detached HEAD not reachable from any branch
            _git(dest, ["fetch", "--quiet", "--no-tags", str(repo), sha], run)


def full_scan(repo: Path, base: str, run=subprocess.run, which=shutil.which,
              head: str = "HEAD") -> list[Finding]:
    """Branch scan of the committed `head` tree: semgrep on the diff's files, gitleaks over
    base..head in a throwaway clone, and the dependency audit of every manifest in the tree."""
    check_ref(base)
    check_ref(head)
    repo = _toplevel(repo, run)
    base_sha, head_sha = _resolve(repo, base, run), _resolve(repo, head, run)
    names = _names(_git(repo, ["diff", "--name-only", "-z", "--diff-filter=ACMRT",
                               f"{base_sha}..{head_sha}"], run))
    found: list[Finding] = _config_changed(names)
    with tempfile.TemporaryDirectory(prefix="cta-tree-") as tmp:
        tmp_path = Path(tmp)
        root = tmp_path / "tree"
        root.mkdir()
        env = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "index")}
        _git(repo, ["read-tree", head_sha], run, env=env)
        _export(repo, root, run, None, env=env)
        paths, skipped = _scannable(root, names)
        found += skipped
        linked = _remove_symlinks(root)
        found += _semgrep(root, paths, run)
        clone = tmp_path / "history"
        _clone_for_history(repo, clone, [base_sha, head_sha], run)
        found += _gitleaks("git", clone, run, log_opts=f"{base_sha}..{head_sha}")
        found += _dependency_audit(root, run, which, linked)
    return found
