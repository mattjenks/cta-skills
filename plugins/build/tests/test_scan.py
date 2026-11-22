import json
import subprocess
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
        return ans(argv) if callable(ans) else ans

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
    run = FakeRun({"semgrep": cp(SEMGREP_OUT, 1), "gitleaks": cp(GITLEAKS_OUT, 1)})
    out = scan.fast_scan(repo, staged=True, run=run)
    by_tool = {(f.tool, f.rule): f for f in out}
    sg = by_tool[("semgrep", "python.lang.security.eval")]
    assert (sg.path, sg.line, sg.severity, sg.message) == ("app.py", 7, "high", "Avoid eval")
    assert by_tool[("semgrep", "python.style.x")].severity == "medium"
    gl = by_tool[("gitleaks", "aws-access-token")]
    assert (gl.path, gl.line, gl.message) == ("app.py", 2, "AWS access token")
    # semgrep got staged paths as argv, deletions skipped, no shell
    (sargv,) = run.argv("semgrep")
    assert sargv[:5] == ["semgrep", "--config", "p/default", "--error", "--json"]
    assert sorted(sargv[5:]) == ["app.py", "new file.py"]
    (gargv,) = run.argv("gitleaks")
    assert "--staged" in gargv and "json" in gargv


def test_fast_scan_nothing_staged_skips_semgrep(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    run = FakeRun({"gitleaks": cp("[]", 0)})
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
    run = FakeRun({"semgrep": cp(json.dumps({"results": []}), 0), "gitleaks": cp(GITLEAKS_OUT, 1)})
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
    repo, base = full_repo(tmp_path, {"package.json": "{}\n", "app.js": "1\n"})
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
            "gitleaks": cp("[]", 0),
            "osv-scanner": cp(osv, 1),
        }
    )
    out = scan.full_scan(repo, "main", run=run, which=lambda n: None)
    assert run.argv("npm") == []
    assert len(run.argv("osv-scanner")) == 1
    (dep,) = [f for f in out if f.tool == "osv-scanner"]
    assert dep.rule == "GHSA-xxxx" and dep.severity == "high"
    assert dep.path == "package-lock.json" and "left-pad" in dep.message
    # semgrep was handed only the branch diff files
    (sargv,) = run.argv("semgrep")
    assert sorted(sargv[5:]) == ["app.js", "package.json"]
    assert any("main..HEAD" in a for a in run.argv("gitleaks")[0])


def test_full_scan_uses_npm_and_pip_audit(tmp_path):
    repo, base = full_repo(tmp_path, {"package.json": "{}\n", "app.py": "1\n"})
    npm = json.dumps(
        {"vulnerabilities": {"lodash": {"name": "lodash", "severity": "critical",
         "via": [{"title": "Proto pollution", "url": "u"}]}}}
    )
    pipa = json.dumps(
        {"dependencies": [{"name": "django", "version": "1.0",
         "vulns": [{"id": "PYSEC-1", "description": "SQLi", "fix_versions": ["2"]}]},
         {"name": "ok", "version": "1", "vulns": []}]}
    )
    run = FakeRun(
        {
            "semgrep": cp(json.dumps({"results": []}), 0),
            "gitleaks": cp("[]", 0),
            "npm": cp(npm, 1),
            "pip-audit": cp(pipa, 1),
        }
    )
    (repo / "requirements.txt").write_text("django==1.0\n")
    out = scan.full_scan(repo, "main", run=run, which=lambda n: "/bin/" + n)
    tools = {f.tool: f for f in out}
    assert tools["npm"].severity == "critical" and tools["npm"].rule == "lodash"
    assert tools["pip-audit"].rule == "PYSEC-1" and tools["pip-audit"].severity == "high"
    assert run.argv("osv-scanner") == []
    assert run.argv("npm")[0][:3] == ["npm", "audit", "--json"]


def test_scanner_failure_is_not_no_findings(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})
    (repo / "a.py").write_text("1\n")
    git(repo, "add", "a.py")
    run = FakeRun({"semgrep": cp("Traceback ...", 2, "boom\n" * 100), "gitleaks": cp("[]", 0)})
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, staged=True, run=run)
    assert ei.value.tool == "semgrep" and "boom" in str(ei.value)
    assert len(ei.value.stderr_tail) <= 2000
    # exit 1 with garbage output is also an error, never "clean"
    run = FakeRun({"semgrep": cp("not json", 1), "gitleaks": cp("[]", 0)})
    with pytest.raises(ScanError):
        scan.fast_scan(repo, staged=True, run=run)
    run = FakeRun({"semgrep": cp('{"results": []}', 0), "gitleaks": cp("oops", 1, "bad")})
    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, staged=True, run=run)
    assert ei.value.tool == "gitleaks"


def test_scanner_not_installed_raises(tmp_path):
    repo = make_repo(tmp_path / "r", {"README.md": "x\n"})

    def run(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        raise FileNotFoundError(argv[0])

    with pytest.raises(ScanError) as ei:
        scan.fast_scan(repo, staged=True, run=run)
    assert ei.value.tool == "gitleaks"  # gitleaks needs no staged paths, runs first
