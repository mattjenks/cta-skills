import json
import subprocess

import pytest

import findings
import scan
import secure

GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid"]


def git(cwd, *a):
    return subprocess.run([*GIT, "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.py").write_text("x = 1\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    git(r, "checkout", "-q", "-b", "feat")
    (r / "a.py").write_text("x = 2\n")
    git(r, "commit", "-qam", "change")
    return r


def fake_scan(found):
    return lambda repo, base, **kw: found


def test_missing_scanner_stops_with_install_command(repo, tmp_path, capsys):
    out = tmp_path / "s.json"
    rc = secure.main(["scan", "--repo", str(repo), "--base", "main", "--out", str(out)],
                     which=lambda n: None)
    assert rc == 3 and not out.exists()
    err = capsys.readouterr().err
    assert "brew install semgrep" in err and "brew install gitleaks" in err


def test_scan_writes_record_with_diff_hash(repo, tmp_path):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    rc = secure.main(["scan", "--repo", str(repo), "--base", "main", "--out", str(out)],
                     which=lambda n: "/x", scan_fn=fake_scan([f]))
    assert rc == 0
    rec = json.loads(out.read_text())
    assert rec["diff_hash"] == findings.diff_hash(repo, "main", "HEAD")
    assert rec["head"] == git(repo, "rev-parse", "HEAD")
    assert rec["findings"][0]["status"] == "open"


def test_scan_error_stops_and_writes_nothing(repo, tmp_path, capsys):
    def boom(repo, base, **kw):
        raise scan.ScanError("pip-audit", "pip-audit is not installed")

    out = tmp_path / "s.json"
    rc = secure.main(["scan", "--repo", str(repo), "--base", "main", "--out", str(out)],
                     which=lambda n: "/x", scan_fn=boom)
    assert rc == 3 and not out.exists()
    assert "uv tool install pip-audit" in capsys.readouterr().err


def test_rescan_keeps_existing_statuses(repo, tmp_path):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    args = ["scan", "--repo", str(repo), "--base", "main", "--out", str(out)]
    secure.main(args, which=lambda n: "/x", scan_fn=fake_scan([f]))
    rec = json.loads(out.read_text())
    rec["findings"][0]["status"] = "fixed"
    out.write_text(json.dumps(rec))
    secure.main(args, which=lambda n: "/x", scan_fn=fake_scan([f]))
    assert json.loads(out.read_text())["findings"][0]["status"] == "fixed"


def test_stamp_refreshes_head_and_hash(repo, tmp_path):
    out = tmp_path / "s.json"
    secure.main(["scan", "--repo", str(repo), "--base", "main", "--out", str(out)],
                which=lambda n: "/x", scan_fn=fake_scan([]))
    (repo / "a.py").write_text("x = 3\n")
    git(repo, "commit", "-qam", "fix")
    assert secure.main(["stamp", "--repo", str(repo), "--base", "main", "--out", str(out)]) == 0
    rec = json.loads(out.read_text())
    assert rec["head"] == git(repo, "rev-parse", "HEAD")
    assert rec["diff_hash"] == findings.diff_hash(repo, "main", "HEAD")


def test_stamp_without_record_fails(repo, tmp_path):
    assert secure.main(["stamp", "--repo", str(repo), "--base", "main", "--out", str(tmp_path / "no.json")]) == 2
