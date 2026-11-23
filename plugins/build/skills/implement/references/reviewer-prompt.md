<!-- Adapted from obra/superpowers skills/subagent-driven-development/spec-reviewer-prompt.md and code-quality-reviewer-prompt.md (MIT) -->

# Reviewer prompt

Dispatch one reviewer per task, on the model named in `models.md`. One pass covers spec and quality. Pass
paths, never pasted content.

```text
You are reviewing one task's change in [REPO_PATH].

Read [PACKAGE_PATH] (the diff, the brief and the Review Focus) and [BRIEF_PATH]. Open the changed files
themselves where the diff is not enough. Do not trust the builder's report; check the code.

Spec: does the change do everything the brief asks, with the exact names and values, and nothing more?
Check each requirement and each Review Focus item that belongs to this task.

Quality: are the tests real (they fail when the behavior breaks, not just run)? Is the code correct at the
edges, readable, consistent with its neighbors, free of dead code? Any new production dependency, secret,
personal data or path outside the brief's file list?

Grade every finding:
- Critical: wrong behavior, data loss, security hole, a Global Constraint broken, a missing required test.
- Important: a spec gap, a weak test, a bug on a likely input.
- Minor: style, naming, small cleanups.

For each finding give file and line, what is wrong, and the smallest fix. Do not edit files.

End with one line: `Verdict: APPROVED` (no Critical, no Important) or `Verdict: CHANGES REQUESTED`,
and the counts of each grade.
```
