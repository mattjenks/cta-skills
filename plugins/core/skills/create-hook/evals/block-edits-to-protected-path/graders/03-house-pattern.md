---
type: llm
focus: trace
weight: 1
---

The hook is a standalone script with a uv run --script shebang, stdlib only, wired in hooks.json with a command using ${CLAUDE_PLUGIN_ROOT} and a matcher limited to edit-type tools.
