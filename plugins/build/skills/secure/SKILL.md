---
name: secure
description: Runs the security pass on a branch before its PR - scanners (semgrep, gitleaks, dependency audit) plus a checklist review, with a failing test, a fix and a record in security.json for each real finding. Use after /build:implement, or when asked to "security review", "scan this branch" or "check for vulnerabilities".
argument-hint: "[base-branch]"
---

<!-- Adapted from obra/superpowers skills/requesting-code-review/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-review-changes/SKILL.md and piv-fix-review-findings/SKILL.md (MIT) -->

# Secure

The security pass over the whole branch. Scanners find the known patterns; a checklist review on the most
capable model finds the rest. Every real finding gets a failing test, a fix, a passing test and a record.
Model map: `../implement/references/models.md`.

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

## 2. Checklist review

Dispatch one reviewer subagent on opus (model map: `../implement/references/models.md`) with the prompt in
`references/checklist.md`, passing paths only: the review package from `workspace.py package PLAN BASE HEAD`
and `security.json`. It covers injection, authn and authz, secrets, deserialization, path traversal, SSRF,
unsafe shell, crypto misuse and prompt injection, and returns findings graded Critical, High, Medium, Low
with file, line and the exploit in one sentence. Add each new real finding to `security.json` as `open`
(`tool: checklist`).

## 3. Per finding

For every `open` finding, one at a time:

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

After the last fix run `secure.py stamp --repo "$PWD" --base BASE --out <folder>/security.json` so `head` and
`diff_hash` match the final branch (re-run the scan if any fix changed code the first scan did not cover).
Report: counts by status, the fixes with their commits, and every entry waiting on the owner
(`open`, `proposed-false-positive`). Commit and push `security.json` in the knowledge-base worktree
(`docs(<slug>): security pass`). Never push to the default branch.

## Resources

- `references/checklist.md`: the reviewer prompt, the nine checks, and scanner install and network notes. Read
  before the checklist review and when a scanner stops the run.
