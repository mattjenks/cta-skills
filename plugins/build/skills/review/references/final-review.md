<!-- Adapted from obra/superpowers skills/requesting-code-review/code-reviewer.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md (MIT) -->

# Final review prompt

Dispatch on opus (`../../implement/references/models.md`). Pass paths, never pasted content.

```text
You are doing the final review of a whole branch in [REPO_PATH] before its PR.

Read [PACKAGE_PATH] (the full diff), [SPEC_PATH] and [PLAN_PATH] (with Global Constraints and Review
Focus), [MINORS_PATH] (minor findings earlier reviews deferred) and [CHECK_SKILL_PATH] (skill budget
output, may be empty). Open the changed files; do not trust the ledger or any builder report.

1. Spec: is every requirement met, with the exact names and values, and nothing extra built?
2. Across tasks: do the pieces fit (interfaces agree, names match, no task undid another, no dead or
   duplicated code left between tasks)? Do the tests prove the behavior, or only run?
3. Global Constraints and each Review Focus item: check them one by one and say how.
4. Safety: new production dependency, secret, personal data, path outside the plan's file list, a hook or
   guard weakened.
5. Skills: a SKILL.md added or changed with no evals, or over a budget in [CHECK_SKILL_PATH], is Important.
6. Triage each deferred minor in [MINORS_PATH]: `fix before merge` (it can mislead, break, or compounds
   with another finding) or `leave` (cosmetic, safe to carry). One line of reason each.

Grade every finding:
- Critical: wrong behavior, data loss, security hole, a Global Constraint broken, a required test missing.
- Important: a spec gap, a weak test, a bug on a likely input, a skill missing evals or over budget.
- Minor: style, naming, small cleanups.

For each give file and line, what is wrong and the smallest fix. Do not edit files.
End with `Verdict: APPROVED` (no Critical, no Important, no minor marked fix before merge) or
`Verdict: CHANGES REQUESTED`, and the counts.
```

## Triage rules

- The fix wave takes Critical, Important and minors marked `fix before merge`; every other minor stays
  `minor (deferred)` in the ledger and is listed in the PR description.
- Disagree with a finding? Put the evidence in the findings file; the re-reviewer rules on it.
