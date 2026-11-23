---
name: loop
description: Runs the whole build from request to PR - prime, design, plan (normal changes only), implement, validate, secure, review, pr and retro - announcing each stop and the small or normal call. Use when asked to "build this", "run the loop", "take this from idea to PR" or when /build:fix-issue hands over work.
argument-hint: "<what to build>"
---

<!-- Adapted from coleam00/skills .claude/skills/piv-loop/SKILL.md (MIT) -->

# Loop

The conductor. It sequences the other skills and holds the stops; it does not repeat their procedures. Each
step is `/build:<skill>`, and each skill's own preconditions apply. Execution always goes through
`/build:implement`; never ask the owner which execution method to use.

## 0. Start

1. The code repo is a git work tree and not on its default branch work will be built on (a build branch is
   cut if it is). The knowledge base must be a git repo: if `kb` is unset or it is not a git repo, **stop** and
   point to `/core:init-kb`, which runs `git init` and optionally `gh repo create --private`. A knowledge base
   with no remote is allowed; pushes and its PR are skipped with a note.
2. If a build is already active (`kbwork.py pointer --repo "$PWD"` is not `null`), resume it from the
   ledger instead of starting another. The commit gate lives in git config and can go stale when the plugin
   updates: run `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" gate --repo "$PWD"`. It calls
   `gate_installed` and, when the gate is missing or its hooksPath is stale, runs `install_gate` again and
   prints `reinstalled`. Announce a repair.
3. Say the plan in one line: the stops ahead and that the owner approves the design (and the plan).

## 1. The chain

Announce each step as it starts ("Step 3 of 9: implement") and each stop as it is reached.

1. `/build:prime` (skip if the session already primed this repo).
2. `/build:design`. **STOP**: the owner approves the design. The classification is announced here, as
   "Small: plan review skipped" or "Normal: plan review required", with its reason; the owner can override.
3. `/build:plan`, **normal changes only**. A small change skips the plan and goes straight to implement.
   **STOP**: the owner approves the plan.
4. `/build:implement`. Stops it raises (a production dependency, a blocked task, the usage cap, hand-off) are
   the loop's stops too; relay them and continue only on the owner's answer.
5. `/build:validate` over the whole branch.
6. `/build:secure`. A scanner stop is a stop.
7. `/build:review`.
8. `/build:pr`. Its one STOP for proposed false positives is the loop's.
9. `/build:retro`.

## 2. Rules

- Never skip or reorder steps; a failed step is fixed in place or reported, not routed around.
- Never proceed past a STOP on silence. A step that cannot run (a missing scanner, no remote) is announced,
  not hidden.
- After a hand-off to a fresh session (`/build:implement` section on hand-off), the new session resumes at the
  next unfinished step from the ledger and the design's `Status:` line.
- Merges are the owner's. The loop ends with the PR links and the retro summary.
