"""The commit gate as real git hooks (pre-commit, pre-merge-commit, pre-applypatch).

Real throwaway repositories with an explicit identity; scanners are faked through a
directory on PATH. Every `git commit` here runs the real hook files through uv.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

import gitgate
import kbwork
from findings import Finding

PLUGIN = Path(__file__).resolve().parent.parent
HOOK_DIR = PLUGIN / "hooks" / "git"
HOOK_NAMES = ("pre-commit", "pre-merge-commit", "pre-applypatch")
MARK = "DANGER"

FAKE_SEMGREP = """#!/bin/sh
# flags every scanned file whose text contains the marker
hits=""
for a in "$@"; do
  case "$a" in -*) continue;; esac
  if [ -f "$a" ] && grep -q MARK "$a"; then
    hits="$hits{\\"check_id\\":\\"r.danger\\",\\"path\\":\\"$a\\",\\"start\\":{\\"line\\":1},\\"extra\\":{\\"severity\\":\\"ERROR\\",\\"message\\":\\"marker found\\"}},"
  fi
done
echo "{\\"results\\": [${hits%,}], \\"errors\\": []}"
""".replace("MARK", MARK)

FAKE_GITLEAKS = """#!/bin/sh
while [ $# -gt 0 ]; do
  if [ "$1" = "--report-path" ]; then echo "[]" > "$2"; fi
  shift
done
"""


def _exe(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def bins(tmp_path):
    tools = tmp_path / "toolbin"
    tools.mkdir()
    for tool in ("uv", "git"):
        (tools / tool).symlink_to(shutil.which(tool))
    fake = tmp_path / "fakebin"
    fake.mkdir()
    _exe(fake / "semgrep", FAKE_SEMGREP)
    _exe(fake / "gitleaks", FAKE_GITLEAKS)
    return {"tools": tools, "fake": fake}


def make_env(bins, scanners=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    dirs = ([str(bins["fake"])] if scanners else []) + [str(bins["tools"]), "/usr/bin", "/bin"]
    env.update({
        "PATH": os.pathsep.join(dirs), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_EDITOR": "true", "EDITOR": "true", "VISUAL": "true", "GIT_SEQUENCE_EDITOR": "true",
        "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "PAGER": "cat",
    })
    return env


@pytest.fixture
def env(bins):
    return make_env(bins)


def git(repo, env, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env,
                          check=check, stdin=subprocess.DEVNULL)


def sh(command, cwd, env, timeout=60):
    return subprocess.run(["bash", "-c", command], cwd=str(cwd), capture_output=True, text=True,
                          env=env, stdin=subprocess.DEVNULL, timeout=timeout)


def make_repo(path: Path, env, gated=False, install=False) -> Path:
    path.mkdir(parents=True)
    git(path, env, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Ada"), ("user.email", "ada@example.invalid"),
                       ("commit.gpgsign", "false")):
        git(path, env, "config", key, value)
    (path / "README.md").write_text("# demo\n")
    (path / "b.py").write_text("y = 1\n")
    (path / "sub" / "deep").mkdir(parents=True)
    (path / "sub" / "deep" / "k.txt").write_text("k\n")
    git(path, env, "add", ".")
    git(path, env, "commit", "-q", "-m", "init")
    if gated:
        (path / ".cta").mkdir()
        (path / ".cta" / "active-build").write_text("{}\n")
        kbwork.exclude_path(path, ".cta/active-build")
    if install:
        gitgate.install_gate(path)
    return path


def head(repo, env):
    return git(repo, env, "rev-parse", "HEAD").stdout.strip()


def leaked(repo, env) -> bool:
    """Does any commit on a branch (or HEAD) contain the marker?"""
    revs = git(repo, env, "rev-list", "--branches", "HEAD").stdout.split()
    return any(git(repo, env, "grep", "-q", MARK, r, check=False).returncode == 0 for r in revs)


@pytest.fixture
def gated(tmp_path, env):
    return make_repo(tmp_path / "repo", env, gated=True, install=True)


# ---- hook files --------------------------------------------------------------------

def test_hook_files_exist_executable_identical():
    bodies = set()
    for name in HOOK_NAMES:
        path = HOOK_DIR / name
        assert path.is_file() and os.access(path, os.X_OK), path
        text = path.read_text()
        assert text.startswith("#!/usr/bin/env -S uv run --script\n")
        assert 'requires-python = ">=3.12"' in text
        bodies.add(text)
    assert len(bodies) == 1


def test_hooks_dir_resolves_from_plugin_location():
    assert gitgate.hooks_dir() == HOOK_DIR.resolve()


# ---- install / uninstall -------------------------------------------------------------

def hooks_path(repo, env):
    out = git(repo, env, "config", "--local", "--get", "core.hooksPath", check=False)
    return out.stdout.strip() or None


def test_install_sets_hooks_path_and_records_state(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    assert not gitgate.gate_installed(repo)
    gitgate.install_gate(repo)
    assert hooks_path(repo, env) == str(HOOK_DIR.resolve())
    assert gitgate.gate_installed(repo)
    state = json.loads((repo / ".cta" / "gate.json").read_text())
    assert state == {"hooks_path": str(HOOK_DIR.resolve()), "previous": None}
    assert git(repo, env, "status", "--porcelain").stdout == ""  # gate.json git-excluded


def test_install_is_idempotent_and_keeps_previous(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    git(repo, env, "config", "core.hooksPath", "myhooks")
    gitgate.install_gate(repo)
    gitgate.install_gate(repo)
    state = json.loads((repo / ".cta" / "gate.json").read_text())
    assert state["previous"] == "myhooks"
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count(".cta/gate.json") == 1
    gitgate.uninstall_gate(repo)
    assert hooks_path(repo, env) == "myhooks"
    assert not (repo / ".cta" / "gate.json").exists()
    assert not gitgate.gate_installed(repo)


def test_uninstall_without_previous_unsets(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    gitgate.install_gate(repo)
    gitgate.uninstall_gate(repo)
    assert hooks_path(repo, env) is None
    gitgate.uninstall_gate(repo)  # idempotent


def test_install_over_stale_plugin_dir_keeps_previous(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    (repo / ".cta").mkdir()
    old = str(tmp_path / "old-plugin" / "hooks" / "git")
    (repo / ".cta" / "gate.json").write_text(json.dumps({"hooks_path": old, "previous": "mine"}))
    git(repo, env, "config", "core.hooksPath", old)
    assert not gitgate.gate_installed(repo)  # the recorded directory is gone
    gitgate.install_gate(repo)
    assert hooks_path(repo, env) == str(HOOK_DIR.resolve())
    assert json.loads((repo / ".cta" / "gate.json").read_text())["previous"] == "mine"


def test_uninstall_leaves_a_foreign_hooks_path(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    gitgate.install_gate(repo)
    git(repo, env, "config", "core.hooksPath", "other")
    gitgate.uninstall_gate(repo)
    assert hooks_path(repo, env) == "other"


# ---- not gated ------------------------------------------------------------------------

def test_not_gated_commit_passes_without_scanners(tmp_path, bins):
    env = make_env(bins, scanners=False)
    repo = make_repo(tmp_path / "repo", env, install=True)
    (repo / "a.py").write_text(f"x = '{MARK}'\n")
    git(repo, env, "add", "a.py")
    before = head(repo, env)
    result = git(repo, env, "commit", "-q", "-m", "x", check=False)
    assert result.returncode == 0, result.stderr
    assert head(repo, env) != before


def test_tracked_security_toml_gates(tmp_path, bins):
    env = make_env(bins, scanners=False)
    repo = make_repo(tmp_path / "repo", env, install=True)
    (repo / ".cta").mkdir(exist_ok=True)
    (repo / ".cta" / "security.toml").write_text("[gate]\n")
    git(repo, env, "add", ".cta/security.toml")
    git(repo, env, "commit", "-q", "--no-verify", "-m", "opt in")
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    result = git(repo, env, "commit", "-q", "-m", "x", check=False)
    assert result.returncode != 0
    assert "install semgrep, gitleaks" in result.stderr


# ---- gated: blocking ---------------------------------------------------------------------

def test_missing_scanner_blocks(tmp_path, bins):
    env = make_env(bins, scanners=False)
    repo = make_repo(tmp_path / "repo", env, gated=True, install=True)
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    before = head(repo, env)
    result = git(repo, env, "commit", "-m", "x", check=False)
    assert result.returncode != 0
    assert "install semgrep, gitleaks (brew install semgrep gitleaks)" in result.stderr
    assert head(repo, env) == before


def test_markdown_only_exempt(tmp_path, bins):
    env = make_env(bins, scanners=False)
    repo = make_repo(tmp_path / "repo", env, gated=True, install=True)
    (repo / "notes.md").write_text("hi\n")
    git(repo, env, "add", "notes.md")
    assert git(repo, env, "commit", "-q", "-m", "x", check=False).returncode == 0


def test_staged_finding_blocks_plain_commit(gated, env):
    (gated / "a.py").write_text(f"token = '{MARK} value-123'\n")
    git(gated, env, "add", "a.py")
    before = head(gated, env)
    result = git(gated, env, "commit", "-m", "x", check=False)
    assert result.returncode != 0
    assert "[high] a.py:1 r.danger - marker found" in result.stderr
    assert "value-123" not in result.stderr  # matched source text is never printed
    assert head(gated, env) == before


def test_clean_commit_passes(gated, env):
    (gated / "a.py").write_text("x = 1\n")
    git(gated, env, "add", "a.py")
    result = git(gated, env, "commit", "-q", "-m", "x", check=False)
    assert result.returncode == 0, result.stderr


def test_commit_all_scans_unstaged_tracked_file(gated, env):
    (gated / "a.py").write_text("x = 1\n")
    git(gated, env, "add", "a.py")
    (gated / "b.py").write_text(f"y = '{MARK}'\n")  # tracked, modified, not staged
    result = git(gated, env, "commit", "-am", "x", check=False)
    assert result.returncode != 0 and "b.py" in result.stderr
    assert not leaked(gated, env)
    # without -a the unstaged change is not part of the commit, so it passes
    assert git(gated, env, "commit", "-q", "-m", "x", check=False).returncode == 0
    assert not leaked(gated, env)


def test_commit_with_pathspec_scans_the_temporary_index(gated, env):
    (gated / "b.py").write_text(f"y = '{MARK}'\n")
    result = git(gated, env, "commit", "-m", "x", "--", "b.py", check=False)
    assert result.returncode != 0 and "b.py" in result.stderr
    assert not leaked(gated, env)


def test_pathspec_commit_ignores_findings_outside_the_commit(gated, env):
    # the real index holds a finding, but `commit -- README.md` commits only README.md:
    # the hook must scan git's temporary index (GIT_INDEX_FILE), not the real one
    (gated / "c.py").write_text(f"z = '{MARK}'\n")
    git(gated, env, "add", "c.py")
    (gated / "README.md").write_text("# demo 2\n")
    (gated / "x.py").write_text("x = 1\n")
    git(gated, env, "add", "x.py")
    result = git(gated, env, "commit", "-q", "-m", "x", "--", "x.py", check=False)
    assert result.returncode == 0, result.stderr
    assert not leaked(gated, env)


def test_git_add_inside_message_substitution_is_scanned(gated, env):
    (gated / "b.py").write_text(f"y = '{MARK}'\n")
    result = sh('git commit -m "$(git add b.py; echo msg)"', gated, env)
    assert result.returncode != 0 and "b.py" in result.stderr
    assert not leaked(gated, env)


def test_info_findings_listed_not_blocking(gated, env, bins):
    _exe(bins["fake"] / "semgrep", '#!/bin/sh\necho \'{"results": [{"check_id": "r.note", "path": "a.py", '
         '"start": {"line": 2}, "extra": {"severity": "INFO", "message": "fyi"}}], "errors": []}\'\n')
    (gated / "a.py").write_text("x = 1\n")
    git(gated, env, "add", "a.py")
    result = git(gated, env, "commit", "-q", "-m", "x", check=False)
    assert result.returncode == 0
    assert "[info] a.py:2 r.note - fyi" in result.stderr


def test_merge_commit_with_finding_blocked_by_pre_merge_commit(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    git(repo, env, "checkout", "-q", "-b", "other")
    (repo / "m.py").write_text(f"m = '{MARK}'\n")
    git(repo, env, "add", "m.py")
    git(repo, env, "commit", "-q", "-m", "other")
    git(repo, env, "checkout", "-q", "main")
    (repo / "n.py").write_text("n = 1\n")
    git(repo, env, "add", "n.py")
    git(repo, env, "commit", "-q", "-m", "main side")
    (repo / ".cta").mkdir()
    (repo / ".cta" / "active-build").write_text("{}\n")
    kbwork.exclude_path(repo, ".cta/active-build")
    gitgate.install_gate(repo)
    before = head(repo, env)
    result = git(repo, env, "merge", "--no-ff", "-m", "merge", "other", check=False)
    assert result.returncode != 0
    assert "m.py" in result.stderr
    assert head(repo, env) == before


def test_am_with_finding_blocked_by_pre_applypatch(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env)
    git(repo, env, "checkout", "-q", "-b", "other")
    (repo / "m.py").write_text(f"m = '{MARK}'\n")
    git(repo, env, "add", "m.py")
    git(repo, env, "commit", "-q", "-m", "other")
    patch = tmp_path / "p.patch"
    patch.write_text(git(repo, env, "format-patch", "-1", "--stdout").stdout)
    git(repo, env, "checkout", "-q", "main")
    (repo / ".cta").mkdir()
    (repo / ".cta" / "active-build").write_text("{}\n")
    kbwork.exclude_path(repo, ".cta/active-build")
    gitgate.install_gate(repo)
    before = head(repo, env)
    result = git(repo, env, "am", str(patch), check=False)
    assert result.returncode != 0
    assert "m.py" in result.stderr
    assert head(repo, env) == before


# ---- earlier bypass vectors: every one ends blocked by git itself --------------------------
# Each runs in a gated repo with a staged finding (a.py) and an unstaged one (b.py). The
# invariant: no commit on any branch contains the marker. Vectors that skip hooks entirely
# (--no-verify, a hooksPath override) are refused by gate_guard instead; that is asserted too.

VECTORS = [
    "git commit -m x", "command git commit -m x", "env git commit -m x", "env -i PATH=\"$PATH\" git commit -m x",
    "env -u FOO git commit -m x", "echo -m x | xargs git commit", "xargs git commit -m x </dev/null",
    "bash -c \"git commit -m x\"", "bash -lc \"git commit -m x\"", "bash --norc -c \"git commit -m x\"",
    "bash -o pipefail -c \"git commit -m x\"", "sh -c 'git commit -m x'", "eval \"git commit -m x\"",
    "eval git commit -m x", "git -c alias.x=commit x -m x", "git -c alias.x='!git commit' x -m x",
    "git -c alias.x='commit -q' x -m x", "git -calias.x=commit x -m x",
    "git commit-tree HEAD^{tree} -p HEAD -m x | xargs git update-ref HEAD",
    "git revert HEAD --no-edit", "git -p commit -m x", "git --no-pager -P commit -m x",
    "G=git; $G commit -m x", "git $(echo commit) -m x", "x=commit; git $x -m x", "\"git\" \"commit\" -m x",
    "time git commit -m x", "nice -n 5 git commit -m x", "timeout 60 git commit -m x",
    "nohup git commit -m x >/dev/null 2>&1 &", "exec git commit -m x",
    "for i in 1; do git commit -m x; done", "if true; then git commit -m x; fi", "{ git commit -m x; }",
    "true && { git commit -m x; }", "find . -maxdepth 0 -exec git commit -m x \\;",
    "/bin/bash -c 'git commit -m x'", "python3 -c \"import os; os.system('git commit -m x')\"",
    "git -C sub commit -m x", "cd sub/deep && git commit -m x", "git --git-dir=.git --work-tree=. commit -m x",
    "GIT_DIR=.git git commit -m x", "git commit --fixup=HEAD", "git commit -m x -uno", "git commit -v -m x",
    "git commit --amend --reset-author --no-edit", "git commit --squash HEAD -m x", "git commit -e -m x",
    "git commit -m=x", "git commit --trailer \"Co-Authored-By: a <b>\" -m x", "git add b.py\ngit commit -m x",
    "git reset --soft HEAD && git commit -m x", "git commit -m x 2>&1 | tail -5", "git commit -m x>/dev/null",
    "git commit -mx -- ", "git commit --allow-empty -m x", "git commit -m \"a\" -m \"b\"",
    "cd {repo} && git commit -m x", "cd {repo}; git commit -m x", "pushd {repo} && git commit -m x",
    "cd ../repo && git commit -m x", "git -C ../repo commit -m x",
    "git --git-dir={repo}/.git --work-tree={repo} commit -m x", "git --git-dir {repo}/.git commit -m x",
    "D={repo}; cd $D && git commit -m x", "(cd {repo} && git commit -m x)", "cd {repo}\ngit commit -m x",
    "cd {repo} && cd - && git commit -m x", "git -C {repo} -C sub commit -m x",
    "cd {repo}/sub && git -C .. commit -m x", "cd {repo} && echo hi | git commit -F -",
    "cd /tmp && cd {repo} && git commit -m x",
    "git commit -m \"$(git add b.py; echo msg)\"", "git commit -m \"`git add b.py`msg\"",
    "git commit -m \"$(git stash pop >/dev/null; echo m)\"",
    "git commit -m \"$(cat <<'EOF'\nfeat: thing\n\nRun git add first, then git commit -am is not allowed.\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nfix: handle case 1) and 2)\n\nBody.\nEOF\n)\"",
    "git commit -m 'it'\"'\"'s fine'", "git commit -m x --author \"A <a@b>\"", "git commit -qm x",
    "git commit -um x", "git commit --amend -C HEAD", "git commit -m x --date now", "git commit -s -m x",
    "git commit -m x --untracked-files=no", "git commit -F <(git add b.py; echo m)",
    "git commit -m x; git add b.py", "git commit -m \"`git add b.py`\"", "git commit --inc a.py -m x",
    "git commit --al -m x", "git commit --interactive", "git commit --pa",
    "cat <<'A'B >/dev/null\nAB\ngit add b.py && git commit -m x", "cat <<\"A\"B\nAB\ngit commit -am x",
    "cat <<\\A\\B\nAB\ngit commit -am x", "cat <<'A'\nA\ngit commit -am x",
    "echo '<<\"X\"'\ngit commit -m \"$(git add b.py; echo m)\"", "echo \"<<'X'\"\ngit commit -m \"`git add b.py`m\"",
    "cat <<'EOF'; git commit -am x\nbody\nEOF", "cat <<-'EOF'\n\tgit commit -am x\n\tEOF\ngit commit -am y",
    "bash <<<'git commit -am x'", "bash <<'EOF'\ngit commit -am x\nEOF", "echo 'git commit -am x' | bash",
    "sh -s <<'EOF'\ngit commit -am x\nEOF", "$(which git) commit -m x", "`which git` commit -m x",
    "g(){ git \"$@\"; }; g commit -am x", "echo commit -am x | xargs git",
    "D={repo}; true || D={other}; cd $D && git commit -m x",
    "pushd {other} && popd && git commit -m x", "cd {other} && cd {repo} && git commit -m x",
    "cd {other}; git -C $OLDPWD commit -m x", "git -C \"${PWD%/*}/repo\" commit -m x",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0=commit git x -m y",
    "GIT_CONFIG_PARAMETERS=\"'alias.x=commit'\" git x -m y", "git -c \"alias.x=!git c'o'mmit -am y\" x",
    "git commit -m \"$(printf 'msg <<'\"'\"'Z'\"'\"'\\n')\"\ngit add b.py",
    "git commit -am x", "git commit -a -m x", "git add . && git commit -m x",
    "git -c alias.ci='commit -a' ci -m x",
    # hook-skipping forms: git cannot block them, gate_guard refuses them
    "git commit --no-verify -m x", "git commit -n -m x", "git commit -anm x",
    "git -c core.hooksPath=/tmp/none commit -m x",
]


@pytest.fixture
def vector_repo(tmp_path, env):
    repo = make_repo(tmp_path / "w" / "repo", env, gated=True, install=True)
    make_repo(tmp_path / "w" / "other", env)
    (repo / "a.py").write_text(f"x = '{MARK}'\n")
    git(repo, env, "add", "a.py")
    (repo / "b.py").write_text(f"y = '{MARK}'\n")
    return repo


@pytest.mark.parametrize("template", VECTORS)
def test_bypass_vector_ends_blocked(template, vector_repo, env):
    import gate_guard

    command = template.replace("{repo}", str(vector_repo)).replace("{other}", str(vector_repo.parent / "other"))
    refused = gate_guard.check("Bash", {"command": command}, str(vector_repo))
    sh(command + "\nwait", vector_repo, env)
    assert refused or not leaked(vector_repo, env), command


# ---- chaining to the repo's own hooks --------------------------------------------------------

def chained_hook(directory: Path, name: str, code: int, marker: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return _exe(directory / name, f'#!/bin/sh\necho "ran $# $*" >> "{marker}"\ncat >> "{marker}"\nexit {code}\n')


def test_chains_to_git_dir_hook_and_preserves_exit_code(gated, env, tmp_path):
    marker = tmp_path / "marker"
    chained_hook(gated / ".git" / "hooks", "pre-commit", 3, marker)
    (gated / "a.py").write_text("x = 1\n")
    git(gated, env, "add", "a.py")
    before = head(gated, env)
    assert git(gated, env, "commit", "-m", "x", check=False).returncode != 0
    assert head(gated, env) == before and "ran 0" in marker.read_text()
    direct = subprocess.run([str(HOOK_DIR / "pre-commit"), "one", "two"], cwd=gated, env=env,
                            input="from-stdin\n", capture_output=True, text=True)
    assert direct.returncode == 3
    assert "ran 2 one two" in marker.read_text() and "from-stdin" in marker.read_text()


def test_chained_hook_success_lets_commit_through(gated, env, tmp_path):
    marker = tmp_path / "marker"
    chained_hook(gated / ".git" / "hooks", "pre-commit", 0, marker)
    (gated / "a.py").write_text("x = 1\n")
    git(gated, env, "add", "a.py")
    assert git(gated, env, "commit", "-q", "-m", "x", check=False).returncode == 0
    assert marker.exists()


def test_chained_hook_not_run_when_gate_blocks(gated, env, tmp_path):
    marker = tmp_path / "marker"
    chained_hook(gated / ".git" / "hooks", "pre-commit", 0, marker)
    (gated / "a.py").write_text(f"x = '{MARK}'\n")
    git(gated, env, "add", "a.py")
    assert git(gated, env, "commit", "-m", "x", check=False).returncode != 0
    assert not marker.exists()


def test_chains_to_previous_hooks_path(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env, gated=True)
    marker = tmp_path / "marker"
    chained_hook(repo / "myhooks", "pre-commit", 0, marker)
    git(repo, env, "config", "core.hooksPath", "myhooks")
    gitgate.install_gate(repo)
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    assert git(repo, env, "commit", "-q", "-m", "x", check=False).returncode == 0
    assert marker.exists()
    gitgate.uninstall_gate(repo)
    assert hooks_path(repo, env) == "myhooks"


def test_non_executable_chained_hook_is_skipped(gated, env, tmp_path):
    marker = tmp_path / "marker"
    hook = chained_hook(gated / ".git" / "hooks", "pre-commit", 5, marker)
    hook.chmod(0o644)
    (gated / "a.py").write_text("x = 1\n")
    git(gated, env, "add", "a.py")
    assert git(gated, env, "commit", "-q", "-m", "x", check=False).returncode == 0


def test_not_gated_still_chains(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env, install=True)
    marker = tmp_path / "marker"
    chained_hook(repo / ".git" / "hooks", "pre-commit", 4, marker)
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    assert git(repo, env, "commit", "-m", "x", check=False).returncode != 0
    assert marker.exists()


# ---- check(): fail closed, deadline ---------------------------------------------------------

@pytest.fixture
def staged(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env, gated=True)
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    return repo


ALL = lambda n: f"/bin/{n}"  # noqa: E731


def test_check_internal_error_fails_closed(staged):
    def boom(_top, _index):
        raise RuntimeError("secret detail")

    code, text = gitgate.check(staged, None, boom, ALL)
    assert code == 1 and "commit gate error: RuntimeError" in text
    assert "secret detail" not in text


def test_check_scan_error_names_tool(staged):
    from scan import ScanError

    def boom(_top, _index):
        raise ScanError("semgrep", "x")

    code, text = gitgate.check(staged, None, boom, ALL)
    assert code == 1 and "ScanError (semgrep)" in text


def test_check_deadline_exceeded_fails_closed(staged):
    def slow(_top, _index):
        exc = subprocess.TimeoutExpired(["semgrep"], 1)
        exc.tool = "semgrep"
        raise exc

    code, text = gitgate.check(staged, None, slow, ALL)
    assert code == 1 and "TimeoutExpired (semgrep)" in text


def test_check_default_scan_uses_deadline_and_index(staged, monkeypatch):
    import scan

    seen = {}

    def fake(repo, staged=True, run=None, timeout=None, index_file=None):
        seen.update(repo=repo, timeout=timeout, index_file=index_file)
        return []

    monkeypatch.setattr(scan, "fast_scan", fake)
    index = str(staged / ".git" / "index")
    assert gitgate.check(staged, index, which_fn=ALL) == (0, "")
    assert seen["timeout"] == gitgate.GATE_DEADLINE and seen["index_file"] == index
    assert 30 <= gitgate.GATE_DEADLINE <= 300


def test_check_findings_capped_at_ten(staged):
    found = [Finding.create("semgrep", f"r.{i}", "a.py", i, "medium", "m") for i in range(14)]
    code, text = gitgate.check(staged, None, lambda t, i: found, ALL)
    assert code == 1 and text.count("[medium]") == 10 and "and 4 more" in text


def test_check_low_blocks_info_does_not(staged):
    low = [Finding.create("semgrep", "r", "a.py", 1, "low", "m")]
    info = [Finding.create("semgrep", "r", "a.py", 1, "info", "m")]
    assert gitgate.check(staged, None, lambda t, i: low, ALL)[0] == 1
    code, text = gitgate.check(staged, None, lambda t, i: info, ALL)
    assert code == 0 and "[info]" in text


def test_check_manifest_requires_osv_scanner(tmp_path, env):
    repo = make_repo(tmp_path / "repo", env, gated=True)
    (repo / "package-lock.json").write_text("{}\n")
    git(repo, env, "add", "package-lock.json")
    code, text = gitgate.check(repo, None, lambda t, i: [], lambda n: None if n == "osv-scanner" else "/x")
    assert code == 1 and "install osv-scanner" in text


# ---- scan.fast_scan honours an explicit index file --------------------------------------------

def test_fast_scan_reads_the_given_index(tmp_path, env):
    import scan

    repo = make_repo(tmp_path / "repo", env)
    temp_index = tmp_path / "temp-index"
    tenv = {**env, "GIT_INDEX_FILE": str(temp_index)}
    git(repo, tenv, "read-tree", "HEAD")
    (repo / "only-in-temp.py").write_text("t = 1\n")
    git(repo, tenv, "add", "only-in-temp.py")
    seen = []

    def run_(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        seen.append(argv)
        if argv[0] == "semgrep":
            return subprocess.CompletedProcess(argv, 0, '{"results": [], "errors": []}', "")
        report = argv[argv.index("--report-path") + 1]
        Path(report).write_text("[]")
        return subprocess.CompletedProcess(argv, 0, "", "")

    assert scan.fast_scan(repo, run=run_) == []  # real index: nothing staged
    assert seen == []
    assert scan.fast_scan(repo, run=run_, index_file=str(temp_index)) == []
    assert any("only-in-temp.py" in a for a in seen[0])


def test_fast_scan_passes_deadline_and_tags_tool(tmp_path, env):
    import scan

    repo = make_repo(tmp_path / "repo", env)
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    seen = {}

    def run_(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        seen["argv"], seen["timeout"] = argv, kw.get("timeout")
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    with pytest.raises(subprocess.TimeoutExpired) as info:
        scan.fast_scan(repo, run=run_, timeout=50)
    assert info.value.tool == "semgrep"
    assert 0 < seen["timeout"] <= 50
    assert "--timeout" in seen["argv"]


def test_fast_scan_without_timeout_adds_none(tmp_path, env):
    import scan

    repo = make_repo(tmp_path / "repo", env)
    (repo / "a.py").write_text("x = 1\n")
    git(repo, env, "add", "a.py")
    seen = []

    def run_(argv, **kw):
        if argv[0] == "git":
            return subprocess.run(argv, **kw)
        seen.append(kw)
        raise subprocess.CalledProcessError(2, argv)

    with pytest.raises(subprocess.CalledProcessError):
        scan.fast_scan(repo, run=run_)
    assert "timeout" not in seen[0]
