---
name: plan
description: Turns an approved design into a task plan with interfaces, tests and review focus, has it security-reviewed with the design, then stops for approval. Use after /build:design approves a normal change, or when asked to "write the plan", "plan this out" or "break this into tasks". Small changes skip it. Stops separately on any new production dependency.
argument-hint: "[topic]"
---

<!-- Adapted from obra/superpowers skills/writing-plans/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-plan-implementation/SKILL.md (MIT) -->

# Plan

Write the implementation plan for an engineer who has not seen this codebase or this design. A plan is the
set of decisions the implementer cannot make alone: which files, names and signatures, which values from the
design, which tests prove each task. It lives in the knowledge base, never in the code repo.

## 0. Preconditions

1. Read the active build: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"`.
   `null` means no build is open: run `/build:design` first.
2. The project folder is `<worktree>/<projects_dir>/<slug>/`; the design is `<topic>-design.md` there. Read it
   and `reqs.md` whole. Find the `Status:` line under the design's title. If it is missing or does not say
   `Status: approved`, refuse: the design is not approved, so go back to `/build:design`.
3. **Small change skips this skill.** If the line says `Status: approved — Small`, go to `/build:implement` with the design as the spec. If the plan grows past the
   small rule (more than 5 files, a production dependency, a security boundary), say so and continue here.

## 1. Research

Map what the plan must name exactly, from the code and the web where it helps:

- the files to create or change, and the existing patterns to mirror (file and line);
- the test framework, where similar tests live, the exact commands that run them;
- libraries involved: current versions, official docs with section anchors, known gotchas;
- anything the code contradicts in the design: surface it, never silently diverge.

Ask the owner a question only when the design, `reqs.md` and the code leave something open that changes the
plan. Number the questions, give each a recommended default, then stop and wait. If the owner declines, record
each guess as an `Assumed` line in the plan and mark the task it affects. Use a sonnet subagent for broad
research only when it saves context (models: `../implement/references/models.md`).

## 2. Write the plan

Write `<worktree>/<projects_dir>/<slug>/plan.md` using `references/plan-format.md`; read it first, since it
fixes the header, the Global Constraints and Review Focus sections, and the task shape. Requirements:

- **Global Constraints:** the design's project-wide rules, with exact values verbatim.
- **Review Focus:** five inputs or failure modes the design implies but no task's tests cover, most likely
  first; each gets a test in the task that owns the code.
- **Tasks:** each with Files, Interfaces (consumes and produces, exact signatures), and steps that start with a
  failing test, then implement, then verify, then commit.
- Right-size tasks: split only where a reviewer could reject one and approve its neighbor.
- Add the design's requirements as rows in `reqs.md` if the design stop did not already.

Then self-review: every design requirement has a task; names and types agree across tasks; no step is a
placeholder ("TBD", "handle edge cases"); the plan is not several times longer than the design.

## 3. Production dependencies

List every new **production** dependency the plan introduces (build and development dependencies do not count).
For each, present **name, version, license and the reason** it is needed, and what was considered instead.
**STOP: the owner verifies each new production dependency**, even in a plan that is otherwise small. Do not add
it to the plan's tasks as settled until the owner says yes; a no means the plan changes. No new production
dependency: say so in one line and go on.

## 4. Security review of the design and plan

Run `/build:secure plan`. It reviews the design and this plan together, before any code exists, and writes a
`## Threat model and accepted gaps` section into `plan.md`: what an attacker or a malformed input could
reach, what the plan defends, and what it deliberately accepts. Plan changes it asks for go into the tasks
now. That section is the line the final code review grades against.

## 5. Stop for the plan

**STOP: the owner approves the plan.** Give the path, the task count with one line per task, the Review Focus,
the threat model and accepted gaps, and any dependency verdicts. Wait. Do not start implementation on silence. Requested changes: edit and ask again.

After approval, commit and push the knowledge-base worktree (`docs(<slug>): plan for <topic>`; push to the
build branch only, never the knowledge base's default branch), then hand off to `/build:implement`.
Execution is always subagent-driven; do not ask which method to use.

## Resources

- `references/plan-format.md`: the header, Global Constraints, Review Focus and task shape. Read before writing.
- Model map: `../implement/references/models.md`.
