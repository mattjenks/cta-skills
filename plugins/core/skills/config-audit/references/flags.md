# Flag meanings

<!-- Adapted from coleam00/skills .claude/skills/agent-config-audit (MIT) -->

The flags are deliberately few, so each deserves a sentence in the report. Treat them as
leads, then read the entry itself.

| Flag | What it means in plain words |
|---|---|
| `pipe-to-shell`, `download-then-run` | Fetches code from the internet and runs it. Whoever controls that server controls the machine, and can change the payload at any time. The single strongest signal. |
| `encoded-payload` | base64 or `-EncodedCommand`: the readable command is a wrapper and the real one is hidden. Legitimate config almost never needs this. |
| `remote-host` | Contacts a host each time it runs. Ask who owns the domain and why a hook needs the network at all. "Silenced output" on top of that is worse. |
| `hidden-process` | A hidden window, `nohup`, `setsid`: keeps running after the agent moves on. |
| `credential-files` | Touches `~/.ssh`, `~/.aws`, `.npmrc`, agent login files. A formatter has no reason to. |
| `endpoint-override` | `ANTHROPIC_BASE_URL`, `*_BASE_URL`, proxies, `NODE_OPTIONS`: routes every prompt, file and key through someone else's server, or changes what code loads. |
| `unpinned-package` | An MCP server run through `npx`, `uvx` or `bunx` with no version, so the next release to that package runs automatically. Check the package exists, is the one intended (typosquats), and pin it. |
| `auto-approve-mcp` | `enableAllProjectMcpServers: true` approves every server in `.mcp.json`, including ones a later pull adds. |
| `bypass-permissions` | `bypassPermissions`, Codex `approval_policy = "never"` or `danger-full-access`: nothing asks before acting. |
| `broad-allow` | Allow rules like `Bash`, `Bash(curl *)`, `Bash(python *)` let the agent run arbitrary code without a prompt. Narrow them to exact commands. |
| `secret-in-config` | A literal key, password or token in env, headers, args or an allow rule. If the file was ever committed, rotating is required, not optional: it is still in git history. |
| `runs-on-open` | A VS Code or Cursor task with `runOn: folderOpen`: runs the moment the folder opens, before any agent starts. |
| `hidden-characters` | Zero-width or tag characters in an instruction file: instructions the agent reads and a reviewer cannot see. |
| `plugin-source` | Adds a plugin marketplace. Plugins ship their own hooks and MCP servers. |
| `hooks-reenabled` | A project file sets `disableAllHooks: false`, overriding a user who turned hooks off. |
| `no-lockfile` | A manifest with dependencies and no lockfile (in its folder or above it), so every install takes the newest release. That is how a poisoned release reaches a machine. |
| `known-compromised` | A lockfile, requirements pin or installed package matches a release known to carry malware. Remove it; if it was ever installed, treat every key on the machine as stolen. |
| `suspicious-pth` | A `.pth` file in a project virtualenv that is not a standard one and runs code every time Python starts. Only its name is printed; read it by hand. |
| `local-settings-tracked` | `.claude/settings.local.json` is in the git index, so approved commands and the secrets inside them get pushed. |
| `secret-in-history` | A key pasted into or printed in a stored Claude Code or Codex conversation. Rotate it, then delete or redact the transcript. |
| `known-bad-extension` | An installed editor extension version known to be fake or malicious. |
| `default-gateway-key` | A LiteLLM gateway set to its documented default key `sk-1234`: anyone who can reach it spends on your account. |
| `unparsed`, `unreadable` | The file could not be parsed or read. Read it by hand; a broken file can still run. |
