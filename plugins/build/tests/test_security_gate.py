import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import security_gate
from findings import Finding

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "security_gate.py"
GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.invalid"]


def git(cwd, *args):
    return subprocess.run([*GIT, "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def make_repo(path, files=None, gated=False):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("# demo\n")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    if gated:
        pointer = path / ".cta" / "active-build"
        pointer.parent.mkdir()
        pointer.write_text("{}")
    for name, text in (files or {}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    return path


def stage(repo, *names):
    git(repo, "add", *names)


def bash(command, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def finding(severity="high", rule="r.x", path="a.py", line=3, message="bad"):
    return Finding.create("semgrep", rule, path, line, severity, message)


def have(*names):
    return lambda n: f"/bin/{n}" if n in names else None


ALL = have("semgrep", "gitleaks", "osv-scanner")


def never_scan(_repo):
    raise AssertionError("scan must not run")


def run(command, cwd, scan_fn=None, which_fn=None, capsys=None):
    code = security_gate.main(bash(command, cwd), scan_fn or (lambda r: []), which_fn or ALL)
    return code, (capsys.readouterr().err if capsys else "")


@pytest.fixture
def gated(tmp_path):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"}, gated=True)
    stage(repo, "a.py")
    return repo


# ---- Review Focus 1: not gated outside runs -------------------------------

def test_gate_inactive_outside_run_allows(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    stage(repo, "a.py")
    code, err = run("git commit -m x", repo, never_scan, lambda n: None, capsys)
    assert code == 0 and err == ""


def test_not_gated_never_refuses_paths(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    for cmd in ("git commit -am x", "git commit -m x a.py", "git add . && git commit -m x"):
        assert run(cmd, repo, never_scan, lambda n: None, capsys)[0] == 0


def test_tracked_security_toml_gates(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {".cta/security.toml": "[x]\n", "a.py": "x = 1\n"})
    stage(repo, ".cta/security.toml", "a.py")
    git(repo, "commit", "-q", "-m", "cfg")
    (repo / "b.py").write_text("y = 2\n")
    stage(repo, "b.py")
    code, err = run("git commit -m x", repo, which_fn=lambda n: None, capsys=capsys)
    assert code == 2 and "install semgrep, gitleaks" in err


def test_untracked_security_toml_does_not_gate(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {".cta/security.toml": "[x]\n", "a.py": "x = 1\n"})
    stage(repo, "a.py")
    assert run("git commit -m x", repo, never_scan, lambda n: None, capsys)[0] == 0


def test_not_a_git_repo_allows(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert run("git commit -m x", plain, never_scan, lambda n: None, capsys)[0] == 0


def test_non_commit_commands_allowed(gated, capsys):
    for cmd in ("git status", "git log --oneline", "echo 'git commit -m x'", "git commit-tree HEAD^{tree}",
                "grep commit notes.txt", "ls"):
        assert run(cmd, gated, never_scan, lambda n: None, capsys)[0] == 0, cmd


def test_non_bash_tool_allowed(gated):
    payload = {"tool_name": "Write", "tool_input": {"file_path": "x", "content": "git commit"}}
    assert security_gate.main(payload, never_scan, lambda n: None) == 0


# ---- exemptions, scanners, findings ---------------------------------------

def test_gate_markdown_only_exempt(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", gated=True)
    (repo / "notes.md").write_text("hi\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "b.md").write_text("hi\n")
    stage(repo, "notes.md", "docs/b.md")
    assert run("git commit -m x", repo, never_scan, lambda n: None, capsys)[0] == 0


def test_nothing_staged_allows(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", gated=True)
    assert run("git commit -m x", repo, never_scan, lambda n: None, capsys)[0] == 0


def test_missing_scanner_blocks(gated, capsys):
    code, err = run("git commit -m x", gated, never_scan, have("gitleaks"), capsys)
    assert code == 2
    assert "security gate: install semgrep (brew install semgrep)" in err
    code, err = run("git commit -m x", gated, never_scan, lambda n: None, capsys)
    assert code == 2 and "install semgrep, gitleaks (brew install semgrep gitleaks)" in err


def test_manifest_requires_osv_scanner(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {"package-lock.json": "{}\n"}, gated=True)
    stage(repo, "package-lock.json")
    code, err = run("git commit -m x", repo, never_scan, have("semgrep", "gitleaks"), capsys)
    assert code == 2 and "install osv-scanner" in err
    assert run("git commit -m x", repo, which_fn=ALL, capsys=capsys)[0] == 0


def test_source_only_does_not_require_osv_scanner(gated, capsys):
    assert run("git commit -m x", gated, which_fn=have("semgrep", "gitleaks"), capsys=capsys)[0] == 0


def test_findings_block_commit(gated, capsys):
    found = [finding("high", "r.sql", "a.py", 3, "sql\ninjection"), finding("info", "r.note", "a.py", 9, "fyi")]
    code, err = run("git commit -m x", gated, lambda r: found, capsys=capsys)
    assert code == 2
    assert "[high] a.py:3 r.sql - sql injection" in err
    assert "[info] a.py:9 r.note - fyi" in err


def test_findings_list_capped_at_ten(gated, capsys):
    found = [finding("medium", f"r.{i}", "a.py", i) for i in range(14)]
    code, err = run("git commit -m x", gated, lambda r: found, capsys=capsys)
    assert code == 2
    assert err.count("[medium]") == 10 and "and 4 more" in err


def test_low_blocks_info_does_not(gated, capsys):
    assert run("git commit -m x", gated, lambda r: [finding("low")], capsys=capsys)[0] == 2
    code, err = run("git commit -m x", gated, lambda r: [finding("info")], capsys=capsys)
    assert code == 0 and "[info]" in err


def test_clean_scan_allows(gated, capsys):
    scanned = []
    code, err = run("git commit -m x", gated, lambda r: scanned.append(r) or [], capsys=capsys)
    assert code == 0 and err == ""
    assert scanned == [gated.resolve()] or scanned == [gated]


def test_internal_error_fails_closed(gated, capsys):
    def boom(_repo):
        raise RuntimeError("secret detail")

    code, err = run("git commit -m x", gated, boom, capsys=capsys)
    assert code == 2 and "security gate error: RuntimeError" in err
    assert "secret detail" not in err


def test_scan_error_names_tool(gated, capsys):
    from scan import ScanError

    def boom(_repo):
        raise ScanError("semgrep", "x")

    code, err = run("git commit -m x", gated, boom, capsys=capsys)
    assert code == 2 and "security gate error: ScanError (semgrep)" in err


def test_scanner_discovery_error_fails_closed(gated, capsys):
    def boom(_name):
        raise OSError("nope")

    assert run("git commit -m x", gated, never_scan, boom, capsys)[0] == 2


# ---- command detection ----------------------------------------------------

DETECTED = [
    "git commit -m x",
    "git commit -m 'a; b && c'",
    "git -C {repo} commit -m x",
    "/usr/bin/git commit -m x",
    "git -c user.name=Ada commit -m x",
    "git -c core.pager=cat --no-pager commit -m x",
    "cd {repo} && git commit -m x",
    "(cd {repo}; git commit -m x)",
    "echo ok; git commit -m x",
    "echo ok | git commit -F -",
    "echo $(git commit -m x)",
    "echo `git commit -m x`",
    "FOO=1 git commit -m x",
    "env FOO=1 git commit -m x",
    "bash -c 'git commit -m x'",
    "sh -c \"cd {repo} && git commit -m x\"",
    "eval 'git commit -m x'",
    "git commit --amend --no-edit",
    "git commit -m \"it's\" > /tmp/out 2>&1",
    "git -c alias.ci=commit ci -m x",
    "git com\"mit\" -m x",
    "git commit -m 'unterminated",
]


@pytest.mark.parametrize("template", DETECTED)
def test_detects_commit_forms(template, tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"}, gated=True)
    stage(repo, "a.py")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    command = template.format(repo=repo)
    cwd = elsewhere if "{repo}" in template else repo
    code, err = run(command, cwd, lambda r: [finding("high")], capsys=capsys)
    assert code == 2 and "security gate" in err, (command, err)


def test_detects_git_dash_c_commit(tmp_path, capsys):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"}, gated=True)
    stage(repo, "a.py")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    code, err = run(f"git -C {repo} commit -m x", elsewhere, lambda r: [finding()], capsys=capsys)
    assert code == 2 and "[high]" in err
    code, err = run(f"git -C {repo} commit -am x", elsewhere, capsys=capsys)
    assert code == 2 and "git add" in err


def test_dash_c_in_other_repo_is_judged_by_that_repo(tmp_path, capsys):
    gated_repo = make_repo(tmp_path / "gated", {"a.py": "x\n"}, gated=True)
    plain = make_repo(tmp_path / "plain", {"b.py": "y\n"})
    stage(plain, "b.py")
    code, _ = run(f"git -C {plain} commit -m x", gated_repo, never_scan, lambda n: None, capsys)
    assert code == 0


def test_chained_cd_resolves_relative(tmp_path, capsys):
    repo = make_repo(tmp_path / "work" / "repo", {"a.py": "x = 1\n"}, gated=True)
    stage(repo, "a.py")
    code, _ = run("cd repo && git commit -m x", tmp_path / "work", lambda r: [finding()], capsys=capsys)
    assert code == 2


# ---- paths and staging flags ----------------------------------------------

REFUSED = [
    "git commit -a -m x", "git commit -am x", "git commit -qam x", "git commit --all -m x",
    "git commit -i a.py -m x", "git commit --include a.py", "git commit -o a.py",
    "git commit --only a.py", "git commit -m x a.py", "git commit -m x -- a.py",
    "git commit -m x -p", "git commit --patch",
    "git commit -m x --pathspec-from-file=list.txt",
    "git add a.py && git commit -m x", "git add -A; git commit -m x", "git rm a.py && git commit -m x",
    "git stash pop && git commit -m x", "GIT_INDEX_FILE=/tmp/x git commit -m x",
]


@pytest.mark.parametrize("command", REFUSED)
def test_gated_refuses_paths_and_staging(command, gated, capsys):
    code, err = run(command, gated, never_scan, capsys=capsys)
    assert code == 2 and "git add" in err and "without paths" in err, (command, err)


ACCEPTED = [
    "git commit -m x", "git commit -m 'fix -a flag'", "git commit -m \"a b\" --amend",
    "git commit -sm x", "git commit --message x", "git commit -F msg.txt", "git commit -C HEAD",
    "git commit -c HEAD --amend", "git commit --author='Ada <a@b.c>' -m x",
    "git commit -m x --no-verify", "git commit --cleanup strip -m x", "git commit -S -m x",
    "git commit -n -m x", "git status && git commit -m x",
]


@pytest.mark.parametrize("command", ACCEPTED)
def test_gated_accepts_plain_commits(command, gated, capsys):
    code, err = run(command, gated, lambda r: [], capsys=capsys)
    assert code == 0, (command, err)


def test_commit_message_heredoc_is_not_pathspec(gated, capsys):
    cmd = "git commit -m \"$(cat <<'EOF'\nfix: a thing (it's -a fine)\n\nbody\nEOF\n)\""
    code, err = run(cmd, gated, lambda r: [], capsys=capsys)
    assert code == 0, err


# ---- subprocess level: the real file, fake scanners on PATH ---------------

def fake_scanners(directory: Path, semgrep_results="[]"):
    directory.mkdir(parents=True, exist_ok=True)
    scripts = {
        "semgrep": f'#!/bin/sh\necho \'{{"results": {semgrep_results}, "errors": []}}\'\n',
        "gitleaks": (
            '#!/bin/sh\nwhile [ $# -gt 0 ]; do\n'
            '  if [ "$1" = "--report-path" ]; then echo "[]" > "$2"; fi\n  shift\ndone\n'
        ),
    }
    for name, body in scripts.items():
        path = directory / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return directory


def run_hook(payload, path_dirs):
    git_dir = Path(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()).parent
    env = {"PATH": os.pathsep.join([*map(str, path_dirs), str(git_dir)]), "HOME": str(path_dirs[0])}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env)


def test_subprocess_missing_scanner_blocks(gated, tmp_path):
    empty = tmp_path / "bin"
    empty.mkdir()
    result = run_hook(bash("git commit -m x", gated), [empty])
    assert result.returncode == 2
    assert "install semgrep, gitleaks" in result.stderr


def test_subprocess_clean_commit_allowed(gated, tmp_path):
    result = run_hook(bash("git commit -m x", gated), [fake_scanners(tmp_path / "bin")])
    assert result.returncode == 0, result.stderr


def test_subprocess_findings_block(gated, tmp_path):
    results = json.dumps([{"check_id": "r.sql", "path": "a.py", "start": {"line": 1},
                           "extra": {"severity": "ERROR", "message": "sql injection"}}])
    result = run_hook(bash("git commit -m x", gated), [fake_scanners(tmp_path / "bin", results)])
    assert result.returncode == 2
    assert "r.sql" in result.stderr


def test_subprocess_outside_run_allows_without_scanners(tmp_path):
    repo = make_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    stage(repo, "a.py")
    empty = tmp_path / "bin"
    empty.mkdir()
    assert run_hook(bash("git commit -m x", repo), [empty]).returncode == 0


def test_subprocess_bad_input_allows(tmp_path):
    empty = tmp_path / "bin"
    empty.mkdir()
    result = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    assert result.returncode == 0
