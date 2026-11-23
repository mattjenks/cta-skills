---
name: create-skill
description: Use whenever a skill is written, created, changed, split, refactored or evaluated, in any repository: "write a skill", "turn this prompt into a skill", "edit this SKILL.md", "split a bloated skill", "my skill does not trigger", "add evals". Sets the budgets, eval layout and model map every skill must meet, and the CTA house rules for placement and naming.
argument-hint: "[create <name> | refactor <path/to/SKILL.md>]"
---

<!-- Adapted from coleam00/skills .claude/skills/skills-create/SKILL.md (MIT), and obra/superpowers skills/writing-skills/SKILL.md (MIT) -->

# Create Skill

Author, change or refactor a Claude Code skill, in a CTA plugin or anywhere else. A skill is a `SKILL.md` plus
optional files the assistant loads only when it reaches for them. This skill is its own worked example: a lean
body, detail in `references/standards.md`. The method follows Anthropic's `skill-creator` (draft, write eval
cases, run with and without the skill, tune the description); the budgets below are enforced by test.

## Budgets (enforced by `tests/test_skill_budgets.py`)

| What | Limit |
|---|---|
| Frontmatter `description` | 400 characters at most; says what the skill does and when to use it, a little pushy |
| `SKILL.md` | 150 lines at most; the procedure only |
| Each `references/*.md` | 300 lines at most; every file named from `SKILL.md` with when to read it |
| `evals/` | 2 or more case folders per skill, in the layout `claude plugin eval` reads |
| Deterministic work | `scripts/`, run and never read into context |
| Dispatching an agent | names the model (haiku or sonnet; the most capable only for secure, review and fix rounds) and links `models.md` |

## House rules (all mandatory)

1. **Placement.** The skill goes in a CTA plugin, at `plugins/<plugin>/skills/<name>/SKILL.md`. Never in
   `~/.claude/skills` or a project's `.claude/skills`; a skill outside a plugin is not versioned, shared or
   audited. Outside cta-skills, still apply the budgets and the eval layout.
2. **Versions and changelog.** Use a conventional commit (`feat(core): ...`). release-please owns the plugin
   version in both manifests and the `CHANGELOG.md`; never hand-edit them.
3. **No personal data.** No emails, home-directory paths, private repository names or persona names other than
   `default` and `CTA`. Examples use neutral names such as "Ada". `tests/test_manifests.py::test_no_personal_data`
   enforces this. Say "the assistant", never a persona name.
4. **The description says what and when.** It is the only text loaded before the skill triggers. Name the
   literal phrases, symptoms and situations that should fire it, in third person, and never summarize the
   workflow (the assistant follows a summary instead of reading the body).
5. **Name for telemetry.** The directory name is `skill.name` in telemetry and the `/<plugin>:<name>` command.
   Kebab-case, no plugin prefix, at most 64 characters, and the frontmatter `name` equals the directory name.
6. **Hooks have subprocess tests.** A skill that ships or tells the user to write a hook requires block and allow
   tests run through a subprocess; see the `create-hook` skill.
7. **Source line for adapted work.** A file adapted from another project starts with
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
`CLAUDE.md`), or for a mechanical constraint a regex, linter or hook can enforce. A hook guarantees; a skill guides.

### 2. Gather context

Ask the user, most important first, and do not write yet: the literal phrases that should trigger the skill
(three to six), the task start to finish and the end artifact, the gotchas a fresh assistant would get wrong, and
the scope boundary. One skill is one capability; two unrelated capabilities are two skills.

### 3. Draft the spine

1. Classify the skill (workflow, artifact generator, reference, tool wrapper) and decide where each part lives:
   inline if needed on every run, `references/` for occasional detail, `scripts/` for deterministic code.
2. Create `plugins/<plugin>/skills/<name>/SKILL.md` with `name` and `description` frontmatter. Count the
   description (400 characters at most) before moving on.
3. Write the body in the imperative, as decision logic only, explaining why a step matters rather than shouting
   MUST. Put a one-line pointer wherever a step needs bulk detail, naming the file and when to read it.
4. Match the form to the failure the assistant shows without the skill (see `references/standards.md`).

### 4. Write 2 to 3 eval cases

Write the cases before polishing the body: each is a realistic prompt a user would type, plus graders that state
verifiable results. Layout, grader format and the commands are in `references/evals.md`; read it before writing
the first case. Cover the main task and one near-miss or pressure case.

### 5. Run with and without the skill

Run each case once with the skill and once without (`claude plugin eval`, locally, never in CI: it bills real
model runs). A case that passes without the skill tests nothing; sharpen it or the skill. Fix failures by
tightening the wording, then re-run only the failed cases. Record the pass rates in the commit or report.

### 6. Tune the description

Write three prompts that should trigger the skill and three near-misses that should not, and check the skill
fires on the first set only. Fix the description, not the body, when it misfires.

### 7. Fill the resources, then ship

Write the planned `references/` and `scripts/`, removing from the body anything that moved. Invoke bundled scripts
through their interpreter in prose (`bash scripts/x.sh`, `uv run scripts/x.py`), never by bare path.

### 8. Checklist (run last)

- [ ] Every file linked from the body exists; nothing duplicated between body and references.
- [ ] Budgets and evals pass: `uv run --with pytest pytest tests/test_skill_budgets.py -q` in cta-skills, or for
  a skill anywhere else `uv run --script "${CLAUDE_PLUGIN_ROOT}/skills/create-skill/scripts/check_skill.py" <skill-dir>`.
- [ ] `uv run --with pytest pytest tests/test_manifests.py -q` passes (frontmatter, no personal data).
- [ ] Eval pass rates with and without the skill are recorded.
- [ ] Reviewed through `build:review`, which flags any `SKILL.md` that is over budget or lacks evals.

## R. Refactor a bloated skill

1. Inventory the body: mark each block as spine (keep) or extractable (long examples, schemas, tables, exhaustive lists).
2. Move extractable blocks verbatim into `references/`; do not reword anything that affects behavior. Lose no
   instruction.
3. Replace each with a pointer naming the file and when to read it. For content needed on every run (such as a
   required output shape), use a mandatory-read line ("Before producing output, read `references/x.md`").
4. Confirm behavior is preserved: same process, same output, nothing lost, nothing duplicated; then run step 8.

## Resources

- `references/standards.md`: frontmatter fields, progressive disclosure, voice, wiring, skill types, matching the
  form to the failure, anti-patterns, the model map rule. Read before drafting the spine.
- `references/evals.md`: eval case layout, grader format, running `claude plugin eval` with and without the skill.
  Read before writing the first case.
- `scripts/check_skill.py`: the budget checks as a standalone script. Run it, do not read it.
