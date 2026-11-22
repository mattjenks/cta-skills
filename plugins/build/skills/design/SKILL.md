---
name: design
description: Starts new work by finding out what the owner actually wants, laying out approaches, writing the design into the project's knowledge-base folder, and stopping for approval. Use before building any feature, change or fix ("design this", "let's build", "I want to add"); also classifies the change small or normal.
argument-hint: "[topic or request]"
---

<!-- Adapted from obra/superpowers skills/brainstorming/SKILL.md and builder-check-prompt.md (MIT) -->

# Design

Find out what the owner wants and why before anything is built, then write it down and get it approved.
Design documents live in the knowledge base, never in the code repo. Nothing is built, scaffolded or
installed until the owner approves the design.

## 1. Resolve the knowledge base

Run from the code repo, with `${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py` (stdlib, prints JSON):

1. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" project --repo "$PWD"`.
   - `error` naming `kb` (not set in `~/.config/cta/config.toml`): **stop**, tell the owner to run
     `/core:init-kb`, and do nothing else.
   - `slug` is null (the repo is unmapped): ask the owner for a project slug (lowercase, digits, hyphens),
     then re-run with `--slug <slug>`, which calls `record_project` and writes it under `[projects]`.
2. Pick a `<topic>` slug for this change (lowercase, hyphens, at most 5 words) and say it.
3. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" open --kb <kb> --slug <slug> --topic <topic>
   --projects-dir <projects_dir> --repo "$PWD"`. It runs `open_build` and `write_pointer`: it creates the knowledge-base worktree and branch
   `build/<slug>-<date>-<topic>` from the knowledge base's default branch, and writes the active-build
   pointer (which also installs the commit gate). Keep the returned `worktree` and `folder`.

Never check out, edit or commit in the live knowledge-base checkout; every write goes in the worktree.
Without a git remote on the knowledge base, skip pushes and say so once.

## 2. Understand the intent

Before the first question, look: the project's existing design, `reqs.md` and `backlog.md` under
`<worktree>/<projects_dir>/<slug>/`, the code the request touches, and what `/build:prime` would show. Never
ask what they already answer. Then follow the conversation method in `references/conversation.md`:
ask one question at a time, open and in the owner's terms until the why is clear, and cover goals,
non-goals, anti-goals, prior art and current state. State your own calls as proposals with a reason.

## 3. Lay out the approaches

In a message of its own, give the two or three real approaches, grounded in this repo, with what each
trades off. Recommend one and say why. The owner picks before anything is written. When there is one
sensible way, say so and say why the others do not fit.

## 4. Write the design

Write `<worktree>/<projects_dir>/<slug>/<topic>-design.md`, the project folder (not the `builds/` folder).
Cover: intent and why, goals, non-goals, anti-goals, constraints, approaches (the options, what each
trades, the pick and why), the parts the owner decided as they decided them, your calls marked as yours,
and what is left to the builder. A talented builder who cannot reach the owner must be able to plan from it.
Add a `reqs.md` row for each new requirement in the same folder, following the project's existing format.

**Builder check.** For a normal change, dispatch a fresh subagent on sonnet (model map:
`../implement/references/models.md`) with `references/builder-check.md`, filling in the document path. Do not
hand over the document until it returns. Sort its questions: already answered (put the answer in the
document), minor (settle it, mark it as your call), the owner's (bring them in one message, most important
first, then update the document). One round only. A small change skips the check.

## 5. Classify and stop

Count against the rule: a **small change** is **5 files or fewer** changed, no new production dependency,
and no path matching **auth, secrets, hooks or CI** (`.github/`, `hooks/`, names containing `auth`, `secret`, `token`, `credential`). New build or development dependencies do not count. Otherwise
it is a **normal change**.

State the classification with the reason at the stop: the estimated files and which, the production
dependencies (none, or each name), and any sensitive paths. Use exactly "Small: plan review skipped" or
"Normal: plan review required". The owner can override either way; their word replaces the rule.

**STOP: the owner approves the design.** Present the path, the approach, your marked calls and the
classification, then wait. Do not continue on silence or on approval of the idea alone. If the owner asks
for changes, edit and ask again.

## 6. After approval

1. Commit the design (and `reqs.md`) in the worktree: `git -C <worktree> add` the files, then a
   conventional `docs(<slug>): design for <topic>` commit.
2. Push the worktree branch: `git -C <worktree> push -u origin build/<slug>-<date>-<topic>`. Never push to
   the knowledge base's default branch; the owner merges through a PR.
3. Hand off: normal change goes to `/build:plan`; small change goes straight to `/build:implement`. If
   implementation will add a production dependency, that still stops for the owner (see `/build:plan`).

## Resources

- `references/conversation.md`: how to ask, play back, and size the work. Read before the first question.
- `references/builder-check.md`: the prompt for the builder check. Read when dispatching it.
- Model map: `../implement/references/models.md`.
