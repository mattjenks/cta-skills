---
name: implement
description: Builds an approved design or plan task by task with subagents, tests first, a spec check and at most two fix rounds per task on Normal changes, and a commit and push after each. Use after /build:design (Small) or /build:plan (Normal) is approved, or when asked to "implement this", "build it" or "start the tasks". Refuses unapproved work.
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
   have run in this session, do the hand-off in section 4 instead of starting the task. With no usage tool
   available, treat context as unknown and hand off every 3 tasks.
2. **Branch.** Before the builder commits anything, run `git branch --show-current` in the code repo. If it is
   the default branch, stop and tell the owner; never build there.
3. **Brief.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" brief PLAN TASK` writes the task brief;
   for a Small change write the brief by hand from the design (`brief` needs `### Task N:` headings, which a
   design file lacks; `workspace` and `package` accept the design file as PLAN). Record `base` = current HEAD in the ledger before the builder runs.
4. **Build.** Dispatch a builder subagent on the model the map in `references/models.md` names (haiku when
   the plan gives exact code, sonnet by default) with `references/implementer-prompt.md`, passing the brief
   path, the repo path and the Global Constraints path. The builder writes tests first and sees them
   fail, implements, runs the suite, commits its task work locally (a conventional message, never pushed),
   and reports `DONE`, `DONE_WITH_CONCERNS`,
   `NEEDS_CONTEXT` or `BLOCKED`. Right after its commit, record the ledger `head` (that commit's sha). Answer `NEEDS_CONTEXT` from the design; escalate `BLOCKED` to the owner.
5. **Review.** Small change: no per-task review; go to validate. The one code review happens in
   `/build:review`. Normal change: once the builder has committed,
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" package PLAN BASE HEAD` writes the review package
   (diff, brief, Review Focus). Dispatch a reviewer subagent on sonnet (map: `references/models.md`) with
   `references/reviewer-prompt.md`: a spec check only, not spec and quality, which the code review covers.
6. **Fix loop.** Critical or Important findings go through `references/fix-loop.md`: at most 2 rounds,
   re-review with `references/re-review-prompt.md` on sonnet. After round 2 the build does not stop: what
   is still open is recorded as `open at PR` in the ledger and goes into the PR description for the owner
   to decide before merge (`references/fix-loop.md`, `references/models.md`).
7. **Validate.** Run `/build:validate`. A FAIL goes back to the builder as a fix round.
8. **Dependency check.** Before the push, after the fix loop and validate (a fix can add one), read the
   whole task range `BASE..HEAD` (the builder's commit and every fix commit) for a new production dependency: any manifest or lockfile change
   (`pyproject.toml`, `package.json`, `requirements*.txt`, `go.mod`, `Cargo.toml`, `Gemfile` and similar)
   outside a dev group (development or build). **STOP before pushing:** present name, version, license and the reason, and
   wait for the owner. A dependency the approved plan already lists as verified is not new. Development and
   build dependencies do not count.
9. **Push and ledger.** Push the code branch (the commits already exist: the builder's, then one per fix
   round; nothing is rewritten). If the code repo is on its default branch, stop and tell the owner; never
   commit or push there. Then commit the ledger and any `reqs.md` change in the knowledge-base worktree
   (`docs(<slug>): progress after task <n>`) and push the build branch. Never push to the default branch,
   never touch the live knowledge-base checkout. A failed push: keep the commits, say so in the ledger and
   tell the owner; do not retry in a loop.
10. Mark the task `done` in the ledger with the head sha.

## 3. Finish

When every task is `done`: run `/build:validate` once over the whole branch, then tell the owner the build is
ready for `/build:secure` (scanners) and `/build:review` (the one code review). Do not start them uninvited.

## 4. Hand-off

Context is state you can lose, the ledger is not. Hand off to a fresh session at a task boundary, never
mid-task, when context passes 40% or after every 3 tasks, whichever comes first:

1. Make sure the ledger is current and committed and pushed in the worktree, and the code is committed and pushed.
2. Use the app's session hand-off with a short brief: the ledger path, the next task number, the topic, and
   the line "resume `/build:implement` from progress.md". Paths only, no pasted content.
3. Stop. The new session reads the ledger and carries on at the next `todo` task.

If the app has no hand-off tool, say so, give the owner that brief to paste into a new session, and stop.

## Resources

- `references/models.md`: the model map. Read before every dispatch.
- `references/implementer-prompt.md`: the builder's prompt, tests first.
- `references/reviewer-prompt.md`: the per-task spec check (Normal only), severities.
- `references/re-review-prompt.md`: the re-review of a fix, small diff.
- `references/fix-loop.md`: two rounds, then `open at PR`.
