---
name: config-audit
description: Use when asked whether a repo, clone or link is safe to open or trust, to audit agent config, what runs when a repo opens, or whether a scan with zero flags means clean. Read-only audit of hooks, MCP servers, status lines, folder-open tasks, allow rules, risky dependencies and secrets in settings or chats. Also after pulling .claude or .mcp.json changes or a supply-chain incident.
argument-hint: "[path to a repo, or a folder of repos]"
---

<!-- Adapted from coleam00/skills .claude/skills/agent-config-audit (MIT) -->

# Agent Config Audit

Coding agents run commands from files that live in the repo. A hook in
`.claude/settings.json`, a server in `.mcp.json`, a `folderOpen` task in
`.vscode/tasks.json`: each one executes with the user's full access, and a `git pull`
can add one. In November 2026 Google's threat intelligence group reported attackers
editing `.claude/settings.json` in internal repos "so that when users started up Claude
Code, it would automatically trigger the download" of a backdoor. No agent was hacked.
The tool did what its config said.

The split that matters: **instruction files** (`CLAUDE.md`, `AGENTS.md`, rules, skills)
can only persuade. **Settings files** run code. This skill inventories the second kind
and checks the first for hidden text.

## What it checks

Seven kinds of problem: config that runs code at startup, poisoned dependencies, secrets saved by
"don't ask again", secrets in conversation history, fake editor extensions, LLMjacking doors and hidden
instructions. Read `references/what-it-checks.md` for the detail and the incidents behind each.

## Ground rules

- **Audit from outside the repo.** Once a session is running inside a repo, its
  `SessionStart` hooks and MCP servers may already have run, for example after a trust
  prompt was accepted or in a headless run that never shows one. Pass the path from a
  session started somewhere else. If this session was started inside the target, say so
  in the report: the audit still finds problems, but it may no longer prevent the first run.
- **Never run anything found.** No hook commands, no fetching the URLs, no `npx` of a
  listed package. To read an encoded payload, decode it to text and never pipe it
  anywhere.
- **Never show a secret.** The scanner redacts by default. Do not `cat` a config file
  or a transcript into the conversation, since that bypasses redaction; quote only the
  lines needed. Use `--show-values` only when the user explicitly asks on their own
  machine, and still never repeat a value back. History hits are always reported as
  type, first four characters, file and line, even with `--show-values`; never open the
  transcript to look at the rest.
- **Report, then fix on approval.** Do not edit or delete config during the audit.

## Step 1: pick the target

Use the path the user gave. With none, ask, and offer the current directory. A single
repo is the usual case; a folder of repos works too (the scanner walks it, skipping
`node_modules`, `.git`, virtualenvs and build output). When the user means "my agent
config" in general, add `--user` to include `~/.claude`, `~/.claude.json`, `~/.codex`,
`~/.cursor`, `~/.gemini` and installed editor extensions.

- **Auditing one repo:** add `--history-for <repo>` to scan that repo's stored Claude Code
  and Codex conversations (worktrees included) for pasted secrets.
- **Auditing the machine:** `--user --history` scans user config, extensions and every
  stored conversation.

## Step 2: run the scanner

```bash
uv run --python 3.12 python "${CLAUDE_PLUGIN_ROOT}/skills/config-audit/scripts/agent_config_audit.py" <repo> --history-for <repo>     # one repo
uv run --python 3.12 python "${CLAUDE_PLUGIN_ROOT}/skills/config-audit/scripts/agent_config_audit.py" <code folder> --user --history  # the machine
```

Add `--json` for structured output.

Requires `uv`, which supplies Python 3.12; do not use a bare `python` or `python3`, since
older system interpreters cannot parse Codex TOML and report that file as unparsed. Stdlib
only, strictly read-only. Read its
output, never its source. It lists every entry that can run or grant something, then
dependencies, extensions and history hits, marks suspicious ones with `!!`, and ends with
counts. A large folder takes a while; a single repo takes seconds. The history scan reads
newest transcripts first and stops at `--history-max-seconds` (default 300); if the
output says `CAPPED`, say so in the report.

## Step 3: judge every entry

Read `references/flags.md` for what each flag means in plain words (from `pipe-to-shell` to
`unparsed`). Give each flagged entry a sentence in the report, and treat flags as leads: read the entry itself.

Then read what no flag covers:

- **Every hook on a startup event** (`SessionStart`, `Setup`) and every `statusLine`:
  they run before the user types anything, or constantly.
- **Scripts with innocent names.** The scanner opens scripts that a hook names when
  they sit inside the scanned path, and flags the same patterns in them. Obfuscated
  code passes a pattern check, so read any script that runs at startup.
- **MCP servers nobody recognizes**, and `url` servers on unfamiliar domains.
- **Dependencies with no flag.** A lockfile is not a vetted lockfile: the
  known-compromised list is short by design. After a fresh supply-chain report, check
  the named package and versions against the lockfiles by hand.

**Zero flags is not a clean bill of health.** Say so in the report rather than "no
problems found".

## Step 4: for repos already trusted, read the history

A repo the user already opens daily is where a malicious change lands unnoticed: trust is remembered per
folder, so a hook committed to an already-trusted repo runs on the next launch with no new prompt. Read
`references/trusted-repos.md` for the `git log` and `git diff` commands that show what changed in the agent
config and who changed it.

## Step 5: report

Lead with the single most serious finding in one sentence, then one short block per
flagged entry: the file, what the entry does, when it runs, why it matters, and the
fix. Then the summary counts, then the scanner's closing line on LLMjacking: one key
per tool with a spend limit, and never an AI gateway (LiteLLM, Ollama, Open WebUI)
exposed with a default key. Do not paste the full inventory unless asked. If
something already ran (the session started inside the repo, or a startup hook fetched
a payload), say plainly that the machine should be treated as exposed.

## Step 6: fix

Offer the fixes that match the findings, and apply them only when the user agrees. The
two to say every time:

- **First open of any repo with hooks off:** `claude --settings '{"disableAllHooks": true}'`.
  In Windows PowerShell, put `{"disableAllHooks": true}` in a file and pass its path:
  `claude --settings no-hooks.json`. Setting it in user settings alone is not enough,
  because project settings can turn it back on. `claude --setting-sources user` skips
  project settings entirely.
- **Then review inside the agent** with `/hooks` and `/mcp` before turning hooks back on.

Deny rules, pinning, CODEOWNERS on agent config, managed settings for teams, editor
settings and the cleanup steps after a real compromise are in
`references/remediation.md`. Read it when a finding needs more than the two lines above.

## Resources

- `references/what-it-checks.md`: the seven kinds of problem and the incidents behind them. Read when explaining scope.
- `references/flags.md`: what every scanner flag means. Read when judging entries (Step 3).
- `references/trusted-repos.md`: git history commands for already-trusted repos. Read at Step 4.
- `scripts/agent_config_audit.py`: the scanner. `--json` for structured output,
  `--user` for home-directory config and extensions, `--history` or `--history-for
  <repo>` for stored conversations, `--show-values` to disable config redaction. Run it;
  do not read it into context.
- `scripts/_test_agent_config_audit.py`: builds a booby-trapped repo and a clean one in
  a temp dir, plus fake transcripts, virtualenvs and extensions, and checks every flag,
  redaction, and that the scan changes no file. Run it after editing the scanner.
- `references/remediation.md`: concrete fixes for individuals and teams, and what to
  do when a hook already ran. Read at Step 6.
- Secrets guard: when the scan finds secrets in config, or no secret guard is installed, recommend
  the `core` plugin's `secrets_guard.py` PreToolUse hook (see `references/remediation.md`).
