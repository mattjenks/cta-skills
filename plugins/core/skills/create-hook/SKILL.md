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
   executable. See `references/skeleton-and-tests.md`.
3. **Exit codes.** Exit 0 to allow, exit 2 to block with the reason on stderr. Never exit 1 to block. Any
   unexpected exception exits 0 (fail open): a bug in a hook must not brick a session. The only deliberate
   non-zero exit is the block.
4. **Wiring.** The command is `uv run --script "${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py"`, never a bare
   `python`. Write the literal text `${CLAUDE_PLUGIN_ROOT}` in `hooks.json`; the harness expands it, so never
   substitute a path. Scope the `matcher` to the tools the guarantee needs, not every call.
5. **Tests through a subprocess.** Every hook ships block and allow tests that execute the real script in a
   subprocess and assert the exit code, in `plugins/<plugin>/tests/test_<name>.py`. Reading the code is not
   proof. See `references/skeleton-and-tests.md`.
6. **Versions and changelog.** Use a conventional commit (`feat(core): ...`). release-please owns the plugin
   version in both manifests and writes the `CHANGELOG.md`; never hand-edit them.
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
  `hookSpecificOutput`; see pitfall 3 in `references/pitfalls.md`.

## Workflow

1. **Pin the behavior.** Establish what to prevent or do, when, and the exact paths, commands or patterns to
   match. The guarantee is only as good as the match, so get concrete values; propose an interpretation and confirm
   if the ask is vague.
2. **Read the current docs** (above) and choose the event and matcher.
3. **Write the failing tests first** (see `references/skeleton-and-tests.md`), run them and see them fail, because the script does not exist.
4. **Write the script** from the skeleton, then run the tests until they pass. Read `references/pitfalls.md`
   first: the venv trap and the `Stop` loop guard bite at this step.
5. **Wire it** into `plugins/<plugin>/hooks/hooks.json`, merging with existing events and hooks; never clobber
   them. If a hook already exists for that event, extend it. Extend the wiring test in `tests/test_manifests.py`
   if it enumerates events.
6. **Commit and test.** Use a conventional commit (house rule 6; never hand-edit versions) and run the full suite:
   `uv run --with pytest pytest tests plugins -q`.
7. **Report** what the hook guarantees, the one line to change to adjust it, how to see it work in a live session
   (an action that should be refused), and what you verified. Always add the security note: a hook runs arbitrary
   code automatically with the user's credentials on every matching event, so review it as CI config.

## Skeleton and tests

Before writing the script or its tests, read `references/skeleton-and-tests.md`. It holds the
standard hook script (a pure `check` function, fail-open `main`), the `Stop` loop guard, the two required test
layers (policy rows plus a subprocess exit-code test) and the wiring test. Every hook needs both layers.

## Pitfalls, debugging and limits

Before writing the script (workflow step 4), read `references/pitfalls.md`: the six pitfalls (the venv trap, `@file` mentions bypassing
PreToolUse, nested `additionalContext`, exit 1 versus exit 2, a `Stop` hook without a loop guard, the
non-interactive shell), how to debug with `claude --debug`, and the coverage limits to state in the report.
Read it at once if a hook never blocks, always blocks or has its output ignored.

## Resources

- `references/skeleton-and-tests.md`: the script skeleton, `Stop` loop guard and both test layers. Read before writing the script.
- `references/pitfalls.md`: the six pitfalls, debugging flags and coverage limits. Read before writing the script, or when a hook misbehaves.
- `${CLAUDE_PLUGIN_ROOT}/hooks/secrets_guard.py`: the house blocking hook, the model for structure and fail-open handling.
- `tests/test_secrets_guard.py` in the plugin: the model for policy rows plus the subprocess exit-code test.
- `${CLAUDE_PLUGIN_ROOT}/hooks/hooks.json`: the wiring format and `uv run --script` command form.
