---
name: pr
description: Opens the pull requests for a finished build - checks that security.json matches the branch head with nothing open, stops once for the owner's answers on proposed false positives, pushes the code and knowledge-base branches and opens both PRs linked to each other. Use after /build:review, or when asked to "open the PRs" or "ship it".
argument-hint: "[base-branch]"
---

<!-- Adapted from coleam00/skills .claude/skills/piv-commit/SKILL.md and piv-implement/SKILL.md (MIT) -->

# PR

The last step before the owner's merge. Two branches ship together: the code and the knowledge-base build
branch (design, plan, ledger, security record, retro). Merges are the owner's; this skill never merges.

## 0. Preconditions

1. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"` gives the build
   (`worktree`, `folder`, `branch`). `null`: no build is open, point to `/build:design` and stop.
2. Base = the argument, else the code repo's default branch. The code repo is on the build branch, clean, and
   not on the default branch (never push there). `/build:review` has run.

## 1. Verify the security record

Run `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/secure.py" verify --repo "$PWD" --base BASE --file <folder>/security.json`.
It never writes. Exit codes:

- 4: the record is missing or its `diff_hash` does not match the branch head. Point to `/build:secure`
  (a rescan) and stop. Never open a PR on a record for a different tree.
- 5: findings are still `open`. List them, point to `/build:secure`, stop.
- 6: only `proposed-false-positive` entries wait on the owner: continue to section 2.
- 0: continue to section 3.

## 2. One STOP for proposed false positives

Only the owner closes a finding as `false-positive` or `accepted-risk`, and the finding-guard hook blocks every
other writer. Never write `false-positive` or `accepted-risk` yourself, by any route.

1. Show **every** `proposed-false-positive` entry in one message, the whole batch at once: `id`, severity,
   `path:line`, the message and your recorded reasoning. **STOP** once and ask for each entry: false-positive,
   accepted-risk (with the reason), or still real (it goes back to `/build:secure`).
2. Record the owner's answers verbatim, with their words, in `<folder>/closures.md` (one section per `id`)
   and commit it in the knowledge-base worktree.
3. Tell the owner the exact edit they apply to `<folder>/security.json` themselves: per `id`, set `status`,
   `reason` (their words) and `closed_by` (their name). Offer a one-line command they can run, and say the
   hook will block the assistant from doing it. Wait for them to say it is done.
4. Re-verify with the same `verify` command: it must now exit 0. Any other exit goes back to section 1; a
   record the owner has not updated is not a pass.

## 3. Push

1. Code repo: `git push -u origin <branch>`. Knowledge-base worktree: commit anything pending
   (`docs(<slug>): ready for PR`) and `git -C <worktree> push -u origin <build-branch>`.
2. Never push to the default branch of either repo. A rejected push: report the error once and stop; do not force.
3. No remote on the knowledge base (`git -C <worktree> remote` is empty): skip the knowledge-base push and PR
   with one note. The code PR still opens.

## 4. Open both PRs

1. Code PR: `gh pr create --base BASE --head <branch> --title "<conventional title>" --body-file <body>`. The
   body gives the why, the changes, the validation and security result, and a link to the design.
2. Knowledge-base PR: `gh pr create` in the worktree against the knowledge base's default branch, titled
   `docs(<slug>): <topic> build record`.
3. Edit each PR body (`gh pr edit --body-file`) so each links the other. Report both URLs.

## 5. Clear the pointer

Last, after both PRs are open: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" clear --repo "$PWD"`
(`clear_pointer`). It leaves the commit gate in place while another worktree of the repo is still mid-build or
the repo opted in permanently. If a PR failed to open, do not clear: the build is not finished. Then point to
`/build:retro`.
