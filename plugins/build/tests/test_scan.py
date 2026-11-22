import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import findings
import scan
from scan import ScanError

GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid"]


def git(cwd, *args):
    return subprocess.run(
        [*GIT, "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path, files):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for name, content in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(content)
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    return path


def cp(stdout="", rc=0, stderr=""):
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


def gl(report, rc=0):
    """A fake gitleaks that writes `report` to its --report-path."""

    def answer(argv, kw):
        Path(argv[argv.index("--report-path") + 1]).write_text(report)
        return cp("", rc)

    return answer


class FakeRun:
    """Answers scanner argv; passes git calls through to the real git."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        assert kw.get("shell") is not True and isinstance(argv, list)
        key = argv[0]
        if key == "git":
            return subprocess.run(argv, **kw)
        ans = self.answers[key]
        return ans(argv, kw) if callable(ans) else ans

    def argv(self, tool):
        return [a for a, _ in self.calls if a[0] == tool]


SEMGREP_OUT = json.dumps(
    {
        "results": [
            {
                "check_id": "python.lang.security.eval",
                "path": "app.py",
                "start": {"line": 7, "col": 1},
                "extra": {"severity": "ERROR", "message": "Avoid eval"},
            },
            {
                "check_id": "python.style.x",
                "path": "app.py",
                "start": {"line": 9},
                "extra": {"severity": "WARNING", "message": "meh"},
            },
        ],
        "errors": [],
    }
)
SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"  # built at runtime; fake value
GITLEAKS_OUT = json.dumps(
    [
        {
            "RuleID": "aws-access-token",
            "File": "app.py",
            "StartLine": 2,
            "Description": "AWS access token",
            "Secret": SECRET,
            "Match": f"key = {SECRET}",
            "Commit": "",
        }
    ]
)


def test_detect_languages(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    langs = scan.detect_languages(
        tmp_path, ["a.py", "web/b.tsx", "run.sh", "gem.rb", "README.md", "package.json"]
    )
    assert langs == {"python", "node", "go", "ruby", "shell"}
    assert scan.detect_languages(tmp_path / "empty", ["x.md"]) == set()
    assert scan.detect_languages(tmp_path, ["Gemfile"]) >= {"ruby"}


def test_missing_scanners_reported():
    have = {"semgrep"}
    which = lambda n: f"/bin/{n}" if n in have else None  # noqa: E731
    assert scan.missing_scanners(["semgrep", "gitleaks", "pip-audit"], which=which) == [
        "gitleaks",
        "pip-audit",
    ]
    assert scan.missing_scanners(["semgrep"], which=which) == []
    assert set(scan.SCANNERS) == {"semgrep", "gitleaks", "pip-audit", "osv-scanner", "npm"}


def test_fast_scan_normalizes_semgrep_and_gitleaks(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "app.py").write_text("eval(x)\n")
    (repo / "old.py").write_text("y\n")
    git(repo, "add", "app.py", "old.py")
    git(repo, "commit", "-q", "-m", "old")
    git(repo, "rm", "-q", "old.py")  # staged deletion: must be skipped
    (repo / "new file.py").write_text("z=1\n")
    git(repo, "add", "app.py", "new file.py")
    (repo / "app.py").write_text("eval(x)\n# touched\n")
    git(repo, "add", "app.py")
    run = FakeRun({"semgrep": cp(SEMGREP_OUT, 1), "gitleaks": gl(GITLEAKS_OUT, 1)})
    out = scan.fast_scan(repo, staged=True, run=run)
    by_tool = {(f.tool, f.rule): f for f in out}
    sg = by_tool[("semgrep", "python.lang.security.eval")]
    assert (sg.path, sg.line, sg.severity, sg.message) == ("app.py", 7, "high", "Avoid eval")
    assert by_tool[("semgrep", "python.style.x")].severity == "medium"
    leak = by_tool[("gitleaks", "aws-access-token")]
    assert (leak.path, leak.line, leak.message) == ("app.py", 2, "AWS access token")
    # semgrep got staged paths as argv, deletions skipped, no shell
    (sargv,) = run.argv("semgrep")
    assert sargv[:7] == ["semgrep", "--config", "p/default", "--error", "--json", "--disable-nosem", "--no-git-ignore"]
    assert sorted(sargv[9:]) == ["./app.py", "./new file.py"]
    (gargv,) = run.argv("gitleaks")
    assert gargv[1] == "dir" and "json" in gargv and "--redact" in gargv
    assert "-" not in gargv[gargv.index("--report-path") + 1:][:1]


def test_fast_scan_nothing_staged_skips_semgrep(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    run = FakeRun({"gitleaks": gl("[]", 0)})
    assert scan.fast_scan(repo, staged=True, run=run) == []
    assert run.argv("semgrep") == []


def test_finding_id_stable():
    a = findings.Finding.create("semgrep", "r", "a.py", 3, "high", "m")
    b = findings.Finding.create("semgrep", "r", "a.py", 3, "high", "other message")
    c = findings.Finding.create("semgrep", "r", "a.py", 4, "high", "m")
    assert a.id == b.id != c.id
    import hashlib

    assert a.id == hashlib.sha256(b"semgrep|r|a.py|3").hexdigest()[:16]
    assert a.to_dict()["id"] == a.id
    with pytest.raises(Exception):
        a.rule = "x"  # frozen


def test_gitleaks_secret_never_kept(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "app.py").write_text("k=1\n")
    git(repo, "add", "app.py")
    run = FakeRun({"semgrep": cp(json.dumps({"results": []}), 0), "gitleaks": gl(GITLEAKS_OUT, 1)})
    out = scan.fast_scan(repo, staged=True, run=run)
    assert out and SECRET not in repr(out)
    assert all(SECRET not in json.dumps(f.to_dict()) for f in out)
    record = findings.new_record("main", "abc", "d" * 64, out)
    path = tmp_path / "security.json"
    findings.save(path, record)
    assert SECRET not in path.read_text()


def full_repo(tmp_path, files):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature")
    for name, content in files.items():
        (repo / name).write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "feature")
    return repo, base


def test_full_scan_uses_osv_without_npm(tmp_path):
    repo, base = full_repo(tmp_path, {"package.json": "{}\n", "package-lock.json": "{}\n", "app.js": "1\n"})
    osv = json.dumps(
        {
            "results": [
                {
                    "source": {"path": "package-lock.json", "type": "lockfile"},
                    "packages": [
                        {
                            "package": {"name": "left-pad", "version": "1.0.0"},
                            "vulnerabilities": [
                                {
                                    "id": "GHSA-xxxx",
                                    "summary": "Bad thing",
                                    "database_specific": {"severity": "HIGH"},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    run = FakeRun(
        {
            "semgrep": cp(json.dumps({"results": []}), 0),
            "gitleaks": gl("[]", 0),
            "osv-scanner": cp(osv, 1),
        }
    )
    out = scan.full_scan(repo, "main", run=run, which=lambda n: n != "npm")
    assert run.argv("npm") == []
    assert len(run.argv("osv-scanner")) == 1
    (dep,) = [f for f in out if f.tool == "osv-scanner"]
    assert dep.rule == "GHSA-xxxx" and dep.severity == "high"
    assert dep.path == "package-lock.json" and "left-pad" in dep.message
    # semgrep was handed only the branch diff files
    (sargv,) = run.argv("semgrep")
    assert sorted(sargv[9:]) == ["./app.js", "./package-lock.json", "./package.json"]
    gl_argv = run.argv("gitleaks")[0]
    assert gl_argv[1] == "git" and f"--log-opts={base}..{git(repo, 'rev-parse', 'HEAD')}" in gl_argv
    assert Path(gl_argv[-1]) != repo


def test_full_scan_uses_npm_and_pip_audit(tmp_path):
    repo, base = full_repo(tmp_path, {"package.json": "{}\n", "package-lock.json": "{}\n", "app.py": "1\n", "requirements.txt": "django==1.0\n"})
    npm = json.dumps(
        {"vulnerabilities": {"lodash": {"name": "lodash", "severity": "critical",
         "via": [{"source": 1096, "name": "lodash", "title": "Proto pollution", "url": "u"}]}}}
    )
    pipa = json.dumps(
        {"dependencies": [{"name": "django", "version": "1.0",
         "vulns": [{"id": "PYSEC-1", "description": "SQLi", "fix_versions": ["2"]}]},
         {"name": "ok", "version": "1", "vulns": []}]}
    )
    run = FakeRun(
        {
            "semgrep": cp(json.dumps({"results": []}), 0),
            "gitleaks": gl("[]", 0),
            "npm": cp(npm, 1),
            "pip-audit": cp(pipa, 1),
            "osv-scanner": cp('{"results": []}', 0),
        }
    )
    out = scan.full_scan(repo, "main", run=run, which=lambda n: "/bin/" + n)
    tools = {f.tool: f for f in out}
    assert tools["npm"].severity == "critical" and tools["npm"].rule == "1096"
    assert tools["pip-audit"].rule == "PYSEC-1" and tools["pip-audit"].severity == "high"
    assert run.argv("npm")[0][:3] == ["npm", "audit", "--json"]


def test_scanner_failure_is_not_no_findings(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    run = FakeRun({"semgrep": cp("Traceback ...", 2, "boom\n" * 100), "gitleaks": gl("[]", 0)})
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, staged=True, run=run)
    assert ei.value.tool == "semgrep" and "boom" in str(ei.value)
    assert len(ei.value.stderr_tail) <= 2000
    # exit 1 with garbage output is also an error, never "clean"
    run = FakeRun({"semgrep": cp("not json", 1), "gitleaks": gl("[]", 0)})
    with pytest.raises(ScanError):
        scan.fast_scan(repo, staged=True, run=run)
    run = FakeRun({"semgrep": cp('{"results": []}', 0), "gitleaks": gl("oops", 1)})
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, staged=True, run=run)
    assert ei.value.tool == "gitleaks"


def test_scanner_not_installed_raises(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")

    def run(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        raise FileNotFoundError(argv[0])

    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, staged=True, run=run)
    assert ei.value.tool == "semgrep" and "not installed" in str(ei.value)


# ---------------------------------------------------------------- fix round 1

CLEAN = cp(json.dumps({"results": []}), 0)


def test_fast_scan_scans_staged_content_not_working_tree(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "app.py").write_text("eval(x)\n")
    (repo / "gone.py").write_text("eval(y)\n")
    git(repo, "add", "app.py", "gone.py")
    (repo / "app.py").write_text("print('clean')\n")  # edited after staging
    (repo / "gone.py").unlink()  # deleted after staging
    seen = {}

    def semgrep(argv, kw):
        root = Path(kw["cwd"])
        for a in argv[9:]:
            seen[a] = (root / a).read_text()
        return CLEAN

    scan.fast_scan(repo, staged=True, run=FakeRun({"semgrep": semgrep, "gitleaks": gl("[]")}))
    assert seen == {"./app.py": "eval(x)\n", "./gone.py": "eval(y)\n"}


def test_full_scan_scans_committed_tree_not_working_tree(tmp_path):
    repo, base = full_repo(tmp_path, {"app.py": "eval(x)\n"})
    (repo / "app.py").write_text("clean\n")  # uncommitted edit
    (repo / "requirements.txt").write_text("evil==1\n")  # uncommitted manifest
    seen = {}

    def semgrep(argv, kw):
        seen["app"] = (Path(kw["cwd"]) / "app.py").read_text()
        return CLEAN

    run = FakeRun({"semgrep": semgrep, "gitleaks": gl("[]")})
    scan.full_scan(repo, "main", run=run, which=lambda n: None)
    assert seen["app"] == "eval(x)\n"
    assert run.argv("pip-audit") == []  # manifest not committed -> not audited


def test_semgrep_errors_raise(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    bad = json.dumps({"results": [], "errors": [{"type": "PartialParsing", "level": "warn"}]})
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, run=FakeRun({"semgrep": cp(bad, 0), "gitleaks": gl("[]")}))
    assert "PartialParsing" in str(ei.value)


def test_semgrep_skipped_files_become_findings(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    out = json.dumps({"results": [], "errors": [],
                      "paths": {"scanned": [], "skipped": [{"path": "a.py", "reason": "too big"}]}})
    (f,) = scan.fast_scan(repo, run=FakeRun({"semgrep": cp(out, 0), "gitleaks": gl("[]")}))
    assert (f.rule, f.path, f.severity) == ("semgrep.skipped-target", "a.py", "high")
    assert "too big" in f.message


def test_dash_leading_file_name_is_scanned_not_an_option(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "--exclude=*.py").write_text("eval(x)\n")
    git(repo, "add", "--", "--exclude=*.py")
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    scan.fast_scan(repo, run=run)
    (sargv,) = run.argv("semgrep")
    assert sargv[9:] == ["./--exclude=*.py"]


def test_non_utf8_name_never_an_uncaught_exception(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    blob = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
        input=b"eval(x)\n", capture_output=True, check=True).stdout.decode().strip()
    # register the name directly in the index: no file system involved
    subprocess.run(
        [b"git", b"-C", str(repo).encode(), b"update-index", b"--add", b"--cacheinfo",
         b"100644," + blob.encode() + b",bad-\xff.py"], check=True, capture_output=True)
    assert b"bad-\xff.py" in subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True).stdout
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    try:
        out = scan.fast_scan(repo, run=run)
    except ScanError:
        return  # e.g. the file system refused the name: fail closed, not a crash
    assert isinstance(out, list)


def test_scan_error_never_carries_stdout(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    leaked = "key = " + SECRET
    for proc in (cp(leaked, 2, ""), cp(leaked, 1, ""), cp(leaked, 0, ""),
                 cp(json.dumps({"results": [], "errors": [{"extra": {"lines": leaked}}]}), 0)):
        with pytest.raises(ScanError) as ei:
            scan.fast_scan(repo, run=FakeRun({"semgrep": proc, "gitleaks": gl("[]")}))
        assert SECRET not in str(ei.value) and SECRET not in ei.value.stderr_tail


def test_exit_one_without_findings_is_an_error(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, run=FakeRun({"semgrep": cp(json.dumps({"results": []}), 1),
                                          "gitleaks": gl("[]")}))
    assert ei.value.tool == "semgrep"
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, run=FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]", 1)}))
    assert ei.value.tool == "gitleaks"


def test_gitleaks_report_goes_to_a_temp_file_that_is_removed(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "b.md").write_text("b\n")
    git(repo, "add", "b.md")
    paths = []

    def leaks(argv, kw):
        p = Path(argv[argv.index("--report-path") + 1])
        paths.append(p)
        p.write_text("[]")
        return cp("", 0)

    scan.fast_scan(repo, run=FakeRun({"semgrep": CLEAN, "gitleaks": leaks}))
    assert paths and paths[0].name != "-" and not paths[0].exists()


def test_npm_one_finding_per_advisory(tmp_path):
    repo, _ = full_repo(tmp_path, {"package-lock.json": "{}\n"})
    npm = json.dumps({"vulnerabilities": {"a": {"severity": "high", "via": [
        {"source": 1, "title": "t1"}, {"source": 2, "title": "t2"}, "b"]}}})
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]"), "npm": cp(npm, 1),
                   "osv-scanner": cp('{"results": []}', 0)})
    out = [f for f in scan.full_scan(repo, "main", run=run, which=lambda n: "/n")
           if f.tool == "npm"]
    assert sorted(f.rule for f in out) == ["1", "2"] and len({f.id for f in out}) == 2


def test_osv_requires_results_key(tmp_path):
    repo, _ = full_repo(tmp_path, {"go.mod": "module x\n"})
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]"), "osv-scanner": cp("{}", 0)})
    with pytest.raises(ScanError) as ei:
        scan.full_scan(repo, "main", run=run, which=lambda n: "/b")
    assert ei.value.tool == "osv-scanner"


def test_pip_audit_skipped_dependency_is_info_finding(tmp_path):
    repo, _ = full_repo(tmp_path, {"requirements.txt": "private==1\n"})
    pipa = json.dumps({"dependencies": [
        {"name": "private", "skip_reason": "Dependency not found on PyPI"}]})
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]"), "pip-audit": cp(pipa, 0)})
    out = scan.full_scan(repo, "main", run=run, which=lambda n: None)
    (f,) = [f for f in out if f.tool == "pip-audit"]
    assert f.severity == "info" and "private" in f.message


def test_audit_only_when_manifest_exists(tmp_path):
    repo, _ = full_repo(tmp_path, {"app.py": "1\n", "app.js": "1\n", "main.go": "x\n"})
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})  # any audit call would KeyError
    assert scan.full_scan(repo, "main", run=run, which=lambda n: "/b") == []


def test_manifest_present_and_tool_fails_raises(tmp_path):
    repo, _ = full_repo(tmp_path, {"requirements.txt": "x==1\n"})
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]"), "pip-audit": cp("", 2, "resolver blew up")})
    with pytest.raises(ScanError) as ei:
        scan.full_scan(repo, "main", run=run, which=lambda n: None)
    assert ei.value.tool == "pip-audit"


def test_option_like_refs_rejected(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    with pytest.raises(ValueError):
        scan.full_scan(repo, "--output=/tmp/x", run=FakeRun({}))


# ---------------------------------------------------------------- fix round 2

OSV_EMPTY = cp('{"results": []}', 0)
PIP_EMPTY = cp('{"dependencies": []}', 0)


def audit_run(**extra):
    answers = {"semgrep": CLEAN, "gitleaks": gl("[]"), "osv-scanner": OSV_EMPTY,
               "pip-audit": PIP_EMPTY, "npm": cp('{"vulnerabilities": {}}', 0)}
    answers.update(extra)
    return FakeRun(answers)


def not_audited(out):
    return sorted(f.path for f in out if f.rule.startswith("audit.not-audited:"))


def test_nested_manifests_are_audited_or_reported(tmp_path):
    repo, _ = full_repo(tmp_path, {"notes.md": "1\n"})
    for name in ("web", "go", "requirements", "svc", "legacy"):
        (repo / name).mkdir()
    (repo / "web/package-lock.json").write_text("{}\n")
    (repo / "go/go.mod").write_text("module x\n")
    (repo / "requirements/base.txt").write_text("a==1\n")
    (repo / "svc/pyproject.toml").write_text("[project]\n")
    (repo / "legacy/setup.py").write_text("x=1\n")
    (repo / "Pipfile.lock").write_text("{}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "m")
    run = audit_run()
    out = scan.full_scan(repo, "main", run=run, which=lambda n: "/b")
    assert len(run.argv("osv-scanner")) == 1 and run.argv("osv-scanner")[0][-2:] == ["-r", "."]
    pip = run.argv("pip-audit")
    assert pip and "requirements/base.txt" in pip[0]  # nested requirements file audited
    assert not_audited(out) == ["legacy/setup.py", "svc/pyproject.toml"]
    # without osv-scanner nothing osv-only is silently clean
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: None if n == "osv-scanner" else "/b")
    assert not_audited(out) == ["Pipfile.lock", "go/go.mod", "legacy/setup.py",
                                "svc/pyproject.toml", "web/package-lock.json"]
    assert all(f.severity == "high" for f in out if f.rule.startswith("audit."))


def test_subdirectory_repo_resolves_to_top_level(tmp_path):
    repo, base = full_repo(tmp_path, {"sub.py": "eval(x)\n", "requirements.txt": "a==1\n"})
    (repo / "pkg").mkdir()
    (repo / "pkg/inner.py").write_text("1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "inner")
    seen = {}

    def semgrep(argv, kw):
        seen["args"] = sorted(argv[9:])
        return CLEAN

    run = audit_run(semgrep=semgrep)
    scan.full_scan(repo / "pkg", "main", run=run, which=lambda n: None)
    assert "./sub.py" in seen["args"] and "./pkg/inner.py" in seen["args"]
    assert run.argv("pip-audit")  # root manifest audited though called from a subdir
    (repo / "x.py").write_text("1\n")
    git(repo, "add", "x.py")
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    scan.fast_scan(repo / "pkg", run=run)
    assert run.argv("semgrep")[0][9:] == ["./x.py"]
    from findings import diff_hash
    assert diff_hash(repo / "pkg", base) == diff_hash(repo, base)


def test_gitleaks_exit_zero_without_report_is_error(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "b.md").write_text("b\n")
    git(repo, "add", "b.md")
    for answer in (lambda argv, kw: cp("", 0), gl(""), gl("null")):
        with pytest.raises(ScanError) as ei:
            scan.fast_scan(repo, run=FakeRun({"semgrep": CLEAN, "gitleaks": answer}))
        assert ei.value.tool == "gitleaks"


def test_typechange_is_scanned(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "link.py").symlink_to("README.md")
    git(repo, "add", "link.py")
    git(repo, "commit", "-q", "-m", "link")
    (repo / "link.py").unlink()
    (repo / "link.py").write_text("eval(payload)\n")
    git(repo, "add", "link.py")
    assert "T\tlink.py" in git(repo, "diff", "--cached", "--name-status")
    seen = {}

    def semgrep(argv, kw):
        seen["body"] = (Path(kw["cwd"]) / "link.py").read_text()
        return CLEAN

    scan.fast_scan(repo, run=FakeRun({"semgrep": semgrep, "gitleaks": gl("[]")}))
    assert seen["body"] == "eval(payload)\n"


def test_nested_ignore_files_removed_and_ignore_dir_is_error(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "d").mkdir()
    (repo / "d/.semgrepignore").write_text("*\n")
    (repo / "d/.gitignore").write_text("*\n")
    (repo / ".semgrepignore").write_text("*\n")
    (repo / "d/a.py").write_text("eval(x)\n")
    git(repo, "add", "-f", ".")
    seen = {}

    def semgrep(argv, kw):
        root = Path(kw["cwd"])
        seen["ignores"] = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                                 if p.name in (".semgrepignore", ".gitignore") and p.is_file())
        seen["root_ignore"] = (root / ".semgrepignore").read_text()
        seen["args"] = argv[9:]
        return CLEAN

    scan.fast_scan(repo, run=FakeRun({"semgrep": semgrep, "gitleaks": gl("[]")}))
    assert seen["ignores"] == [".semgrepignore"] and seen["root_ignore"] == ""
    assert seen["args"] == ["./d/a.py"]
    # a directory named .semgrepignore: fail closed
    git(repo, "rm", "-rq", "--cached", ".")
    (repo / ".semgrepignore").unlink()
    (repo / ".semgrepignore").mkdir()
    (repo / ".semgrepignore/f.py").write_text("1\n")
    git(repo, "add", "-f", ".semgrepignore/f.py")
    with pytest.raises(ScanError):
        scan.fast_scan(repo, run=FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")}))


def test_skipped_binary_and_symlink_are_findings(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "img.png").write_bytes(b"\x89PNG\x00\x01")
    (repo / "blob.dat").write_bytes(b"a\x00b")
    (repo / "ln.py").symlink_to("README.md")
    (repo / "ok.py").write_text("1\n")
    git(repo, "add", ".")
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    out = scan.fast_scan(repo, run=run)
    rules = {f.rule: f for f in out}
    assert rules["scan.skipped-binary:img.png"].severity == "info"  # known media type
    assert rules["scan.skipped-symlink:ln.py"].severity == "info"
    assert rules["scan.skipped-binary:blob.dat"].severity == "high"  # NUL in an unknown type
    assert run.argv("semgrep")[0][9:] == ["./ok.py"]


def test_gitleaks_uses_bundled_config_and_flags_config_changes(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / ".gitleaks.toml").write_text("[allowlist]\n")
    (repo / ".gitleaksignore").write_text("fingerprint\n")
    git(repo, "add", ".")
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    out = scan.fast_scan(repo, run=run)
    argv = run.argv("gitleaks")[0]
    assert argv[argv.index("--config") + 1] == str(scan.GITLEAKS_CONFIG)
    assert "useDefault = true" in scan.GITLEAKS_CONFIG.read_text()
    ignore_dir = Path(argv[argv.index("--gitleaks-ignore-path") + 1])
    assert ignore_dir != repo and "--ignore-gitleaks-allow" in argv
    changed = sorted(f.path for f in out if f.rule == "gitleaks.config-changed")
    assert changed == [".gitleaks.toml", ".gitleaksignore"]


def test_null_results_is_scan_error(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    with pytest.raises(ScanError):
        scan.fast_scan(repo, run=FakeRun({"semgrep": cp('{"results": null}', 0),
                                          "gitleaks": gl("[]")}))
    full, _ = full_repo(tmp_path / "f", {"go.mod": "module x\n"})
    with pytest.raises(ScanError) as ei:
        scan.full_scan(full, "main", run=audit_run(**{"osv-scanner": cp('{"results": null}', 0)}),
                       which=lambda n: "/b")
    assert ei.value.tool == "osv-scanner"


def test_npm_error_message_not_from_stdout(tmp_path):
    repo, _ = full_repo(tmp_path, {"package-lock.json": "{}\n"})
    leaked = "token=" + SECRET
    npm = cp(json.dumps({"error": {"summary": leaked}}), 1)
    with pytest.raises(ScanError) as ei:
        scan.full_scan(repo, "main", run=audit_run(npm=npm), which=lambda n: "/b")
    assert SECRET not in str(ei.value) and "exit 1" in str(ei.value)


# ---------------------------------------------------------------- fix round 3

def test_gitleaks_never_uses_the_working_tree_as_source(tmp_path):
    repo, base = full_repo(tmp_path, {"a.txt": "1\n"})
    (repo / ".gitleaksignore").write_text("anything\n")  # untracked: must not be seen
    sources = []

    def leaks(argv, kw):
        src = Path(argv[-1])
        sources.append((src, sorted(p.name for p in src.rglob(".gitleaksignore")), (src / "b.txt").exists(), (src / "a.txt").exists()))
        Path(argv[argv.index("--report-path") + 1]).write_text("[]")
        return cp("", 0)

    scan.full_scan(repo, "main", run=audit_run(gitleaks=leaks), which=lambda n: None)
    (src, ignores, _b, has_a), = sources
    assert src != repo and not str(src).startswith(str(repo)) and ignores == []
    assert not has_a  # --no-checkout: no working tree files
    # fast scan: staged .gitleaksignore is removed from the export gitleaks reads
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "-f", "b.txt", ".gitleaksignore")
    sources.clear()
    scan.fast_scan(repo, run=audit_run(gitleaks=leaks))
    (src, ignores, has_b, _a), = sources
    assert src != repo and ignores == [] and has_b


def test_semgrep_disable_nosem():
    assert "--disable-nosem" in scan.SCANNERS["semgrep"]


def test_pip_audit_dot_only_with_project_table(tmp_path):
    repo, _ = full_repo(tmp_path, {"pyproject.toml": "[tool.x]\na = 1\n"})
    run = audit_run()
    out = scan.full_scan(repo, "main", run=run, which=lambda n: None)
    assert run.argv("pip-audit") == []
    assert not_audited(out) == ["pyproject.toml"]
    repo2, _ = full_repo(tmp_path / "two", {"pyproject.toml": "[project]\nname='x'\n"})
    run = audit_run()
    out = scan.full_scan(repo2, "main", run=run, which=lambda n: None)
    assert run.argv("pip-audit")[0][-1] == "."
    assert not_audited(out) == []


def test_lockfiles_not_covered_by_pip_audit(tmp_path):
    repo, _ = full_repo(tmp_path, {"pyproject.toml": "[tool.x]\n", "uv.lock": "v\n",
                                    "poetry.lock": "v\n", "pdm.lock": "v\n"})
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: None if n == "osv-scanner" else "/b")
    assert not_audited(out) == ["pdm.lock", "poetry.lock", "pyproject.toml", "uv.lock"]
    run = audit_run()
    out = scan.full_scan(repo, "main", run=run, which=lambda n: "/b")
    assert not_audited(out) == [] and run.argv("pip-audit") == [] and len(run.argv("osv-scanner")) == 1


def test_unrecognised_manifests_are_reported_or_covered(tmp_path):
    files = {"package.json": "{}\n", "Gemfile": "g\n", "Cargo.toml": "c\n", "composer.json": "{}\n",
             "build.gradle": "x\n", "build.gradle.kts": "x\n", "Pipfile": "p\n",
             "pom.xml": "<p/>\n", "Cargo.lock": "l\n", "composer.lock": "{}\n",
             "Requirements-Dev.TXT": "a==1\n", "requirements.in": "a\n", "sub": None}
    files.pop("sub")
    repo, _ = full_repo(tmp_path, files)
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: "/b")
    # package.json/Gemfile/Pipfile have no lock; gradle has no lockfile; Cargo.toml/composer.json covered
    assert not_audited(out) == ["Gemfile", "Pipfile", "build.gradle", "build.gradle.kts", "package.json"]
    run = audit_run()
    scan.full_scan(repo, "main", run=run, which=lambda n: "/b")
    assert any("Requirements-Dev.TXT" in a for a in run.argv("pip-audit")[0])  # case-insensitive
    # without osv-scanner the osv-only manifests are reported too
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: None if n == "osv-scanner" else "/b")
    assert {"Cargo.lock", "composer.lock", "pom.xml"} <= set(not_audited(out))


def test_symlinked_manifest_not_followed(tmp_path):
    repo, _ = full_repo(tmp_path, {"notes.md": "1\n"})
    (repo / "requirements.txt").symlink_to("/etc/hosts")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "link")
    run = audit_run()
    out = scan.full_scan(repo, "main", run=run, which=lambda n: "/b")
    assert run.argv("pip-audit") == []
    assert not_audited(out) == ["requirements.txt"]


def test_skipped_other_for_submodule_gitlink(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor/lib")
    out = scan.fast_scan(repo, run=FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")}))
    (f,) = [f for f in out if f.rule.startswith("scan.skipped-other")]
    assert (f.severity, f.path) == ("info", "vendor/lib")


def test_requirements_findings_name_their_file(tmp_path):
    repo, _ = full_repo(tmp_path, {"requirements.txt": "a==1\n", "requirements-dev.txt": "b==1\n"})

    def pip(argv, kw):
        name = argv[argv.index("-r") + 1]
        vid = "V-" + name
        return cp(json.dumps({"dependencies": [{"name": "x", "version": "1",
                  "vulns": [{"id": vid, "description": "d"}]}]}), 1)

    out = scan.full_scan(repo, "main", run=audit_run(**{"pip-audit": pip}), which=lambda n: None)
    got = {(f.rule, f.path) for f in out if f.tool == "pip-audit"}
    assert got == {("V-requirements.txt", "requirements.txt"),
                   ("V-requirements-dev.txt", "requirements-dev.txt")}


# ---------------------------------------------------------------- fix round 4

def test_gitleaks_scans_content_of_ignore_files(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "d").mkdir()
    for name in (".gitignore", "d/.semgrepignore", ".gitleaksignore", ".gitleaks.toml"):
        (repo / name).write_text(f"# key {SECRET}\n")
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "-f", ".")
    seen = {}

    def leaks(argv, kw):
        src = Path(argv[-1])
        seen["root_names"] = sorted(p.name for p in src.iterdir())
        hits = sorted(str(p.relative_to(src)) for p in src.rglob("*")
                      if p.is_file() and SECRET in p.read_text())
        seen["hits"] = hits
        report = [{"RuleID": "aws-access-token", "File": str(src / h), "StartLine": 1,
                   "Description": "AWS"} for h in hits]
        Path(argv[argv.index("--report-path") + 1]).write_text(json.dumps(report))
        return cp("", 1)

    def semgrep(argv, kw):
        root = Path(kw["cwd"])
        seen["semgrep_ignores"] = sorted(
            str(p.relative_to(root)) for p in root.rglob("*")
            if p.name in (".semgrepignore", ".gitignore", ".gitleaksignore", ".gitleaks.toml"))
        return CLEAN

    out = scan.fast_scan(repo, run=FakeRun({"semgrep": semgrep, "gitleaks": leaks}))
    # every ignore file's content reached gitleaks, none under a name gitleaks honours
    assert len(seen["hits"]) == 4
    assert ".gitleaksignore" not in seen["root_names"] and ".gitleaks.toml" not in seen["root_names"]
    paths = sorted(f.path for f in out if f.tool == "gitleaks" and f.rule == "aws-access-token")
    assert paths == [".gitignore", ".gitleaks.toml", ".gitleaksignore", "d/.semgrepignore"]
    # semgrep never sees a repository ignore file under a name it honours
    assert seen["semgrep_ignores"] == [".semgrepignore"]
    # the root .semgrepignore semgrep saw is the empty one, and gitleaks saw no ignore file
    assert ".gitignore" not in seen["root_names"]


def lock_repo(tmp_path, files):
    repo, _ = full_repo(tmp_path, {"notes.md": "1\n"})
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "m")
    return repo


def test_root_npm_lock_covers_only_listed_packages(tmp_path):
    lock = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "packages/a": {},
                                                           "node_modules/x": {}}})
    repo = lock_repo(tmp_path, {"package.json": "{}\n", "package-lock.json": lock,
                                "packages/a/package.json": "{}\n",
                                "tools/unrelated/package.json": "{}\n",
                                "web/package.json": "{}\n", "web/package-lock.json": "{}\n"})
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: "/b")
    assert not_audited(out) == ["tools/unrelated/package.json"]


def test_root_uv_lock_covers_only_workspace_members(tmp_path):
    root = "[project]\nname='r'\n[tool.uv.workspace]\nmembers = ['libs/*']\nexclude = ['libs/skip']\n"
    repo = lock_repo(tmp_path, {"pyproject.toml": root, "uv.lock": "v\n",
                                "libs/one/pyproject.toml": "[project]\nname='one'\n",
                                "libs/skip/pyproject.toml": "[project]\nname='skip'\n",
                                "other/pyproject.toml": "[project]\nname='o'\n",
                                "same/pyproject.toml": "[project]\n", "same/poetry.lock": "v\n"})
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: "/b")
    assert not_audited(out) == ["libs/skip/pyproject.toml", "other/pyproject.toml"]


def test_root_lock_without_workspace_does_not_cover_nested(tmp_path):
    repo = lock_repo(tmp_path, {"uv.lock": "v\n", "pyproject.toml": "[project]\nname='r'\n",
                                "sub/pyproject.toml": "[project]\nname='s'\n",
                                "package-lock.json": "{}\n", "app/package.json": "{}\n"})
    out = scan.full_scan(repo, "main", run=audit_run(), which=lambda n: "/b")
    assert not_audited(out) == ["app/package.json", "sub/pyproject.toml"]


def test_unreadable_regular_file_is_high(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "bad.py").write_text("1\n")
    (repo / "ok.py").write_text("1\n")
    git(repo, "add", ".")
    real_open = open

    def fake_open(path, *a, **k):
        if str(path).endswith("bad.py"):
            raise PermissionError("denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr(scan, "open", fake_open, raising=False)
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    out = scan.fast_scan(repo, run=run)
    (f,) = [f for f in out if f.path == "bad.py"]
    assert (f.rule, f.severity) == ("scan.unreadable:bad.py", "high")
    assert run.argv("semgrep")[0][9:] == ["./ok.py"]


def test_history_clone_is_shared_and_checkout_less(tmp_path):
    repo, base = full_repo(tmp_path, {"a.txt": "1\n"})
    git(repo, "checkout", "-q", "--detach")
    (repo / "b.txt").write_text("2\n")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-q", "-m", "detached")  # reachable from no branch
    run = audit_run()
    scan.full_scan(repo, "main", run=run, which=lambda n: None)
    (clone,) = [a for a, _ in run.calls if a[:2] == ["git", "clone"]]
    assert "--shared" in clone and "--no-checkout" in clone and "--no-local" not in clone
    assert "--template=" in clone
    assert len(run.argv("gitleaks")) == 1


def test_git_environment_from_a_hook_is_ignored(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    other = make_repo(tmp_path / "other", {"elsewhere.py": "1\n"})
    (repo / "mine.py").write_text("eval(x)\n")
    git(repo, "add", "mine.py")
    repo2, _ = full_repo(tmp_path / "f", {"b.py": "1\n"})
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    scan.fast_scan(repo, run=run)
    assert run.argv("semgrep")[0][9:] == ["./mine.py"]
    for argv, kw in run.calls:
        env = kw.get("env")
        assert env is not None, argv
        assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"} & set(env), argv
    run = audit_run()
    scan.full_scan(repo2, "main", run=run, which=lambda n: None)
    read_tree = [kw for a, kw in run.calls if "read-tree" in a]
    assert read_tree and read_tree[0]["env"]["GIT_INDEX_FILE"] != str(other / ".git" / "index")
    assert all(kw.get("env") is not None and "GIT_DIR" not in kw["env"] for _, kw in run.calls)


# ---------------------------------------------------------------- fix round 5

def test_utf16_ignore_file_is_classified_not_skipped_silently(tmp_path):
    body = f"# key {SECRET}\n".encode("utf-16")  # NUL bytes: gitleaks regexes cannot match
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / ".gitignore").write_bytes(body)
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "-f", ".")
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    out = scan.fast_scan(repo, run=run)
    (f,) = [f for f in out if f.path == ".gitignore"]
    assert (f.rule, f.severity) == ("scan.skipped-binary:.gitignore", "high")
    assert run.argv("semgrep")[0][9:] == ["./a.py"]
    full, _ = full_repo(tmp_path / "f", {"a.py": "1\n"})
    (full / "d").mkdir()
    (full / "d/.semgrepignore").write_bytes(body)
    git(full, "add", "-f", ".")
    git(full, "commit", "-q", "-m", "ignore")
    out = scan.full_scan(full, "main", run=audit_run(), which=lambda n: None)
    (f,) = [f for f in out if f.path == "d/.semgrepignore"]
    assert (f.rule, f.severity) == ("scan.skipped-binary:d/.semgrepignore", "high")


def test_injected_git_config_does_not_change_targets(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    # config that makes every `git diff` die unless it is stripped
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.algorithm")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "nonsense")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'diff.algorithm'='nonsense'")
    bad = tmp_path / "gitconfig"
    bad.write_text("[diff]\n\talgorithm = nonsense\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(bad))
    run = FakeRun({"semgrep": CLEAN, "gitleaks": gl("[]")})
    scan.fast_scan(repo, run=run)
    assert run.argv("semgrep")[0][9:] == ["./a.py"]


def test_semgrep_ignores_an_outer_work_tree(tmp_path, monkeypatch):
    outer = make_repo(tmp_path / "outer", {".gitignore": "*\n!.gitignore\n"})
    (outer / "tmp").mkdir()
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("eval(x)\n")
    git(repo, "add", "a.py")
    monkeypatch.setattr(scan.tempfile, "tempdir", str(outer / "tmp"))
    seen = {}

    def semgrep(argv, kw):
        root = Path(kw["cwd"])
        seen["inside_outer"] = str(root).startswith(str(outer))
        seen["no_git_ignore"] = "--no-git-ignore" in argv[:7]
        seen["target"] = (root / argv[9]).read_text()
        return CLEAN

    scan.fast_scan(repo, run=FakeRun({"semgrep": semgrep, "gitleaks": gl("[]")}))
    assert seen == {"inside_outer": True, "no_git_ignore": True, "target": "eval(x)\n"}
