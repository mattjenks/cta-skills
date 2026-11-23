"""gate_guard: the thin PreToolUse guard that protects the git-hook commit gate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import gate_guard
from gate_guard import check

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "gate_guard.py"
HOOK_DIR = Path(__file__).resolve().parent.parent / "hooks" / "git"
ENV = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def make_repo(path: Path, gated: bool) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=ENV)
    if gated:
        (path / ".cta").mkdir()
        (path / ".cta" / "active-build").write_text("{}\n")
    return path


@pytest.fixture
def gated(tmp_path):
    return make_repo(tmp_path / "repo", True)


@pytest.fixture
def plain(tmp_path):
    return make_repo(tmp_path / "plain", False)


def bash(command, cwd):
    return check("Bash", {"command": command}, str(cwd))


REFUSED = [
    "git commit --no-verify -m x", "git commit -m x --no-verify", "git commit --no-veri -m x",
    "git push --no-verify",  # false positive by design: the text is refused wherever it appears
    "git commit -n -m x", "git commit -nm x", "git commit -anm x", "git commit -a -n -m x",
    "git commit -qn -m x", "git -C . commit -n -m x",
    "git -c core.hooksPath=/tmp/none commit -m x", "git config core.hooksPath /tmp/none",
    "git config --unset core.hookspath", "git config --local --unset-all core.HooksPath",
    "GIT_CONFIG_GLOBAL=/tmp/g git commit -m x", "GIT_CONFIG_PARAMETERS=\"'a.b=c'\" git commit -m x",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.x GIT_CONFIG_VALUE_0=y git commit -m x",
    "export GIT_CONFIG_SYSTEM=/tmp/s", "git -c core.fsmonitor=x status", "git -ccore.x=y commit -m x",
    "git --config-env=core.x=V commit -m x", "git -c include.path=/tmp/a.cfg commit -m x",
    "rm .cta/gate.json", "echo '{}' > .cta/gate.json", "sed -i 's/a/b/' .cta/gate.json",
    "mv .cta/gate.json /tmp/g", "cp /tmp/g .cta/gate.json", "echo x | tee .cta/gate.json",
    "chmod -x " + str(HOOK_DIR / "pre-commit"), "rm -rf " + str(HOOK_DIR),
    "echo exit 0 > plugins/build/hooks/git/pre-commit",
    "rm .cta/active-build", "mv .cta/active-build /tmp/x", "unlink .cta/active-build",
    "rm -f ./.cta/active-build", "ls .git/hooks", "cp x .git/hooks/pre-commit",
    "sed -i '/hooks/d' .git/config", "echo > .git/config",
    "bash -c \"git commit --no-verify -m x\"", "git com\"mit\" -n -m x", "git commit -m \"$(echo x)\" -n",
    "git -c alias.x='commit -n' x -m y", "git -c alias.x='!git commit --no-verify' x",
    "git config --remove-section core", "git config --rename-section core old",
    "git config include.path /tmp/a.cfg", "git config --add includeIf.gitdir:/x/.path /tmp/a.cfg",
    "echo x >> .git/config.worktree", "rm -r .git/cta", "echo '{}' > .git/cta/gate.json",
]


@pytest.mark.parametrize("command", REFUSED)
def test_refused_in_gated_repo(command, gated):
    assert bash(command, gated), command


@pytest.mark.parametrize("command", REFUSED)
def test_allowed_outside_gated_repo(command, plain):
    assert bash(command, plain) is None, command


ALLOWED = [
    "git commit -m x", "git commit -am x", "git commit -m 'fix: n things'", "git commit -m x -uno",
    "git commit -m x -S", "git commit -mnote", "git log -n 5", "git status", "cat .cta/gate.json",
    "cat .cta/active-build", "git -c user.name=Ada commit -m x", "ls .cta", "git add . && git commit -m x",
    "git config user.name Ada", "echo hi > notes.txt", "git commit -m \"$(cat <<'EOF'\nfeat: x\nEOF\n)\"",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_normal_commands_allowed_in_gated_repo(command, gated):
    assert bash(command, gated) is None, command


def test_literal_cd_or_dash_c_target_decides_gating(gated, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert bash(f"cd {gated} && git commit -n -m x", elsewhere)
    assert bash(f"git -C {gated} commit --no-verify -m x", elsewhere)
    assert bash(f"cd {gated}/.cta && rm active-build", elsewhere)
    assert bash("git commit --no-verify -m x", elsewhere) is None


def test_tracked_security_toml_gates(plain):
    (plain / ".cta").mkdir()
    (plain / ".cta" / "security.toml").write_text("[gate]\n")
    subprocess.run(["git", "-C", str(plain), "add", ".cta/security.toml"], check=True, env=ENV)
    assert bash("git commit --no-verify -m x", plain)


def test_message_names_the_reason(gated):
    assert "--no-verify" in bash("git commit --no-verify -m x", gated)
    assert "hooksPath" in bash("git config core.hooksPath x", gated)


# ---- Write / Edit / MultiEdit -------------------------------------------------------

@pytest.mark.parametrize("tool,extra", [
    ("Write", {"content": "{}"}), ("Edit", {"old_string": "a", "new_string": "b"}),
    ("MultiEdit", {"edits": [{"old_string": "a", "new_string": "b"}]}),
])
def test_file_tools_refused_on_gate_files(tool, extra, plain, gated):
    for repo in (plain, gated):
        assert check(tool, {"file_path": str(repo / ".cta" / "gate.json"), **extra}, str(repo))
        assert check(tool, {"file_path": ".cta/gate.json", **extra}, str(repo))
    assert check(tool, {"file_path": str(HOOK_DIR / "pre-commit"), **extra}, str(plain))
    assert check(tool, {"file_path": str(gated / ".git" / "config"), **extra}, str(gated))
    assert check(tool, {"file_path": str(gated / ".git" / "config.worktree"), **extra}, str(gated))
    assert check(tool, {"file_path": str(plain / ".git" / "cta" / "gate.json"), **extra}, str(plain))
    assert check(tool, {"file_path": str(gated / "a.py"), **extra}, str(gated)) is None


def test_symlink_into_hook_dir_is_refused(tmp_path):
    link = tmp_path / "h"
    link.symlink_to(HOOK_DIR)
    assert check("Write", {"file_path": str(link / "pre-commit"), "content": ""}, str(tmp_path))


def test_garbage_input_allows(gated):
    assert check("Bash", None, str(gated)) is None
    assert check("Bash", {"command": 5}, str(gated)) is None
    assert check("Read", {"file_path": ".cta/gate.json"}, str(gated)) is None
    assert check("Write", {"file_path": 5}, str(gated)) is None


def test_hook_process_exit_codes(gated):
    def run(payload):
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=ENV)

    blocked = run({"tool_name": "Bash", "tool_input": {"command": "git commit -n -m x"}, "cwd": str(gated)})
    assert blocked.returncode == 2 and "gate guard" in blocked.stderr
    allowed = run({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(gated)})
    assert allowed.returncode == 0, allowed.stderr
    bad = subprocess.run([sys.executable, str(HOOK)], input="nope", capture_output=True, text=True)
    assert bad.returncode == 0


def test_gating_error_on_a_trigger_fails_closed(gated, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(gate_guard, "_gated_dirs", boom)
    assert bash("git commit --no-verify -m x", gated)
    assert bash("git commit -m x", gated) is None
