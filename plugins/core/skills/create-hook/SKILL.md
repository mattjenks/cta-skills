---
name: create-hook
description: Use when asked to create a hook, add a guardrail or guarantee ("never let the assistant edit X", "don't stop until tests pass", "log every command", "notify me when done"), automate something on a Claude Code lifecycle event, or debug a hook that never blocks, always blocks, or whose output is ignored.
argument-hint: "[what the hook should guarantee or do]"
---

<!-- Adapted from coleam00/skills .claude/skills/hooks-create/SKILL.md and hooks/README.md (MIT) -->

# Create Hook

Turn a plain-English guarantee into a working Claude Code hook inside a CTA plugin, with block and allow tests.
A rule asks the assistant to behave; a hook guarantees it, because the harness runs it whether or not the model
remembers. Use a hook when ignoring the rule would cause a leaked secret, a broken deploy or an incident. Use a
rule or skill when ignoring it is a minor annoyance.

What the hook should do: `$ARGUMENTS`. If filled in, treat it as the spec and ask only about the gaps. If blank,
ask what the hook should guarantee.

## House rules (all mandatory)

1. **Placement.** The hook script goes in a CTA plugin at `plugins/<plugin>/hooks/<name>.py` and is wired in that
   plugin's `hooks/hooks.json`. Never in `~/.claude/settings.json` or a project's `.claude/settings.json`.
2. **The house pattern.** A standalone Python script with the shebang `#!/usr/bin/env -S uv run --script`, an
   inline metadata block with `requires-python = ">=3.12"`, the standard library only, and the file marked
   executable. See the skeleton below.
3. **Exit codes.** Exit 0 to allow, exit 2 to block with the reason on stderr. Never exit 1 to block. Any
   unexpected exception exits 0 (fail open): a bug in a hook must not brick a session. The only deliberate
   non-zero exit is the block.
4. **Wiring.** The command is `uv run --script "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py"`, never a bare
   `python`. Scope the `matcher` to the tools the guarantee needs, not every call.
5. **Tests through a subprocess.** Every hook ships block and allow tests that execute the real script in a
   subprocess and assert the exit code, in `plugins/<plugin>/tests/test_<name>.py`. Reading the code is not
   proof. See "Tests".
6. **Version bump and changelog.** In the same commit, bump the plugin version in BOTH
   `plugins/<plugin>/.claude-plugin/plugin.json` and its `.claude-plugin/marketplace.json` entry, and add a
   `## <version> — <summary>` heading with a line for the hook to `CHANGELOG.md`.
7. **No personal data.** No emails, home-directory paths or private names in the script, the wiring or the
   tests. Use neutral names such as "Ada". Personal values come from `~/.config/cta/config.toml` through the
   plugin's `cta_config.py` helper, never from the repository.

## Pick the event

The behavior maps to one event. Choose by when it fires and whether it must stop something.

| The user wants to | Event | Can it block? |
|---|---|---|
| Stop the assistant doing something (read a secret, edit a protected path, run a destructive command) | PreToolUse | Yes, before the tool runs |
| React after an action (format an edited file, log a command) | PostToolUse | No, the tool already ran |
| Make "done" depend on a check (tests green, lint clean) | Stop, SubagentStop | Yes, sends the assistant back to work |
| Gate or scan the user's prompt | UserPromptSubmit | Yes, and can inject context |
| Load context at session start | SessionStart | No, injects context only |
| Be notified when the assistant needs input or finishes | Notification, Stop | No, side effect only |
| Snapshot state before compaction | PreCompact | Yes, but rarely wanted |

Pre is a gate; post is a log. "Make sure X never happens" needs a blocking event; "do Z when W happens" does not.
The event list and field names evolve, so before writing, fetch the current hooks reference
(`https://code.claude.com/docs/en/hooks`) and confirm the event name, its stdin fields and its control protocol.
If the fetch fails, proceed from the table and say so in the report.

## Protocol

- **Input:** JSON on stdin with `session_id`, `cwd`, `hook_event_name`, plus event fields such as `tool_name` and
  `tool_input` (tool events), `prompt` (UserPromptSubmit) or `source` (SessionStart).
- **Allow:** exit 0. On SessionStart and UserPromptSubmit, stdout is added to the assistant's context.
- **Block:** exit 2, reason on stderr; the assistant reads the reason and adapts. Only blocking events honor it.
- **Any other code:** a non-blocking error; execution continues.
- **JSON output** (to modify input or inject context) goes on stdout, and `additionalContext` is nested inside
  `hookSpecificOutput`; see pitfall 3.

## Workflow

1. **Pin the behavior.** Establish what to prevent or do, when, and the exact paths, commands or patterns to
   match. The guarantee is only as good as the match, so get concrete values; propose an interpretation and confirm
   if the ask is vague.
2. **Read the current docs** (above) and choose the event and matcher.
3. **Write the failing tests first** (see "Tests"), run them and see them fail, because the script does not exist.
4. **Write the script** from the skeleton, then run the tests until they pass.
5. **Wire it** into `plugins/<plugin>/hooks/hooks.json`, merging with existing events and hooks; never clobber
   them. If a hook already exists for that event, extend it. Extend the wiring test in `tests/test_manifests.py`
   if it enumerates events.
6. **Bump the version and changelog** (house rule 6) and run the full suite:
   `uv run --with pytest pytest tests plugins -q`.
7. **Report** what the hook guarantees, the one line to change to adjust it, how to see it work in a live session
   (an action that should be refused), and what you verified. Always add the security note: a hook runs arbitrary
   code automatically with the user's credentials on every matching event, so review it as CI config.

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

## The six pitfalls

1. **The venv trap.** A hook runs under `uv run` in a throwaway environment with none of the project's packages,
   and it is not the user's shell, so the project's `.venv` is not on `PATH`. Never rebuild a project command with
   `sys.executable` or a bare `["python", "-m", ...]` list. Run the user's command verbatim as a shell string in
   the project directory (`cwd` from the payload), with uv's ephemeral venv removed from `PATH` and `VIRTUAL_ENV`,
   and the project's own `.venv` (or `venv`) `bin` directory put first. Keep the command in one named constant at
   the top of the file. If it must run in a subdirectory, pass `cwd=Path(data["cwd"]) / "subdir"`. Getting this
   wrong yields a hook that blocks on green exactly as it does on red.
2. **`@file` mentions bypass PreToolUse.** A file the user attaches with `@path` arrives without a tool call, so
   no PreToolUse hook fires. A guard covers what the assistant reaches for, not what the user hands it.
3. **`additionalContext` must be nested.** It goes inside `hookSpecificOutput`
   (`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`), never at the top
   level, where Claude Code silently ignores it, with no error.
4. **Exit 1 does not block; exit 2 does.** Exit 1 is a non-blocking error: logged, and the assistant carries on.
   Only exit 2 blocks, and only on events that can block. A hook that exits 1 on a violation protects nothing and
   says nothing.
5. **A `Stop` hook without a loop guard spins.** It blocks the stop, the assistant works, tries to stop and is
   blocked again. Claude Code overrides after eight consecutive blocks, so it is a bounded spin, but it burns eight
   turns. Read `stop_hook_active` and stand down when true.
6. **Hooks run in a non-interactive shell.** No `~/.zshrc` or `~/.bashrc`, so a tool on `PATH` only through the
   profile works by hand and fails in the hook. Anything the profile prints at startup mixes into stdout and breaks
   JSON parsing. Use absolute paths or `PATH` set in the script.

Debug with `claude --debug` (hook execution) and `CLAUDE_CODE_DEBUG_LOG_LEVEL=verbose` (matcher counts, which
answers "did my matcher match").

## Coverage and limits

The harness guarantees the hook runs; what it catches is only as good as the check. State the gaps to the user
(a path matcher will not catch a path built at runtime; the two-step route of writing a script and then running it
needs content inspection of Write and Edit calls). Keep hooks fast, since they run on every matching event; heavy
work belongs in a skill. Command hooks are the default. Prompt, agent, HTTP and MCP-tool handler types exist for
judgments a regex cannot make; reach for them only with a reason, and confirm syntax in the current docs.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/hooks/secrets_guard.py`: the house blocking hook, the model for structure and fail-open handling.
- `tests/test_secrets_guard.py` in the plugin: the model for policy rows plus the subprocess exit-code test.
- `${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json`: the wiring format and `uv run --script` command form.
