<!-- Adapted from obra/superpowers skills/subagent-driven-development/SKILL.md (MIT) -->

# Fix loop

Runs when a review returns Critical or Important findings. Minor findings are fixed only if the fixer is
touching that code anyway; otherwise they are dropped, never filed for later.

**Two rounds, then move on.** The loop never stops the build for the owner. After round 2, whatever is
still open is written to the ledger as `open at PR` (file, line, finding, what each round tried) and goes
into the PR description's **Open findings** section, where the owner decides before merge.

| Round | Fixer | Re-reviewer |
|---|---|---|
| 1 to 2 | the task's builder model | sonnet (`models.md`), scoped to the fix |

## Each round

1. Write the open findings to `<workspace>/findings-<task>-<round>.md` (file, line, issue, smallest fix).
2. Record the pre-fix sha (current HEAD) in the ledger, then dispatch the fixer with `implementer-prompt.md`, passing the findings path in place of the brief and the
   instruction: write the failing test for each finding first, then fix, and report as before.
3. The fixer commits on top (never rewriting history). Write the fix diff from the commit range, never a
   working-tree `git diff` (it would be empty): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" 
   package PLAN <pre-fix-sha> HEAD`. Record the round and the new head in the ledger.
4. Dispatch the re-reviewer with `re-review-prompt.md`, passing the findings path and the fix diff path that step 3 printed.
5. APPROVED: go on to validate. CHANGES REQUESTED: round 2 with the findings still open; after round 2,
   record what is open as `open at PR` and go on to validate.

## Rules

- Never start round 3. Never mark a task `blocked` for open review findings; `blocked` is only for a
  builder that reports `BLOCKED`.
- Opus is not used in this loop; the opus check is the one code review in `review`.
- Disagree with a finding? Say so in the findings file with the evidence and let the re-reviewer rule; do
  not skip it.
