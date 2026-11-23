---
name: retro
description: Writes the build retrospective and records it as telemetry - plan versus actual, corrections, slow steps, review findings by severity and category, fix rounds and gates fired, plus the owner's 1 to 5 rating, sent as a cta.build event. Use after /build:pr, or when asked to "run the retro", "retrospective" or "how did that build go".
argument-hint: "[topic]"
---

<!-- Adapted from coleam00/skills .claude/skills/system-execution-report/SKILL.md (MIT) -->

# Retro

Learn from the build while it is fresh. Facts come from the build's own files, not memory. Model map:
`../implement/references/models.md`.

## 1. Gather

`uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"` gives `folder`. If the
pointer was cleared by `/build:pr`, the owner or the argument names the build folder. Read, in
`<folder>` and the project folder: `progress.md` (the ledger: tasks, rounds, notes), `security.json`, the
design and `plan.md`, and the commit log of the branch. For a long build, dispatch one subagent on sonnet
(model map: `../implement/references/models.md`) to digest them with `references/retro-template.md`; otherwise
do it directly.

## 2. Write `retro.md`

Write `<folder>/retro.md` following `references/retro-template.md`: plan vs actual (tasks added, dropped or
resized), corrections the owner made, slow steps and why, findings by severity and by category, fix rounds
per task, gates that fired (security gate, validate, dependency stop, scanner stops), and what to change next
time. Facts, with numbers; no blame, no padding.

## 3. Ask for the rating

Ask the owner for a 1 to 5 rating of the build (5 best) and one line on why. They may decline: record
`rating` as empty and move on. Never invent or default a rating.

## 4. Send the event

Write the fixed fields to a scratch JSON file (keys in `references/retro-template.md`: `slug`, `topic`,
`size`, `tasks`, `fix_rounds`, `findings_critical`, `findings_important`, `findings_minor`, `gates`,
`rating`), then run
`uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/retro_event.py" --file <retro-fields.json>`.

- Exit 0: sent as the `cta.build` event.
- Exit 1: the collector at 127.0.0.1:4318 is unreachable. Say so in the report and in `retro.md`; this does not
  block anything. Never retry in a loop.
- Exit 2: a field is invalid; fix the file and run it once more.

## 5. Commit

Commit and push `retro.md` in the knowledge-base worktree (`docs(<slug>): retro for <topic>`) when its PR is
still open; if the PR has merged, tell the owner the retro is uncommitted and where it is. Never push to the
default branch.

## Resources

- `references/retro-template.md`: the sections of `retro.md` and the event field list. Read before writing.
