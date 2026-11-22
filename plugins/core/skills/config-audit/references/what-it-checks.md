# What the audit checks

<!-- Adapted from coleam00/skills .claude/skills/agent-config-audit (MIT) -->

- **Config that runs code at startup**: hooks, status lines, MCP servers, plugins, skills
  with inline shell, VS Code folder-open tasks. North Korean attackers hid a backdoor
  download in `.claude/settings.json` hooks; an npm worm planted `SessionStart` hooks.
- **Poisoned dependencies**: manifests with no lockfile, and known-bad releases pinned or
  installed, like agent-framework 1.26.1 and 1.26.2 on PyPI, which stole keys through a
  `.pth` file that runs whenever Python starts.
- **Secrets saved by "don't ask again"**: keys inside approved commands and env in
  `settings.local.json`, and that file committed to git. Apiiro found 1,122 public ones.
- **Secrets in your conversation history**: keys pasted into Claude Code or Codex sessions
  sit on disk in the transcripts. Cursor's breach exposed stored agent traces with
  unredacted credentials.
- **Fake editor extensions**: known-bad versions in VS Code, Cursor or Windsurf, like the
  fake Claude Code extension 2.1.312 and 2.1.313 in Cursor's marketplace cache.
- **LLMjacking doors**: AI gateways left on a default key (LiteLLM `sk-1234`) and endpoint
  overrides that route your prompts and keys through someone else's server.
- **Hidden instructions**: invisible characters in `CLAUDE.md`, `AGENTS.md` and rules,
  text the agent reads and you cannot see.
