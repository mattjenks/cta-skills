---
name: pr
description: Opens the pull requests for a finished build - checks that security.json matches the branch head, lists the reviewer's closures, open findings and known gaps in the PR for the owner to decide before merge, pushes the code and knowledge-base branches and opens both PRs linked to each other. Use after /build:review, or when asked to "open the PRs" or "ship it".
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
- 6: `proposed-false-positive` entries are still unresolved: the review step did not close them. Go back
  to `/build:review` once to resolve them, then rescan and verify again; if review already re-asked, list
  each unresolved entry under Open findings for the owner.
- 0: continue.

## 2. Findings and closures, in the PR

The build does not stop for findings; the owner decides at the PR, before merge. The independent review
closes false positives; this skill never writes `false-positive` or `accepted-risk`, by any route.

1. Build the PR body's **Open findings** from `<folder>/pr-notes.md` (from `/build:review`) plus every
   entry `verify` named on exit 5 (an `open` status, an unknown status, or a closure missing `reason` or
   `closed_by`): `id`, severity, `path:line`, the message, what was tried or what is missing. Accepted
   risk is the owner merging with the finding listed there.
2. List every reviewer closure under **Closed by review**: `id`, severity, `path:line`, the
   `reason` and `closed_by`, so the owner can overrule any of them before merge.
3. If the owner gives words in the session (an overrule or an accepted risk), record them verbatim in
   `<folder>/closures.md` (one section per `id`) and commit it.
4. Add the **Known gaps** from `pr-notes.md`.

## 3. Push

1. Code repo: `git push -u origin <branch>`. Knowledge-base worktree: commit anything pending
   (`docs(<slug>): ready for PR`) and `git -C <worktree> push -u origin <build-branch>`.
2. Never push to the default branch of either repo. A rejected push: report the error once and stop; do not force.
3. No remote on the knowledge base (`git -C <worktree> remote` is empty): skip the knowledge-base push and PR
   with one note. The code PR still opens.

## 4. Open both PRs

1. Code PR: `gh pr create --base BASE --head <branch> --title "<conventional title>" --body-file <body>`. The
   body gives the why, the changes, the validation and security result, the Open findings, closures and Known gaps
   (section 2), and a link to the design.
2. Knowledge-base PR: `gh pr create` in the worktree against the knowledge base's default branch, titled
   `docs(<slug>): <topic> build record`.
3. Edit each PR body (`gh pr edit --body-file`) so each links the other. Report both URLs.
4. Watch the code PR. When the desktop app's PR tools are available (`get_status`, `bind_pr`,
   `set_monitor`): read `get_status`; if the code PR is not bound to this session, bind it with
   `bind_pr`. Then call `set_monitor` with the code PR's `url`, `auto_fix: true`,
   `address_comments: true` and `auto_archive_on_close: true`. This skill is the owner's standing request for these switches,
   attended or unattended: do not ask about Auto-fix. Never set auto-merge;
   never bind or watch the knowledge-base PR. If the tools are missing, or the app refuses or no
   approval comes, say in the report that Auto-fix and archive-on-close are off and continue;
   never retry through another session.

## 5. Clear the pointer

Last, after both PRs are open: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" clear --repo "$PWD"`
(`clear_pointer`). It leaves the commit gate in place while another worktree of the repo is still mid-build or
the repo opted in permanently. If a PR failed to open, do not clear: the build is not finished. Then point to
`/build:retro`.
