<!-- Adapted from obra/superpowers skills/subagent-driven-development/code-quality-reviewer-prompt.md (MIT) -->

# Re-review prompt

After a fix round, dispatch a re-reviewer on the model named in `models.md` (a small fix diff is a haiku job;
a Critical finding raises it, see the map). It checks the fix, not the whole task again.

```text
A reviewer found these issues in [REPO_PATH]: [FINDINGS_PATH]. A fix was made.

Read [FINDINGS_PATH] and the fix diff [FIX_DIFF_PATH]. For each finding, say whether the fix resolves it,
with the file and line that shows it. Then check that the fix broke nothing nearby and added no new problem
of its own, graded Critical, Important or Minor as before. Do not review unrelated code. Do not edit files.

End with `Verdict: APPROVED` or `Verdict: CHANGES REQUESTED`, and list the findings still open.
```

Write the fix diff with `git diff <before-fix-sha> HEAD > <workspace>/fix-<n>.diff` and pass the path.
