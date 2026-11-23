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


def run_scan(repo, out, found, capsys=None):
    return secure.main(["scan", "--repo", str(repo), "--base", "main", "--out", str(out)],
                       which=lambda n: "/x", scan_fn=fake_scan(found))


def set_status(out, status):
    rec = json.loads(out.read_text())
    rec["findings"][0]["status"] = status
    out.write_text(json.dumps(rec))


def test_stamp_subcommand_is_gone(repo, tmp_path):
    with pytest.raises(SystemExit):
        secure.main(["stamp", "--repo", str(repo), "--base", "main", "--out", str(tmp_path / "s.json")])


def test_rescan_refreshes_head_and_hash_after_new_commit(repo, tmp_path):
    out = tmp_path / "s.json"
    run_scan(repo, out, [])
    (repo / "a.py").write_text("x = 3\n")
    git(repo, "commit", "-qam", "fix")
    run_scan(repo, out, [])
    rec = json.loads(out.read_text())
    assert rec["head"] == git(repo, "rev-parse", "HEAD")
    assert rec["diff_hash"] == findings.diff_hash(repo, "main", "HEAD")


def test_rediscovered_fixed_reopens(repo, tmp_path):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    set_status(out, "fixed")
    run_scan(repo, out, [f])
    assert json.loads(out.read_text())["findings"][0]["status"] == "open"


@pytest.mark.parametrize("status", ["false-positive", "accepted-risk", "proposed-false-positive"])
def test_rescan_never_changes_closed_or_proposed(repo, tmp_path, status):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    set_status(out, status)
    run_scan(repo, out, [f])
    assert json.loads(out.read_text())["findings"][0]["status"] == status


def test_not_rediscovered_left_alone(repo, tmp_path):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    set_status(out, "fixed")
    run_scan(repo, out, [])
    assert json.loads(out.read_text())["findings"][0]["status"] == "fixed"


def test_not_rediscovered_label_in_output(repo, tmp_path, capsys):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    capsys.readouterr()
    run_scan(repo, out, [])
    text = capsys.readouterr().out
    assert "not rediscovered" in text and f.id in text


def test_corrupt_record_exits_2_with_message(repo, tmp_path, capsys):
    out = tmp_path / "s.json"
    out.write_text("{not json")
    rc = run_scan(repo, out, [])
    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert out.read_text() == "{not json"


# --- verify (what `pr` checks before it opens anything) ---


def verify(repo, out):
    return secure.main(["verify", "--repo", str(repo), "--base", "main", "--file", str(out)])


def test_verify_clean_record_passes(repo, tmp_path, capsys):
    out = tmp_path / "s.json"
    run_scan(repo, out, [])
    assert verify(repo, out) == 0


def test_verify_stale_after_new_commit(repo, tmp_path, capsys):
    out = tmp_path / "s.json"
    run_scan(repo, out, [])
    (repo / "a.py").write_text("x = 9\n")
    git(repo, "commit", "-qam", "later")
    assert verify(repo, out) == 4
    assert "diff_hash" in capsys.readouterr().err


def test_verify_missing_file_is_stale(repo, tmp_path):
    assert verify(repo, tmp_path / "none.json") == 4


def test_verify_open_finding_blocks(repo, tmp_path, capsys):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    assert verify(repo, out) == 5
    assert f.id in capsys.readouterr().err


def test_verify_lists_proposed_and_exits_6(repo, tmp_path, capsys):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    set_status(out, "proposed-false-positive")
    assert verify(repo, out) == 6
    assert json.loads(capsys.readouterr().out)["proposed"][0]["id"] == f.id


@pytest.mark.parametrize("status", ["false-positive", "accepted-risk"])
def test_verify_owner_closure_passes_only_with_closed_by(repo, tmp_path, status):
    f = findings.Finding.create("semgrep", "r1", "a.py", 1, "high", "bad")
    out = tmp_path / "s.json"
    run_scan(repo, out, [f])
    rec = json.loads(out.read_text())
    rec["findings"][0].update(status=status, reason="why", closed_by=None)
    out.write_text(json.dumps(rec))
    assert verify(repo, out) == 5
    rec["findings"][0]["closed_by"] = "matt"
    out.write_text(json.dumps(rec))
    assert verify(repo, out) == 0
