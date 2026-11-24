import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
FORBIDDEN = ["@gmail.com", "personal-kb", "mobile documents", "jax"]


def _marketplace():
    return json.loads(MARKETPLACE.read_text())


def test_marketplace_lists_every_plugin_dir():
    plugins = _marketplace()["plugins"]
    sources = {(ROOT / p["source"]).resolve() for p in plugins}
    for p in plugins:
        assert (ROOT / p["source"]).is_dir(), p["source"]
    dirs = {d.resolve() for d in (ROOT / "plugins").glob("*/") if d.is_dir()}
    assert dirs <= sources, f"plugin dirs missing from marketplace: {dirs - sources}"


def test_plugin_versions_match():
    for entry in _marketplace()["plugins"]:
        plugin_dir = ROOT / entry["source"]
        manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
        assert manifest["version"] == entry["version"]
        changelog = (plugin_dir / "CHANGELOG.md").read_text()
        assert _has_changelog_heading(changelog, entry["version"]), entry["version"]


def _has_changelog_heading(changelog: str, version: str) -> bool:
    """`## 0.4.0 — summary` (hand-written) or `## [0.6.0](url) (date)` (release-please)."""
    v = re.escape(version)
    return bool(re.search(rf"^## (?:\[{v}\]|{v}(?![\w.]))", changelog, re.M))


def test_changelog_heading_shapes():
    assert _has_changelog_heading("## 0.4.0 — notify\n", "0.4.0")
    assert _has_changelog_heading(
        "# Changelog\n\n## [0.6.0](https://github.com/o/r/compare/core-v0.5.0...core-v0.6.0)"
        " (2026-12-01)\n", "0.6.0")
    assert not _has_changelog_heading("## 0.4.10 — later\n", "0.4.1")
    assert not _has_changelog_heading("## [0.4.10](u) (2026-12-01)\n", "0.4.1")


def test_plugin_names_match():
    for entry in _marketplace()["plugins"]:
        plugin_dir = ROOT / entry["source"]
        manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
        assert manifest["name"] == entry["name"], (manifest["name"], entry["name"])
        assert plugin_dir.name == entry["name"], (plugin_dir.name, entry["name"])
        assert not entry["name"].startswith("cta-"), entry["name"]


def _candidate_files():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    for rel in out:
        parts = Path(rel).parts
        name = parts[-1]
        if rel == "NOTICE" or "tests" in parts[:-1]:
            continue
        if name.startswith(("test_", "_test_")):
            continue
        path = ROOT / rel
        if path.is_file():
            yield rel, path


def test_no_personal_data():
    hits = []
    for rel, path in _candidate_files():
        try:
            text = path.read_text().lower()
        except UnicodeDecodeError:
            continue
        hits += [f"{rel}: {term}" for term in FORBIDDEN if term in text]
    assert not hits, hits


PLUGIN_DIR = ROOT / "plugins" / "core"
HOOKS_JSON = PLUGIN_DIR / "hooks" / "hooks.json"


def _hook_entries():
    data = json.loads(HOOKS_JSON.read_text())
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                yield event, group, hook


def _script_path(command):
    match = re.search(r'"\$\{CLAUDE_PLUGIN_ROOT\}/([^"]+)"', command)
    assert match, command
    return PLUGIN_DIR / match.group(1)


def test_hooks_json_commands_exist():
    entries = list(_hook_entries())
    assert {e for e, _, _ in entries} == {
        "SessionStart", "PreToolUse", "UserPromptSubmit", "Stop", "Notification"
    }
    for _, _, hook in entries:
        path = _script_path(hook["command"])
        assert path.is_file(), path
        assert os.access(path, os.X_OK), f"not executable: {path}"


def test_no_bare_python_in_hooks():
    for _, _, hook in _hook_entries():
        assert not hook["command"].startswith("python"), hook["command"]
        assert hook["command"].startswith("uv run --script "), hook["command"]


def _run_wired_guard(tool_name, tool_input):
    command = next(
        h["command"] for e, _, h in _hook_entries() if e == "PreToolUse"
    ).replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_DIR))
    return subprocess.run(
        command, shell=True, capture_output=True, text=True,
        input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
    )


def test_wired_turn_start_is_silent_and_records(tmp_path):
    command = next(
        h["command"] for e, _, h in _hook_entries() if e == "UserPromptSubmit"
    ).replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_DIR))
    assert command.endswith('hooks/turn_start.py"')
    state = tmp_path / "state"
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        input=json.dumps({"session_id": "wired-1"}),
        env={**os.environ, "CTA_STATE_DIR": str(state)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert (state / "turns" / "wired-1").is_file()


def test_wired_secrets_guard_blocks():
    blocked = _run_wired_guard("Read", {"file_path": str(ROOT / ".env")})
    assert blocked.returncode == 2, blocked.stderr
    allowed = _run_wired_guard("Read", {"file_path": str(ROOT / "README.md")})
    assert allowed.returncode == 0, allowed.stderr


SKILLS_DIR = PLUGIN_DIR / "skills"
AUTHORING_SKILLS = {"create-skill", "create-hook", "config-audit"}


def _frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "missing YAML frontmatter"
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def test_skill_frontmatter():
    skills = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    assert AUTHORING_SKILLS <= {p.parent.name for p in skills}
    for path in skills:
        text = path.read_text()
        fields = _frontmatter(text)
        assert fields.get("name") == path.parent.name, path
        description = fields.get("description", "")
        assert 0 < len(description) <= 1024, (path, len(description))
        assert len(text.splitlines()) <= 500, (path, len(text.splitlines()))


BUILD_DIR = ROOT / "plugins" / "build"
BUILD_HOOKS_JSON = BUILD_DIR / "hooks" / "hooks.json"


def _build_hook_entries():
    data = json.loads(BUILD_HOOKS_JSON.read_text())
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                yield event, group, hook


def _build_command(script):
    return next(
        h["command"] for _, _, h in _build_hook_entries() if h["command"].endswith(f'hooks/{script}"')
    ).replace("${CLAUDE_PLUGIN_ROOT}", str(BUILD_DIR))


def test_build_hooks_json_commands_exist_and_run_through_uv():
    entries = list(_build_hook_entries())
    assert {e for e, _, _ in entries} == {"PreToolUse"}
    assert {Path(h["command"]).name.rstrip('"') for _, _, h in entries} == {"gate_guard.py"}
    for _, _, hook in entries:
        assert hook["command"].startswith("uv run --script "), hook["command"]
        match = re.search(r'"\$\{CLAUDE_PLUGIN_ROOT\}/([^"]+)"', hook["command"])
        assert match, hook["command"]
        path = BUILD_DIR / match.group(1)
        assert path.is_file(), path
        assert os.access(path, os.X_OK), f"not executable: {path}"


def test_build_hook_matchers_and_timeouts():
    by_script = {Path(h["command"]).name.rstrip('"'): (g["matcher"], h["timeout"])
                 for _, g, h in _build_hook_entries()}
    assert by_script["gate_guard.py"] == ("Bash|Write|Edit|MultiEdit", 15)
    assert "finding_guard.py" not in by_script


def test_wired_gate_guard_refuses_hook_bypass_in_gated_repo(tmp_path):
    command = _build_command("gate_guard.py")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def run(cmd, cwd):
        return subprocess.run(
            command, shell=True, capture_output=True, text=True, env=env,
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}),
        )

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, env=env)
    assert run("git commit --no-verify -m x", repo).returncode == 0  # not gated
    (repo / ".cta").mkdir()
    (repo / ".cta" / "active-build").write_text("{}")
    blocked = run("git commit --no-verify -m x", repo)
    assert blocked.returncode == 2, blocked.stderr
    assert "--no-verify" in blocked.stderr
    assert run("git commit -m x", repo).returncode == 0


def test_build_git_hooks_are_executable_uv_scripts():
    for name in ("pre-commit", "pre-merge-commit", "pre-applypatch"):
        path = BUILD_DIR / "hooks" / "git" / name
        assert path.is_file() and os.access(path, os.X_OK), path
        assert path.read_text().startswith("#!/usr/bin/env -S uv run --script\n"), path
