---
name: validate
description: Detects and runs the repo's test, type-check and lint commands and reports one PASS or FAIL with the failing output. Use after any change, before a commit or a "done" claim, or when asked to "validate", "run the checks" or "does it pass". Reports only what it ran this turn.
argument-hint: "[tests | types | lint]"
---

<!-- Adapted from obra/superpowers skills/verification-before-completion/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-validate/SKILL.md (MIT) -->

# Validate

Run the repo's own checks and report what happened, with evidence. No claim of "passes" or "done" without
output from a command run this turn: fresh evidence, never memory of an earlier run or a builder's report.
This skill dispatches nothing. It runs the commands itself.

## 1. Detect the commands

Prefer what the repo declares, in this order, and stop at the first source that names a command per kind:

1. Project instructions (`CLAUDE.md`, `README`, `CONTRIBUTING`) and CI files (`.github/workflows/*`):
   the commands they run.
2. `Makefile` or `justfile` targets named `test`, `check`, `lint`, `typecheck`, `types`.
3. `package.json` scripts (`test`, `lint`, `typecheck`, `check`); run with the lockfile's package manager.
4. `pyproject.toml`, `pytest.ini` or `tox.ini` (pytest, ruff, mypy, pyright as configured); `go.mod`
   (`go test ./...`, `go vet ./...`); `Cargo.toml` (`cargo test`, `cargo clippy`).

Three kinds: test, type check, lint. A kind the repo does not configure is `skipped (not configured)`, never
invented. If nothing at all is found, report that and ask the owner for the commands.
An argument (`tests`, `types`, `lint`) narrows the run to that kind.

## 2. Run

Run each detected command from the repo root, once, in the order test, type, lint. Do not stop at the first
failure; run them all so one report shows every problem. Do not edit code, install packages, or change
config to make a command pass. Do not set quiet or "ignore failures" flags the repo did not choose.

## 3. Report

One verdict, `PASS` or `FAIL`, as the first line:

- `PASS` only when every command that ran exited 0 and at least one ran.
- `FAIL` when any exited non-zero, timed out or could not start.

Then a table: kind, the exact command, exit code, and a one-line result (counts for tests). For each failing
command give the failing output: the relevant lines of its output, trimmed to the failures (the assertion,
the error, file and line), not the whole log. Say what was skipped and why.

A FAIL is a finding, not a task: report it and return. When called from `/build:implement`, the failing
output goes back to the builder as a fix round.
