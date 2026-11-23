---
name: init-kb
description: Use when the user wants to start a knowledge base, second brain or notes repo, says "init-kb" or "set up my KB", or when a build run finds no git-backed knowledge base. Creates the folder as a git repo with template documents, lint and secret-scan workflows, offers a private GitHub repo, and records `kb` in the CTA config.
argument-hint: "[target folder]"
---

# Init KB

Turns a folder into a git-backed knowledge base the other skills can read and write. The minimum
contract is a git repository; a remote is optional. Every command below is
`uv run --script "${CLAUDE_SKILL_DIR}/scripts/init_kb.py"`, called `init_kb.py` here. The script does
the file work and prints JSON; this skill holds the questions.

## Procedure

1. **Ask for the target folder** if the user has not named one. Suggest nothing personal; any path works.
   Expand `~` and use an absolute path from here on.
2. **Check it.** Run `init_kb.py check --target <dir>`. The state is `missing`, `empty` or `non-empty`.
   - `missing` or `empty`: continue.
   - `non-empty`: stop and refuse. Say what is in the way. Continue only if the user explicitly asks to
     merge into it, and confirm once more that existing files will be kept, never overwritten.
3. **Initialize.** Run `init_kb.py init --target <dir>`, adding `--merge` only after the user agreed to
   a merge. It runs `git init` when the folder is not already a repo, copies the templates, and skips
   any file that already exists. Report the `copied` and `skipped` lists.
4. **Record `kb`.** Run `init_kb.py config --target <dir>`. It writes `kb = "<path>"` as a top-level key
   in `~/.config/cta/config.toml` (or the file named by `CTA_CONFIG`) without touching other content.
   If it refuses because the file is not valid TOML or already points `kb` elsewhere, show the message
   and ask the user; do not edit the file by hand.
5. **Commit the starting point.** Show `git status` and ask before the first commit. Use a plain message
   such as `docs: initial knowledge base`.
6. **Offer a private remote.** Never create one unasked. Confirm first, naming the exact command and
   that it publishes the repository to the user's GitHub account: `gh repo create <name> --private
   --source <dir> --remote origin`. Run it only after a clear yes. Do not push until the user confirms
   that too. If they decline, say a remote is optional and stop.
7. **Hand over.** Tell the user which files to fill in first (`USER.md`, `SOUL.md`, `BOUNDARIES.md`),
   that `projects/README.md` states the project standard, and that the lint and secret-scan workflows
   only run once a remote exists.

## Rules

- Templates are skeletons with placeholders. Fill nothing in for the user and add no personal data.
- Never overwrite an existing file, and never delete one.
- Do not write to the user's config except through `init_kb.py config`.
- Detail on the templates and the workflows is in `references/templates.md`. Read it when the user asks
  what a file is for, or wants to change a workflow.
