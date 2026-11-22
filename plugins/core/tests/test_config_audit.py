import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "config-audit" / "scripts" / "_test_agent_config_audit.py"
)


def test_config_audit_self_tests_pass():
    result = subprocess.run(
        ["uv", "run", "--python", "3.12", "python", str(SCRIPT)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "OK" in result.stdout


def test_skill_md_invocations_are_runnable():
    text = (SCRIPT.parent.parent / "SKILL.md").read_text()
    assert "<skill>" not in text
    for line in text.splitlines():
        stripped = line.strip()
        assert not stripped.startswith(("python ", "python3 ")), line
        if "agent_config_audit.py" in stripped and not stripped.startswith(("-", "`", "<!--")):
            assert stripped.startswith("uv run --python 3.12 python "), line
            assert "${CLAUDE_PLUGIN_ROOT}" in stripped, line
