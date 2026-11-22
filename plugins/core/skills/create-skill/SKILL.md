---
name: create-skill
description: Use when asked to create a new skill, write a skill, turn a repeated prompt or command into a skill, split a bloated SKILL.md into references, or improve a skill that does not trigger. Covers authoring skills for a CTA plugin, including the house rules for placement, versioning and naming.
argument-hint: "[create <name> | refactor <path/to/SKILL.md>]"
---

<!-- Adapted from coleam00/skills .claude/skills/skills-create/SKILL.md (MIT), and obra/superpowers skills/writing-skills/SKILL.md (MIT) -->

# Create Skill

Author or refactor a Claude Code skill for a CTA plugin. A skill is a `SKILL.md` plus optional files the
assistant loads only when it reaches for them. This skill is its own worked example: a lean body, detail in
`references/standards.md`.

## House rules (all mandatory)

1. **Placement.** The skill goes in a CTA plugin, at `plugins/<plugin>/skills/<name>/SKILL.md`. Never in
   `~/.claude/skills` or a project's `.claude/skills`; a skill outside a plugin is not versioned, shared or
   audited.
2. **Version bump and changelog.** In the same commit as the skill, bump the plugin version in BOTH
   `plugins/<plugin>/.claude-plugin/plugin.json` and its entry in `.claude-plugin/marketplace.json`, and add a
   `## <version> — <summary>` heading with a line for the skill to the plugin's `CHANGELOG.md`.
3. **No personal data.** No emails, home-directory paths, private repository names or persona names other than
   `default` and `CTA`. Examples use neutral names such as "Ada". `tests/test_manifests.py::test_no_personal_data`
   enforces this. Say "the assistant", never a persona name.
4. **The description says when to use the skill.** It is the only text loaded before the skill triggers, so it
   decides whether the skill ever runs. Start with "Use when", list concrete triggers and symptoms, write it in
   third person, and never summarize the workflow (the assistant follows a summary instead of reading the body).
5. **Name for telemetry.** The directory name becomes `skill.name` in telemetry and the `/<plugin>:<name>`
   command. Use kebab-case, no plugin prefix (`create-skill`, not `core-create-skill`), at most 64 characters, and
   make the frontmatter `name` equal the directory name.
6. **Hooks have subprocess tests.** A skill that ships or tells the user to write a hook requires block and allow
   tests run through a subprocess; see the `create-hook` skill.
7. **Frontmatter and size limits.** `description` is at most 1,024 characters and the `SKILL.md` body at most 500
   lines. `tests/test_manifests.py::test_skill_frontmatter` enforces both.
8. **Source line for adapted work.** A file adapted from another project starts with
   `<!-- Adapted from <repo> <path> (MIT) -->` right after the frontmatter, and the source is credited in the
   repository's `NOTICE`.

## Workflow

### 0. Pick the mode from `$ARGUMENTS`

- `create [<name>]`, or clearly a new-skill request: create mode.
- `refactor <path>`, or a path to an existing skill: refactor mode (step R below).
- Blank or unclear: ask which mode and which skill. Do not guess.

### 1. Establish that a skill is warranted

Build a skill when the technique was not obvious, will be reused across projects, and the assistant would
otherwise get it wrong. Do not build one for a one-off, for a project convention (put it in that project's
`CLAUDE.md`), or for a mechanical constraint a regex, linter or hook can enforce (automate it; keep skills for
judgment calls). A hook guarantees; a skill guides.

### 2. Baseline first

A skill is untested documentation until the assistant has been seen to fail without it. Before writing:

1. Run the target scenario in a fresh session WITHOUT the skill and record, verbatim, what the assistant does
   wrong and the rationalizations it gives.
2. Write the minimal skill that addresses exactly those failures.
3. Run the same scenario WITH the skill. If it still fails, tighten the wording and re-run.

Editing an existing skill follows the same loop. Skip the baseline only for pure reference skills (command
tables, API facts), and then test retrieval: ask a question the skill answers and confirm it loads.

### 3. Gather context

Ask the user, most important first, and do not write yet:

- The literal phrases that should trigger the skill (three to six).
- The task start to finish and the end artifact.
- The gotchas: what a fresh assistant would get wrong, and the existing patterns in the repository to mirror.
- The scope boundary. One skill is one capability; two unrelated capabilities are two skills.

### 4. Classify and plan resources

Pick the type: **workflow** (multi-step procedure), **artifact generator** (produces a document),
**reference** (facts the assistant consults) or **tool wrapper** (drives a script). Apply only the machinery
that fits; never put phases or validation loops in a reference skill. Then decide where each part lives: inline
if needed on every run, `references/` if it informs occasional work, `scripts/` if it is deterministic code to
run rather than read, a cited path or URL if another project owns it. Details in `references/standards.md`.

### 5. Write the spine

1. Create `plugins/<plugin>/skills/<name>/SKILL.md` with `name` and `description` frontmatter.
2. Write the body in the imperative, as decision logic and workflow only, with a one-line pointer wherever
   a step needs bulk detail.
3. Match the form to the failure seen in the baseline: a rule the assistant breaks under pressure gets a
   prohibition plus a rationalization table; a wrong output shape gets a positive recipe; a missing element gets a
   required slot in a template.
4. End with a Resources list naming every bundled file and when to read it.

Get the spine triggering before writing any reference.

### 6. Fill the resources, then ship

Write the planned `references/` and `scripts/`, removing from the body anything that moved. Invoke bundled
scripts through their interpreter in prose (`bash scripts/x.sh`, `uv run scripts/x.py`), never by bare path,
because some packagers strip executable bits. Then apply house rule 2: version bump in both manifests and a
changelog line, in the same commit.

### 7. Validate

Run these and fix failures before declaring done:

```bash
uv run --with pytest pytest tests/test_manifests.py -q
```

Then check by hand: every file linked from the body exists; no content is duplicated between body and
references; the description triggers on a task phrased the way the user would phrase it (start a fresh session
and try it); the skill was exercised on real work once.

## R. Refactor a bloated skill

1. Inventory the body: mark each block as spine (keep) or extractable (long examples, schemas, exhaustive lists).
2. Move extractable blocks verbatim into `references/`; do not reword anything that affects behavior.
3. Replace each with a pointer. For content needed on every run (such as a required output shape), use a
   mandatory-read line ("Before producing output, read `references/x.md`"). Moving an always-needed format behind
   a lazy pointer is the main refactor risk, because the assistant forgets to read it and output silently
   changes.
4. Confirm behavior is preserved: same process, same output, nothing lost, nothing duplicated.

## Resources

- `references/standards.md`: frontmatter fields, progressive disclosure budgets, voice, wiring, skill types,
  anti-patterns and the baseline-testing method. Read before writing the spine.
