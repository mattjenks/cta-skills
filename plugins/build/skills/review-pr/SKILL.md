---
name: review-pr
description: Reviews an open pull request - reads the diff and its description, checks correctness, tests and fit with the spec, then drafts a review and posts it only after the owner confirms. Use when asked to "review this PR", "review PR 12" or "look over this pull request". Takes a PR number or URL.
argument-hint: "<pr-number-or-url>"
---

<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md (MIT) -->

# Review PR

Review someone's open pull request the way the final branch review does, then publish it deliberately. Model
map: `../implement/references/models.md`.

## 1. Gather

1. `gh pr view <pr> --json number,title,body,baseRefName,headRefName,files,author,url` and `gh pr diff <pr>`
   to a file in a scratch directory outside the repo. An argument-less call uses the current branch's PR.
   No PR found: say so and stop.
2. Read the description, any linked issue or design (`gh issue view`), and CI status (`gh pr checks <pr>`).
3. A diff over about 1500 lines: review it by directory and say so, or ask the owner to split the work.
   Binary files are listed, not read.

## 2. Review

Dispatch one reviewer subagent on sonnet (model map: `../implement/references/models.md`) with the prompt in
`references/review-prompt.md`, passing the diff path, the description and the repo path; paths, never pasted
content. It grades findings Critical, Important and Minor with file and line, and writes no code. When the PR
touches hooks, guards, auth or secrets, or the owner asks for depth, run the reviewer on the strongest
model the map names for the final review instead.

Check its findings against the diff before keeping them: drop anything you cannot point to a line for.

## 3. Draft, confirm, post

Posting a review is public, so it is never automatic.

1. Draft the review: a one-paragraph verdict (approve, request changes, or comment), then findings by
   severity with `path:line` and the fix suggested. Save the draft to a file and show it.
2. Ask the owner to confirm. Wait for a clear yes; an edit request means revise and ask again.
3. After confirmation only: `gh pr review <pr> --approve|--request-changes|--comment --body-file <draft>`. For
   line comments use `gh api` with the draft's findings. Never merge, never approve on the owner's behalf
   without the yes.
4. Report the review URL.

## Resources

- `references/review-prompt.md`: the reviewer's prompt. Read when dispatching it.
