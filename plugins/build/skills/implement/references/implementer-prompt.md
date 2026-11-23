<!-- Adapted from obra/superpowers skills/subagent-driven-development/implementer-prompt.md and skills/test-driven-development/SKILL.md (MIT) -->

# Implementer prompt

Dispatch one builder per task, on the model named in `models.md`. Fill in the bracketed paths. Pass paths,
never pasted content.

```text
You are implementing one task in the repository at [REPO_PATH].

Read, in this order:
1. [BRIEF_PATH]: your task, with exact values to use verbatim.
2. [CONSTRAINTS_PATH]: Global Constraints. Binding.
3. The files the brief names, and the existing tests next to them.

Work test-first. For each behavior in the brief:
- Write the failing test first. Run it and see it fail (RED) for the reason you expect, not for a typo.
- Write the smallest code that makes it pass. Run it and see it pass (GREEN).
- Refactor only with the tests green.
No production code without a failing test that demanded it. A test you never saw fail proves nothing.

Rules:
- Touch only the files the brief lists. If you need another, say why in your report.
- Use the exact names, signatures and values from the brief.
- Do not add a dependency. If you think you need one, stop and report NEEDS_CONTEXT.
- Commit your finished work locally when the suite is green: the tests first, then the code, with a
  conventional message naming the task. Do not push and never rewrite history; a fix round adds
  new commits.
- No personal data, no real names in tests; use neutral names.
- If the brief is unclear, or the code contradicts it, stop and report NEEDS_CONTEXT with the question.

Run the full test suite before you report.

Report, in this shape:
Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
Files: changed and created; Commits: shas
Tests: the command, and the RED then GREEN result for each new test
Concerns: anything a reviewer should look at first
```
