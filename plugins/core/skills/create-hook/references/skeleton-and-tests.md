# Hook skeleton and tests

<!-- Adapted from coleam00/skills .claude/skills/hooks-create/SKILL.md and hooks/README.md (MIT) -->

## Skeleton

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse guard: block edits under a protected directory."""

import json
import sys

PROTECTED = "db/migrations/"   # the one line the user will edit


def check(tool_name: str, tool_input: dict) -> str | None:
    """Return a block reason, or None to allow."""
    path = tool_input.get("file_path", "")
    if tool_name in ("Edit", "Write", "MultiEdit") and PROTECTED in path:
        return f"{PROTECTED} is protected; write a new migration instead."
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
        reason = check(data.get("tool_name", ""), data.get("tool_input") or {})
    except Exception:
        sys.exit(0)  # fail open
    if reason:
        print(reason, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

Keep `check` a pure function so tests can table-drive the policy and the subprocess test covers the exit codes.
For a `Stop` or `SubagentStop` hook, read `stop_hook_active` first and exit 0 when it is true, or the hook blocks,
the assistant works, and it is blocked again.

## Tests

Two layers, both required. Follow `plugins/core/tests/test_secrets_guard.py`.

1. **Policy rows:** import `check` (the plugin's `tests/conftest.py` puts `hooks/` on `sys.path`) and
   parametrize over `(tool, tool_input, blocked)` rows that include near-misses that must be allowed
   (an example template next to the real secret, a similarly named path).
2. **Exit codes through a subprocess:** run the real script and assert the contract end to end.

```python
SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "protect_migrations.py"


def _run(stdin_text):
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin_text,
                          capture_output=True, text=True)


def test_main_exit_codes():
    block = _run(json.dumps({"tool_name": "Edit",
                             "tool_input": {"file_path": "db/migrations/001.sql"}}))
    assert block.returncode == 2 and block.stderr.strip()
    allow = _run(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}))
    assert allow.returncode == 0
    assert _run("not json {").returncode == 0      # fail open
    assert _run("").returncode == 0
```

A blocking hook needs at least one block and one allow case. A hook that runs a project command (tests, lint)
needs both directions with the command green and red; if it exits 2 in both, the command is not resolving (see
pitfall 1). Also test the wiring: run the command from `hooks.json` with `${CLAUDE_PLUGIN_ROOT}` substituted, as
`tests/test_manifests.py` does for the secrets guard.
