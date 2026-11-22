# The six pitfalls, debugging, coverage

<!-- Adapted from coleam00/skills .claude/skills/hooks-create/SKILL.md and hooks/README.md (MIT) -->

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
