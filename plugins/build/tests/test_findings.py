import json
import os
import subprocess

import pytest

import findings
from findings import (
    ASSISTANT_STATUSES,
    MATT_ONLY,
    Finding,
    diff_hash,
    load,
    new_record,
    open_findings,
    save,
)

GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid"]


def git(cwd, *args):
    return subprocess.run(
        [*GIT, "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("hello\n")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    return path


def test_diff_hash_stable_with_binary(tmp_path):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "blob.bin").write_bytes(bytes(range(256)) * 64 + b"\x00\xff")
    (repo / "big.txt").write_text("line of text\n" * 500_000)  # > 5 MB
    assert (repo / "big.txt").stat().st_size > 5 * 1024 * 1024
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "feature")
    first = diff_hash(repo, base)
    second = diff_hash(repo, base, "HEAD")
    assert first == second
    assert len(first) == 64 and int(first, 16) >= 0
    # independent of the working tree: uncommitted edits and untracked files
    (repo / "big.txt").write_text("changed\n")
    (repo / "untracked.txt").write_text("x\n")
    assert diff_hash(repo, base) == first


def test_diff_hash_changes_with_content(tmp_path):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("one\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "a")
    one = diff_hash(repo, base)
    (repo / "a.txt").write_text("two\n")
    git(repo, "commit", "-qam", "b")
    assert diff_hash(repo, base) != one


def test_diff_hash_bad_ref_raises(tmp_path):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(RuntimeError):
        diff_hash(repo, "no-such-ref")


def sample(**kw):
    base = dict(
        tool="semgrep",
        rule="r1",
        severity="high",
        path="a.py",
        line=3,
        message="m",
    )
    base.update(kw)
    return Finding.create(**base)


def test_open_findings(tmp_path):
    f1, f2 = sample(), sample(rule="r2")
    record = new_record("main", "abc", "d" * 64, [f1, f2])
    assert [f["status"] for f in record["findings"]] == ["open", "open"]
    record["findings"][0]["status"] = "fixed"
    record["findings"][1]["status"] = "proposed-false-positive"
    assert open_findings(record) == []
    record["findings"][1]["status"] = "open"
    assert [f["id"] for f in open_findings(record)] == [f2.id]
    assert findings.unresolved(record) == record["findings"][1:]


def test_status_sets():
    assert ASSISTANT_STATUSES == {"open", "fixed", "proposed-false-positive"}
    assert MATT_ONLY == {"false-positive", "accepted-risk"}
    assert not ASSISTANT_STATUSES & MATT_ONLY


def test_record_keys_and_roundtrip(tmp_path):
    record = new_record("main", "abc", "d" * 64, [sample()])
    entry = record["findings"][0]
    assert set(entry) == {
        "id", "tool", "rule", "severity", "path", "line", "message",
        "status", "test", "fix_commit", "reason", "closed_by",
    }
    path = tmp_path / "sub" / "security.json"
    save(path, record)
    assert load(path) == record


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.json")


def test_save_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "security.json"
    old = new_record("main", "abc", "d" * 64, [])
    save(path, old)

    def boom(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    new = new_record("main", "def", "e" * 64, [sample()])
    with pytest.raises(OSError):
        save(path, new)
    monkeypatch.undo()
    assert json.loads(path.read_text()) == old  # original untouched
    assert [p.name for p in tmp_path.iterdir()] == ["security.json"]  # no temp left


def test_diff_hash_rejects_option_like_refs(tmp_path):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(ValueError):
        diff_hash(repo, "--output=/tmp/x")
    with pytest.raises(ValueError):
        diff_hash(repo, "HEAD", "-p")
    with pytest.raises(ValueError):
        diff_hash(repo, "HEAD main")


def test_diff_hash_ignores_user_diff_config(tmp_path):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "old.txt").write_text("".join(f"line {i}\n" for i in range(30)))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "a")
    git(repo, "mv", "old.txt", "new.txt")
    git(repo, "commit", "-q", "-m", "rename")
    plain = diff_hash(repo, base)
    git(repo, "config", "diff.renames", "copies")
    git(repo, "config", "diff.algorithm", "patience")
    git(repo, "config", "diff.indentHeuristic", "false")
    git(repo, "config", "diff.suppressBlankEmpty", "true")
    git(repo, "config", "diff.relative", "true")
    assert diff_hash(repo, base) == plain


def test_diff_hash_ignores_git_environment(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "a")
    other = make_repo(tmp_path / "other")
    want = diff_hash(repo, base)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    assert diff_hash(repo, base) == want
    assert findings.toplevel(repo / ".") == findings.toplevel(repo)
    env = findings.git_env()
    assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"} & set(env) and env.get("PATH")
    assert findings.git_env(GIT_INDEX_FILE="/x")["GIT_INDEX_FILE"] == "/x"


def test_diff_hash_ignores_injected_git_config(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "a")
    want = diff_hash(repo, base)
    attrs = tmp_path / "attrs"
    attrs.write_text("*.txt -diff\n")  # would turn the text patch into a binary one
    plain = subprocess.run(["git", "-C", str(repo), "diff", "--binary", f"{base}..HEAD"],
                           capture_output=True).stdout
    changed = subprocess.run(["git", "-C", str(repo), "-c", f"core.attributesFile={attrs}",
                              "diff", "--binary", f"{base}..HEAD"], capture_output=True).stdout
    assert plain != changed  # sanity: the injected setting really alters diff output
    glob_cfg = tmp_path / "gitconfig"
    glob_cfg.write_text(f"[core]\n\tattributesFile = {attrs}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(glob_cfg))
    assert diff_hash(repo, base) == want
    monkeypatch.delenv("GIT_CONFIG_GLOBAL")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.attributesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(attrs))
    assert diff_hash(repo, base) == want
    monkeypatch.delenv("GIT_CONFIG_COUNT")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'core.attributesfile'='{attrs}'")
    assert diff_hash(repo, base) == want
    env = findings.git_env()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert not {"GIT_CONFIG_PARAMETERS", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"} & set(env)
