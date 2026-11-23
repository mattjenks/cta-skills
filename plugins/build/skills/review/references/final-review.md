<!-- Adapted from obra/superpowers skills/requesting-code-review/code-reviewer.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md (MIT) -->

# Code review prompt

Dispatch on opus (`../../implement/references/models.md`). Pass paths, never pasted content.

```text
You are doing the one code review of a whole branch in [REPO_PATH] before its PR.

Read [PACKAGE_PATH] (the full diff), [DESIGN_PATH] (with its Accepted gaps), [PLAN_PATH] if given (Global
Constraints, Review Focus, Threat model and accepted gaps), [OPEN_ITEMS_PATH] (findings earlier rounds left
open), [CHECK_SKILL_PATH] (skill budget output, may be empty) and [CHECKLIST_PATH] (the nine security
checks). Open the changed files and the code they call; do not trust the ledger or any builder report.

1. Spec: is every requirement met, with the exact names and values, and nothing extra built?
2. Tests: do they prove the behavior (fail when it breaks), or only run?
3. Security: apply each of the nine checks to the code this branch adds or changes. Report only routes you
   can trace to a concrete input an attacker or a malformed file could control.
4. Safety: new production dependency, secret, personal data, a hook or guard weakened versus the base.
5. Skills: a SKILL.md added or changed with no evals, or over a budget in [CHECK_SKILL_PATH].

Grade against the stated line. A finding inside an accepted gap is not a defect: list it under "Inside
accepted gaps" in one line and do not grade it. A guard can always be probed one more way; report a
permutation only when it is a route the accepted gaps do not already cover.

Grade every other finding:
- Critical: wrong behavior, data loss, an exploitable security hole, a Global Constraint broken.
- High: a likely bug, a security route outside the accepted gaps, a required test missing, a skill
  missing evals or over budget.
- Medium: a weak test, an unlikely edge, a small spec drift.
- Low: style, naming, cleanups.

For each give file and line, what is wrong and the smallest fix. Do not edit files.
End with `Verdict: APPROVED` (no Critical, no High) or `Verdict: CHANGES REQUESTED`, and the counts.
```

## After the review

- The fix rounds take Critical and High; a Medium only when its fix sits in code the round already touches.
- Whatever is still open after two rounds goes to the PR's Open findings; the owner decides before merge.
- Disagree with a finding? Put the evidence in the findings file; the re-reviewer rules on it.
