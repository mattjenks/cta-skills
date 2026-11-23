# Changelog

## [0.5.1](https://github.com/mattjenks/cta-skills/compare/core-v0.5.0...core-v0.5.1) (2026-11-23)


### Bug Fixes

* drop $schema from plugin.json so claude.ai stops warning ([39a07e1](https://github.com/mattjenks/cta-skills/commit/39a07e1a82be0c0111d78edac92a17a8e49e8396))
* drop $schema from plugin.json so claude.ai stops warning ([047df8c](https://github.com/mattjenks/cta-skills/commit/047df8cc0edf2cf728239c7bfb1481e117319495))

## [0.5.0](https://github.com/mattjenks/cta-skills/compare/core-v0.4.2...core-v0.5.0) (2026-11-23)


### Features

* **build:** implement and validate skills ([b4acb41](https://github.com/mattjenks/cta-skills/commit/b4acb41c7061053526eb0155ec63dac1a322cb3f))
* **build:** knowledge-base worktrees and project mapping ([1d6b29a](https://github.com/mattjenks/cta-skills/commit/1d6b29aaee2d75de2e90c293d7f283256e21fe92))
* **core:** create-skill, create-hook, config-audit ([005a8b8](https://github.com/mattjenks/cta-skills/commit/005a8b8363c5d6e191044223038690491a0b97c7))
* **core:** init-kb skill and templates ([d31776d](https://github.com/mattjenks/cta-skills/commit/d31776d087e15f6bcc85f366b3d226e56ef71b73))
* **core:** macOS notify hook ([e3cd7a8](https://github.com/mattjenks/cta-skills/commit/e3cd7a87e97a37f84623038808a6badd7319f597))
* **core:** notify only for turns over the threshold ([fbff115](https://github.com/mattjenks/cta-skills/commit/fbff115a6d7845e8601af84c752a17edcb2dfc83))
* **core:** secrets guard with content inspection ([ac031b1](https://github.com/mattjenks/cta-skills/commit/ac031b1a5fd2f46a9ecfa464a4ce1c583970717f))
* **core:** session-context hook and default persona ([8f04c51](https://github.com/mattjenks/cta-skills/commit/8f04c5112e3d2f4c7fccb5433853ae0e5c150f7c))
* **core:** skill budgets, evals and model map ([39611ea](https://github.com/mattjenks/cta-skills/commit/39611ea8378a6b872d4bfbfe343e32fb70d792c4))
* **core:** wire hooks ([9e2e7d7](https://github.com/mattjenks/cta-skills/commit/9e2e7d7242d39b8f9e533463f52739de72679a1e))
* CTA stage 2 build plugin ([517ef08](https://github.com/mattjenks/cta-skills/commit/517ef08a45de86ba6c2d03ba110d30bfa2cdb79c))
* **telemetry:** nightly backup, launchd schedules, restart resilience ([1e2b3ee](https://github.com/mattjenks/cta-skills/commit/1e2b3ee2ad780f5cea49eef0166ea9933bac3753))


### Bug Fixes

* **core:** config-audit runnable invocation ([3e79440](https://github.com/mattjenks/cta-skills/commit/3e794403b2a0523a1e1bc67f1f6df0d480366faf))
* **core:** persona fallback, CRLF-safe secrets guard, stale turn starts (0.4.1) ([7d8b523](https://github.com/mattjenks/cta-skills/commit/7d8b523d3370eab305d166f77a8f18615f318dac))
* **core:** route only non-notebook file_path to prose checks ([a84eed5](https://github.com/mattjenks/cta-skills/commit/a84eed59d077b68318f9ba3f56f1a3d318a63555))
* **core:** secrets guard bounded work, deadline, shortest-first bodies ([2d552eb](https://github.com/mattjenks/cta-skills/commit/2d552eb8fb52896d6b6a6923e65c8a112df5280c))
* **core:** secrets guard false positives, nesting blowup, backslash bypass ([d96858a](https://github.com/mattjenks/cta-skills/commit/d96858ac74bbfde3cdaf87a386e8440f1351f5a2))
* **core:** secrets guard linear content checks, no padding bypass ([51fa9d9](https://github.com/mattjenks/cta-skills/commit/51fa9d91b905d65201ca4087800c2c3afaebb8b5))
* **core:** secrets guard linear substitution scan, fail closed on complexity ([02e8164](https://github.com/mattjenks/cta-skills/commit/02e8164d620fc8628ce7cab1b3e2df069d43e897))
* **core:** secrets guard stops blocking prose that names env-dump builtins ([56e294c](https://github.com/mattjenks/cta-skills/commit/56e294c4cc12346f0acde3adeff3a1c41c41d53a))
* **core:** secure F1 F2 hybrid builtin-dump matching, unanchored except in prose files ([777a55d](https://github.com/mattjenks/cta-skills/commit/777a55d7aea652c462875a4a75e4b35f94158ad8))
* **core:** skill standard consistency and stricter budget tests ([75f2584](https://github.com/mattjenks/cta-skills/commit/75f258456eeb1e268144376f1a63e1b25a93658d))
* **core:** task 1 anchor secrets-guard builtin dump pattern to command position ([9245aa7](https://github.com/mattjenks/cta-skills/commit/9245aa71d51fbb92c4cdb322f811a8e0019ba27a))
* **core:** task 1 round 1 restore command-prefix and quoted -c coverage for builtin dumps ([785c121](https://github.com/mattjenks/cta-skills/commit/785c1211d091ed3c4924639947e0330856083acc))

## 0.4.2 — secrets guard prose false positive

- Secrets guard: content written to prose files (`.md`, `.markdown`, `.txt`, `.rst`, `.adoc`) matches the three environment-dump builtins only at command position (line start, after a separator, `$(`, a prefix word such as `then`/`sudo`/`eval`, or `-c`), so notes that merely name one are no longer blocked. Bash commands and all other file content keep the unanchored match, so a dump held in a string (piped to a shell, `trap`, `os.system`, a Dockerfile `RUN`) is still caught. Known gaps: a prose file holding a dump away from command position passes the Write, and Bash commands that only mention a builtin are blocked.

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
