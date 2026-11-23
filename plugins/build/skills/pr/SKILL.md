---
name: pr
description: Opens the pull requests for a finished build - checks that security.json matches the branch head, lists open findings, proposed false positives and known gaps in the PR for the owner to decide before merge, pushes the code and knowledge-base branches and opens both PRs linked to each other. Use after /build:review, or when asked to "open the PRs" or "ship it".
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

- 4: the record is missing or its `diff_hash` does not match the branch head. Rescan with `secure.py scan`
  (as `/build:review` section 4 does) and verify again. Never open a PR on a record for a different tree.
- 5: findings are still `open`. Do not stop: each goes into the PR's **Open findings** (section 2).
- 6: `proposed-false-positive` entries wait on the owner. Do not stop: they go into the PR (section 2).
- 0: continue.

## 2. Findings for the owner, in the PR

The build does not stop for findings; the owner decides at the PR, before merge. Only the owner closes a
finding as `false-positive` or `accepted-risk`, and the finding-guard hook blocks every other writer.
Never write `false-positive` or `accepted-risk` yourself, by any route.

1. Build the PR body's **Open findings** from `<folder>/pr-notes.md` (from `/build:review`) plus every
   entry `verify` named on exit 5 (an `open` status, an unknown status, or an owner closure missing
   `closed_by`): `id`, severity, `path:line`, the message, what was tried or what is missing.
2. List every `proposed-false-positive` entry there too, the whole batch at once, with your recorded
   reasoning and the exact edit the owner applies to `<folder>/security.json` themselves before merging:
   per `id`, set `status`, `reason` (their words) and `closed_by` (their name). Say the hook blocks the
   assistant from making it.
3. If the owner answers in the session, record their answers verbatim in `<folder>/closures.md` (one
   section per `id`) and commit it; after they apply the edit, re-verify with the same `verify` command.
4. Add the **Known gaps** from `pr-notes.md`.

## 3. Push

1. Code repo: `git push -u origin <branch>`. Knowledge-base worktree: commit anything pending
   (`docs(<slug>): ready for PR`) and `git -C <worktree> push -u origin <build-branch>`.
2. Never push to the default branch of either repo. A rejected push: report the error once and stop; do not force.
3. No remote on the knowledge base (`git -C <worktree> remote` is empty): skip the knowledge-base push and PR
   with one note. The code PR still opens.

## 4. Open both PRs

1. Code PR: `gh pr create --base BASE --head <branch> --title "<conventional title>" --body-file <body>`. The
   body gives the why, the changes, the validation and security result, the Open findings and Known gaps
   (section 2), and a link to the design.
2. Knowledge-base PR: `gh pr create` in the worktree against the knowledge base's default branch, titled
   `docs(<slug>): <topic> build record`.
3. Edit each PR body (`gh pr edit --body-file`) so each links the other. Report both URLs.

## 5. Clear the pointer

Last, after both PRs are open: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" clear --repo "$PWD"`
(`clear_pointer`). It leaves the commit gate in place while another worktree of the repo is still mid-build or
the repo opted in permanently. If a PR failed to open, do not clear: the build is not finished. Then point to
`/build:retro`.
