---
name: secure
description: Runs the security passes - in plan mode an opus review of a Normal change's design and plan (threat model and accepted gaps), otherwise the scanners (semgrep, gitleaks, dependency audit) over the branch, with a failing test, a fix and a record in security.json for each real finding. Use after /build:implement, or when asked to "security review", "scan this branch" or "check for vulnerabilities".
argument-hint: "[plan | base-branch]"
---

<!-- Adapted from obra/superpowers skills/requesting-code-review/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md and piv-fix-review-findings/SKILL.md (MIT) -->

# Secure

Two modes. `/build:secure plan` (Normal changes, from `/build:plan`) reviews the design and plan before any
code exists. `/build:secure` (both sizes, after implement) runs the scanners over the branch. The checklist
review of the code is part of the one code review in `/build:review`, which uses `references/checklist.md`.
Every real finding gets a failing test, a fix, a passing test and a record. Model map:
`../implement/references/models.md`.

## Plan mode

Dispatch one reviewer subagent on opus (model map: `../implement/references/models.md`) with the plan-review
prompt in `references/checklist.md`, passing the design and `plan.md` paths. It applies the nine checks to
what the plan will build and returns: the threat model, plan changes that close real routes (graded Critical,
High, Medium, Low), and the gaps worth accepting. Fold the Critical and High changes into the tasks, write
the `## Threat model and accepted gaps` section into `plan.md`, and return to `/build:plan` for its stop.
No scanners, no `security.json` in plan mode.

## 0. Preconditions

1. `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/kbwork.py" pointer --repo "$PWD"` gives the active build
   (`folder`). `null` means no build is open: point to `/build:design` and stop.
2. Base = the argument, else the repo's default branch. The code repo must be on the build branch, committed
   and clean; never run on the default branch. Findings live in `<build.folder>/security.json`.

## 1. Scan

Run `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/secure.py" scan --repo "$PWD" --base BASE --out <folder>/security.json`.
It calls `full_scan` (semgrep on the changed files, gitleaks over the branch history, an audit of every
manifest and lockfile) and records each finding as `open` with `diff_hash` set for the branch. Exit 3 is a
**STOP**: a scanner is missing or failed, so give the owner the install command it printed and wait. Never skip
a scanner, never continue without it, never record "no findings" for a scan that did not run. Semgrep's
`p/default` ruleset needs network access on its first run (`references/checklist.md`).

## 2. Checklist review of the code

Not here: the opus code review in `/build:review` runs the nine checks (injection, authn and authz, secrets,
deserialization, path traversal, SSRF, unsafe shell, crypto misuse, prompt injection) from
`references/checklist.md` and adds its security findings to `security.json` as `open` (`tool: checklist`).

## 3. Per finding

For every `open` scanner finding, one at a time, at most two fix attempts each. One still open after two
stays `open` and is listed in the PR's Open findings for the owner to decide before merge; the build does
not stop for it.

1. Decide: real, or a false positive. Say why in one line; for a false positive see section 4.
2. Real: write the failing test that shows the weakness, see it fail, fix the code, see it pass, run the
   suite (`/build:validate`). Commit (`fix(<scope>): ...`) and push the code branch.
3. Update that entry in `security.json` with Edit: `status: fixed`, `test` (the test id), `fix_commit`.
4. A fix that touches more than the finding's files, or that a test cannot cover (a config or a dependency
   bump), is stated to the owner before it is made.

A scanner finding that is a skipped or unscannable file (`scan.skipped-*`, `audit.not-audited:*`) is real
until the owner closes it: it cannot be fixed by a test.

## 4. Statuses

The assistant may write `open`, `fixed` and `proposed-false-positive` only. Never write `false-positive` or
`accepted-risk`: the owner closes a finding that way, with the reason in `reason` and their name in
`closed_by`, and the finding-guard hook blocks any other writer (shell edits included). For a likely false
positive set `proposed-false-positive` with the reason, then tell the owner which entries wait on them.

## 5. Finish

After the last fix, re-run the scan on the final head: `uv run --script "${CLAUDE_PLUGIN_ROOT}/scripts/secure.py" scan --repo "$PWD" --base BASE --out <folder>/security.json`.
It is the only thing that writes `head` and `diff_hash`, so they always describe a tree the scanners saw.
The rescan keeps every entry's status with three rules: a finding found again that was `fixed` reopens as
`open` (a regression: back to section 3); `false-positive`, `accepted-risk` and `proposed-false-positive`
are never changed; entries the scan did not rediscover are left as they are and printed as "not
rediscovered" (fixed ones are expected). A `security.json` that is not valid JSON stops the script (exit 2):
tell the owner, do not overwrite it.
Report: counts by status, the fixes with their commits, every entry waiting on the owner (`open`,
`proposed-false-positive`) and any "not rediscovered" entries. Commit and push `security.json` in the
knowledge-base worktree (`docs(<slug>): security pass`). Never push to the default branch.

## Resources

- `references/checklist.md`: the plan-review prompt, the nine checks, and scanner install and network notes.
  Read before plan mode and when a scanner stops the run.
