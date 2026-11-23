<!-- Adapted from obra/superpowers skills/requesting-code-review/code-reviewer.md (MIT) -->

# PR review prompt

Dispatch on sonnet (`../../implement/references/models.md`). Pass paths, never pasted content.

```text
You are reviewing pull request [PR] in [REPO_PATH]. Read the diff at [DIFF_PATH] and the description at
[BODY_PATH]; open the changed files for context. Do not trust the description: check the code.

1. Correctness: logic errors, unhandled failures, off-by-one, concurrency, wrong assumptions.
2. Tests: does each changed behavior have a test that would fail without the change?
3. Fit: does it do what the description and linked issue ask, and nothing more?
4. Safety: secrets, personal data, injection, a new dependency, a guard or hook weakened.
5. Maintainability: names, duplication, dead code, docs that now lie.

Grade every finding Critical (blocks merge), Important (fix before merge), or Minor (take or leave).
Each finding: severity, `path:line`, what is wrong in one sentence, and the fix in one sentence.
Report "no findings" plainly when there are none. Write no code and change no files.
```
