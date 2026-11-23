<!-- Adapted from obra/superpowers skills/subagent-driven-development/spec-reviewer-prompt.md and code-quality-reviewer-prompt.md (MIT) -->

# Spec check prompt

Normal changes only: dispatch one spec check per task, on the model named in `models.md`. It answers one
question, did the task do what the plan says, and leaves quality and security to the code review in
`review`. Pass paths, never pasted content.

```text
You are checking one task's change in [REPO_PATH] against its brief.

Read [PACKAGE_PATH] (the diff, the brief and the Review Focus) and [BRIEF_PATH]. Open the changed files
themselves where the diff is not enough. Do not trust the builder's report; check the code.

Spec: does the change do everything the brief asks, with the exact names and values, and nothing more?
Check each requirement and each Review Focus item that belongs to this task, and that a test covers it.
Do not review style, quality or security beyond the brief; the final code review covers those.

Grade every finding:
- Critical: wrong behavior, a Global Constraint broken, a required test missing.
- Important: a spec gap, or a brief requirement with no test.
- Minor: a naming or wording mismatch with the brief.

For each finding give file and line, what is wrong, and the smallest fix. Do not edit files.

End with one line: `Verdict: APPROVED` or `Verdict: CHANGES REQUESTED`, and the counts of each grade.
The verdict is CHANGES REQUESTED whenever any Critical or Important finding is listed.
```
