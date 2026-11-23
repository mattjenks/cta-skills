<!-- Adapted from obra/superpowers skills/subagent-driven-development/SKILL.md (MIT) -->

# Fix loop

Runs when a review returns Critical or Important findings. Minor findings are noted in the ledger and fixed
only if the builder is touching that code anyway.

| Round | Fixer | Re-reviewer |
|---|---|---|
| 1 to 3 | the task's builder model | sonnet at least (`models.md`) |
| 4 to 5 | a fresh subagent on opus, new context | opus |

## Each round

1. Write the open findings to `<workspace>/findings-<task>-<round>.md` (file, line, issue, smallest fix).
2. Record the pre-fix sha (current HEAD) in the ledger, then dispatch the fixer with `implementer-prompt.md`, passing the findings path in place of the brief and the
   instruction: write the failing test for each finding first, then fix, and report as before.
3. The fixer commits on top (never rewriting history). Write the fix diff from the commit range, never a
   working-tree `git diff` (it would be empty): `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" 
   package PLAN <pre-fix-sha> HEAD`. Record the round and the new head in the ledger.
4. Dispatch the re-reviewer with `re-review-prompt.md`, passing the findings path and the fix diff path that step 3 printed.
5. APPROVED: go on to validate. CHANGES REQUESTED: next round with the findings still open.

## Escalation

- From round 4 on (rounds 4 and 5), use a fresh agent on the most capable model: two failed rounds by the same context is a
  sign it cannot see the problem. Say in the ledger why the round escalated.
- A Critical finding from a sonnet reviewer sends its re-review to opus, whatever the round (model rules:
  `models.md`).
- After round 5 with findings still open, stop. Mark the task `blocked`, write the findings and what each
  round tried to the ledger, and ask the owner. Never start round 6 and never approve with open Critical
  or Important findings.
- Disagree with a finding? Say so in the findings file with the evidence and let the re-reviewer rule; do
  not skip it.
