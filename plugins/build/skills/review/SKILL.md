---
name: review
description: Runs the final whole-branch review before the PR - one deep review of the full diff against the spec, the ledger's deferred minor findings triaged, one fix wave and one scoped re-review. Use after /build:implement and /build:secure, or when asked to "review the branch", "final review" or "is this ready for a PR".
argument-hint: "[base-branch]"
---

<!-- Adapted from obra/superpowers skills/requesting-code-review/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md and piv-fix-review-findings/SKILL.md (MIT) -->

# Review

The last review before the PR: the whole branch, not one task. Per-task reviews catch local defects; this one
catches what only shows across tasks. Model map: `../implement/references/models.md`.

## 0. Preconditions

1. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"` gives the active build
   (`folder`, topic). `null` means no build is open: stop and point to `/build:design`.
2. Every ledger row (`<folder>/progress.md`) is `done`, and `/build:validate` passes on the branch now. If
   `security.json` is missing or has `open` entries, say so and point to `/build:secure`; do not review past it.
3. Base = the argument, else the default branch. The code repo is on the build branch and clean.

## 1. Gather

- Review package: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" package PLAN BASE HEAD` (the whole
  branch range). Paths only, never pasted content.
- Deferred minors: every `minor (deferred)` line in the ledger, collected into one file in the workspace.
- Skill changes: list the `SKILL.md` files the diff adds or changes, and for each run
  `uv run --script <plugins>/core/skills/create-skill/scripts/check_skill.py <skill-dir>`. A changed
  `SKILL.md` with no evals, or any budget failure it prints, is an Important finding (`references/final-review.md`).

## 2. Final review

Dispatch one reviewer subagent on opus (model map: `../implement/references/models.md`) with the prompt in
`references/final-review.md`, passing the package, spec and plan paths, the minors file and the check_skill
output. It grades findings Critical, Important or Minor and triages each deferred minor: fix before merge, or
leave. It writes no code.

## 3. One fix wave

Collect every Critical and Important finding plus the minors triaged "fix before merge" into one findings
file. Dispatch one builder per `../implement/references/models.md` (haiku for one or two files with exact
fixes, else sonnet) with `../implement/references/implementer-prompt.md`, tests first, one commit per logical
fix, never rewriting history. Run `/build:validate`. A fix that adds a production dependency stops for the
owner as in `/build:implement`. This is one wave: no second one.

## 4. One scoped re-review

Write the fix diff from the commit range (`workspace.py package PLAN <pre-fix-sha> HEAD`), then dispatch one
re-reviewer on sonnet (model map: `../implement/references/models.md`; opus only when the final reviewer found a
Critical) with `../implement/references/re-review-prompt.md`, passing the findings and fix diff paths. It checks
the fixes and what they touched, nothing else.

- APPROVED: push the code branch, record the verdict and the leftover minors in the ledger, say the branch is
  ready for `/build:pr`.
- CHANGES REQUESTED: stop. List what is still open for the owner; do not start another wave. If the fix
  changed code after `/build:secure`, say it should run again.

## Resources

- `references/final-review.md`: the reviewer prompt, grading and the minor-triage rules. Read before the
  final review dispatch.
