# Changelog

## 0.4.2 — secrets guard prose false positive

- Secrets guard: the three environment-dump builtins are matched only at command position (line start, after a separator, `$(`, `then`/`do`/`else`/`eval`/`exec`/`command`/`builtin`, or `-c`), so prose or notes that merely name one are no longer blocked. A dump builtin inside a backtick substitution in written file content is a known gap.

## 0.4.1 — telemetry backup config and fixes

- New `[telemetry] backup_dir` config key: the folder the nightly telemetry backup copies to.
- A configured persona file that is missing now falls back to the bundled default persona, still reported as `[cta] missing: <path>`.
- Secrets guard: CRLF and lone-CR line endings are normalized before scanning, so secret-file reads and whole-environment dumps in Windows-style files are caught.
- `turn_start.py` prunes turn records older than 24 hours (at most 200 checked per run); `notify.py` treats a start older than 24 hours as stale and stays silent.
- Telemetry backup: prints config problems to stderr, keeps only the newest 7 live snapshots (rotated copies are never pruned), and raises a macOS notification on any failure.

## 0.4.0 — notify only for long turns

- New `turn_start.py` (UserPromptSubmit) records when each turn starts; it prints nothing and fails open.
- `notify.py` notifies only when the turn ran at least `[notify] min_turn_seconds` (default 300); no recorded start or `CTA_UNATTENDED=1` stays silent. Stop clears the start; osascript output is discarded.

## 0.3.0 — authoring and audit skills

- `create-skill`: author or refactor a skill for a CTA plugin, with the house rules for placement, versioning, naming and baseline testing.
- `create-hook`: author a hook in the house `uv run --script` pattern, with the six pitfalls and required subprocess block and allow tests.
- `config-audit`: read-only audit of what a repository's agent config can run, with its scanner script and self-tests.

## 0.2.0 — hooks: session context, secrets guard, notify

- Config loader (`cta_config.py`) reads `~/.config/cta/config.toml` and falls back to defaults.
- Session-context hook injects the persona and configured context files, and falls back to the neutral default persona.
- Secrets guard blocks reads and writes of secret files and credential-bearing commands (exit 2).
- Notify hook raises a desktop notification on Stop and Notification, titled with the persona name.
- Hook wiring: `hooks/hooks.json` runs each hook through `uv run --script`.

## 0.1.0 — scaffold
