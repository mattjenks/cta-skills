---
name: review
description: Runs the one code review before the PR - a single opus pass over the whole branch for spec, quality and security (the nine checks, graded against the design's accepted gaps and the plan's threat model), at most two fix rounds, and what is left listed for the PR. Use after /build:implement and /build:secure, or when asked to "review the branch", "final review" or "is this ready for a PR".
argument-hint: "[base-branch]"
---

<!-- Adapted from obra/superpowers skills/requesting-code-review/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md and piv-fix-review-findings/SKILL.md (MIT) -->

# Review

The one code review, for both sizes: spec, quality and security in a single pass over the whole branch. It
grades against a stated line, the design's `Accepted gaps` and, for a Normal change, the plan's `Threat model
and accepted gaps`, so it finds what matters and stops there. Model map: `../implement/references/models.md`.

## 0. Preconditions

1. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"` gives the active build
   (`folder`, topic). `null` means no build is open: stop and point to `/build:design`.
2. Every ledger row (`<folder>/progress.md`) is `done`, and `/build:validate` passes on the branch now. If
   `security.json` is missing, the scanners have not run: point to `/build:secure`. Scanner entries still
   `open` do not stop the review; they go to the PR.
3. Base = the argument, else the default branch. The code repo is on the build branch and clean.

## 1. Gather

- Review package: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workspace.py" package PLAN BASE HEAD` (the whole
  branch range). Paths only, never pasted content.
- Open items: every `open at PR` line in the ledger, collected into one file in the workspace.
- Skill changes: list the `SKILL.md` files the diff adds or changes, and for each run core's checker:
  `uv run --script <check_skill.py> <skill-dir>`. The script belongs to the `core` plugin, so find it from
  this plugin's root: `${CLAUDE_PLUGIN_ROOT}/../core/skills/create-skill/scripts/check_skill.py` in a repo
  checkout, or `${CLAUDE_PLUGIN_ROOT}/../../core/*/skills/create-skill/scripts/check_skill.py` when the
  marketplace installed both plugins side by side (the installed layout is `<marketplace>/<plugin>/<version>/`;
  take the newest version). If neither exists the script is missing: report that as a High finding
  and never skip the check silently. A changed `SKILL.md` with no evals, or any budget failure it prints, is
  a High finding (`references/final-review.md`).

## 2. The code review

Dispatch one reviewer subagent on opus (model map: `../implement/references/models.md`) with the prompt in
`references/final-review.md`, passing the package, the design (with its Accepted gaps), the plan for a
Normal change, the open-items file, the check_skill output and `../secure/references/checklist.md` for the
nine checks. It grades findings Critical, High, Medium or Low, says which fall inside an accepted gap, and
writes no code. Add each security finding to `security.json` as `open` (`tool: checklist`).

## 3. Fix, at most two rounds

Collect every Critical and High finding into one findings file; add a Medium only when the fix is in code
the round already touches. Dispatch one builder per `../implement/references/models.md` (haiku for one or
two files with exact fixes, else sonnet) with `../implement/references/implementer-prompt.md`, tests first,
one commit per logical fix, never rewriting history. Run `/build:validate`. A fix that adds a production
dependency stops for the owner as in `/build:implement`. Mark fixed security entries `fixed` in
`security.json`.

Then one scoped re-review: write the fix diff from the commit range (`workspace.py package PLAN
<pre-fix-sha> HEAD`) and dispatch one re-reviewer on sonnet (model map: `../implement/references/models.md`)
with `../implement/references/re-review-prompt.md`. CHANGES REQUESTED: one more round, the second and last.

## 4. Hand to the PR

The review never stops the build. After the last round:

1. Resolve the proposals. The builder never closes a finding; this review, which did not write the code,
   does. For each `proposed-false-positive` in `security.json`, open the code and the recorded reasoning,
   then either close it (`status: false-positive`, a non-empty `reason` in your own words, `closed_by:
   "review"`) or send it back to `open` with why. Close only a finding you can show is not exploitable;
   a doubtful one goes back to `open`. Set `false-positive` only, never `accepted-risk`: a real finding
   nobody can fix stays `open` and goes to the PR. Edit each entry with Edit.
2. Rescan so the record matches the tree: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/secure.py" scan
   --repo "$PWD" --base BASE --out <folder>/security.json`, then `secure.py verify` (as `/build:pr` runs it)
   to confirm no proposal is left (exit 6 means one is).
3. Write `<folder>/pr-notes.md`: **Open findings** (every Critical or High still open, with file, line and
   what the rounds tried; the owner decides each before merge; plus every ledger `open at PR` line copied
   as is, an Important there counting as High, whatever the reviewer said of it) and **Known gaps** (the accepted gaps the
   review confirmed, one line each). Mediums and Lows not fixed are dropped, never filed for later.
4. Push the code branch, record the verdict in the ledger, and say the branch is ready for `/build:pr`.

## Resources

- `references/final-review.md`: the reviewer prompt and the grading. Read before the review dispatch.
