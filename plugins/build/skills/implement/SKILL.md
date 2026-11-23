---
name: implement
description: Builds an approved design or plan task by task with subagents, tests first, a review and fix loop per task, and a commit and push after each. Use after /build:design (Small) or /build:plan (Normal) is approved, or when asked to "implement this", "build it" or "start the tasks". Refuses unapproved work.
argument-hint: "[topic]"
---

<!-- Adapted from obra/superpowers skills/subagent-driven-development/SKILL.md and skills/test-driven-development/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-implement/SKILL.md (MIT) -->

# Implement

Execute the approved work as the controller: you hold the ledger and dispatch, subagents write and review the
code. Execution is always subagent-driven; never ask the owner which execution method to use. Dispatch
prompts pass file paths, never pasted content. Model map: `references/models.md`.

## 0. Preconditions

1. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"` gives the active build
   (`worktree`, `folder`, slug, topic). `null` means no build is open: refuse and point to `/build:design`.
2. Read `<topic>-design.md` in the project folder and find the `Status:` line under its title.
   - Missing or not `Status: approved`: refuse, and point to `/build:design`.
   - `Status: approved — Small`: the design is the spec; there is no `plan.md`. Treat its parts as the tasks.
   - `Status: approved — Normal`: `plan.md` must exist in the same folder and be approved; if it does not,
     refuse and point to `/build:plan`.
3. Read `reqs.md` and the spec whole. Read the plan's Global Constraints and Review Focus; every brief and
   review carries them.

## 1. Workspace and ledger

- Workspace: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" workspace PLAN` (PLAN is `plan.md`, or the
  design file for a Small change). Briefs and review packages are written there, outside git status.
- Ledger: `<build.folder>/progress.md` (the build's `folder` from the pointer, in the knowledge-base
  worktree). One row per task: number, title, status (`todo`, `building`, `reviewing`, `fixing`, `done`,
  `blocked`), base and head sha, review rounds, notes. Write it before dispatching, update it after every
  step. A fresh session resumes from this file alone.

## 2. Per task

Repeat for each task in order, never in parallel.

1. **Usage check.** Before dispatching, read the context level and the account usage with the app's usage
   tool. Stop and tell the owner if the account is near its usage cap. If context is past 40% or three tasks
   have run in this session, do the hand-off in section 4 instead of starting the task.
2. **Brief.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" brief PLAN TASK` writes the task brief;
   for a Small change write the brief from the design by hand. Record `base` = current HEAD in the ledger.
3. **Build.** Dispatch a builder subagent on the model the map in `references/models.md` names (haiku when
   the plan gives exact code, sonnet by default) with `references/implementer-prompt.md`, passing the brief
   path, the repo path and the Global Constraints path. The builder writes tests first and sees them
   fail, implements, runs the suite, commits nothing, and reports `DONE`, `DONE_WITH_CONCERNS`,
   `NEEDS_CONTEXT` or `BLOCKED`. Answer `NEEDS_CONTEXT` from the design; escalate `BLOCKED` to the owner.
4. **Dependency check.** Before the commit, read the diff for a new production dependency: any manifest or
   lockfile change (`pyproject.toml`, `package.json`, `requirements*.txt`, `go.mod`, `Cargo.toml`, `Gemfile`
   and similar) outside a dev group (development or build). **STOP:** present name, version, license and the
   reason, and wait for the owner. A dependency the approved plan already lists as verified is not new.
   Development and build dependencies do not count.
5. **Review.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" package PLAN BASE HEAD` writes the
   review package (diff, brief, Review Focus). Dispatch a reviewer subagent on sonnet by default (map: `references/models.md`)
   with `references/reviewer-prompt.md`: one pass for spec and quality, with findings graded Critical,
   Important and Minor.
6. **Fix loop.** Anything Critical or Important goes through `references/fix-loop.md`: up to 5 rounds, the
   re-review uses `references/re-review-prompt.md`, and rounds 4 and 5 move to a fresh, more capable model.
   Still failing after round 5: mark the task `blocked` and stop for the owner with the open findings.
7. **Validate.** Run `/build:validate`. A FAIL goes back to the builder as a fix round.
8. **Commit and push.** Commit the code with a conventional message that names the task, in the code repo's
   current branch (never the default branch), then push it. Commit the ledger and any `reqs.md` change in the
   knowledge-base worktree (`docs(<slug>): progress after task <n>`) and push the build branch. Never push
   to the default branch, never touch the live knowledge-base checkout. A failed push: keep the commit, say
   so in the ledger and tell the owner; do not retry in a loop.
9. Mark the task `done` in the ledger with the head sha.

## 3. Finish

When every task is `done`: run `/build:validate` once over the whole branch, then tell the owner the build is
ready for `/build:secure` and `/build:review`. Do not start them uninvited.

## 4. Hand-off

Context is state you can lose, the ledger is not. Hand off to a fresh session at a task boundary, never
mid-task, when context passes 40% or after every 3 tasks, whichever comes first:

1. Make sure the ledger is current and committed and pushed in the worktree, and the code is committed.
2. Use the app's session hand-off with a short brief: the ledger path, the next task number, the topic, and
   the line "resume `/build:implement` from progress.md". Paths only, no pasted content.
3. Stop. The new session reads the ledger and carries on at the next `todo` task.

If the app has no hand-off tool, say so, give the owner that brief to paste into a new session, and stop.

## Resources

- `references/models.md`: the model map. Read before every dispatch.
- `references/implementer-prompt.md`: the builder's prompt, tests first.
- `references/reviewer-prompt.md`: the reviewer's prompt, spec and quality, severities.
- `references/re-review-prompt.md`: the re-review of a fix, small diff.
- `references/fix-loop.md`: rounds, escalation, when to stop.
