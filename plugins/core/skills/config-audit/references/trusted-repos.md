# Trusted repos: read the history

<!-- Adapted from coleam00/skills .claude/skills/agent-config-audit (MIT) -->

A repo the user already opens daily is where a malicious change lands unnoticed. Trust
is remembered per folder: tested on Claude Code 2.1.330 (2026-11-21), a hook committed
to an already-trusted repo ran on the next launch with no new prompt. Show what changed
in the agent config and who changed it:

```bash
git log -p -- .claude .mcp.json .codex .cursor .vscode .gemini AGENTS.md CLAUDE.md
git diff HEAD@{1} -- .claude .mcp.json .codex .cursor .vscode AGENTS.md CLAUDE.md   # since the last pull
git ls-files | grep settings.local.json   # should print nothing
```

The classic sign is a config change inside a commit whose message is about something
else, or from an author who does not normally touch tooling.
