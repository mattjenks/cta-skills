<!-- Adapted from coleam00/skills .claude/skills/skills-create/references/skill-standards.md (MIT), and obra/superpowers skills/writing-skills/SKILL.md (MIT) -->

# Skill Standards

The craft rules every CTA skill obeys. They govern how a skill is built, never what it says: the sections of a
plan, the domain vocabulary and the output shape are the author's call.

## Skill types

| Type | What it is | Apply |
|---|---|---|
| Workflow | A multi-step procedure (plan, review, ship) | Full craft rules plus verifiable gates |
| Artifact generator | Produces a document or output | Dense context plus a suggested, never mandated, output shape |
| Reference | Facts the assistant consults | Dense context; no phases, no validation loop |
| Tool wrapper | Drives a script, CLI or API | A deterministic script plus sharp triggers; validation is the tool's exit status |

A skill can blend types; apply the union. Never impose a workflow's phases or loops on a reference skill.

## Anatomy

```text
skill-name/
  SKILL.md        required: YAML frontmatter plus markdown body
  references/     docs the assistant reads on demand
  templates/      shapes the output follows
  scripts/        code that is run, not read
```

Keep inline: principles, and code patterns under about 50 lines. Split out: heavy reference (100 or more
lines) and reusable tools. One excellent, runnable example beats several mediocre ones; do not write the same
example in five languages.

## Frontmatter

| Field | Required | Constraint |
|---|---|---|
| `name` | yes | At most 64 characters, lowercase letters, digits and hyphens, equal to the directory name, no plugin prefix |
| `description` | yes | At most 400 characters (test-enforced), third person, says what the skill does and when to use it |
| `argument-hint` | no | Autocomplete hint, such as `<path> [--base <branch>]` |
| `allowed-tools` | no | Tools usable without a prompt while the skill is active |
| `disable-model-invocation` | no | `true` makes the skill user-only |
| `user-invocable` | no | `false` hides it from `/` and leaves it to the assistant |

Invocation control is a deliberate decision. A skill distributed in a plugin that performs a side effect
(commit, push, delete, deploy) sets `disable-model-invocation: true`, so another user's assistant cannot fire it
unprompted. Read and plan skills stay open. Other fields exist (`model`, `effort`, `paths`, `hooks`,
`context: fork`); confirm any of them against the current Claude Code skills documentation before use.

## Descriptions

The description is a trigger, not a summary, and Claude tends to under-trigger, so make it a little pushy: name
concrete situations, symptoms, error messages and literal user phrases, and stay in third person. It says what the
skill does and when to use it, in 400 characters or fewer.

- Good: `Use when tests pass in isolation but fail in the suite, or a test leaves files behind.`
- Bad: `Helps with testing.` (vague) and `Use when ... runs a four-step process of X, Y, Z.` (summarizes the workflow, so the assistant follows the summary and skips the body)

Put the searchable words (tool names, error text, synonyms) early and repeat them where natural in the body.

## Progressive disclosure

1. Metadata (`name` and `description`) is always in context. Keep it small.
2. The body loads when the skill triggers. It is the procedure only: 150 lines at most, test-enforced.
3. Resources load only when the assistant reaches for them. Scripts cost almost nothing, since only their
   output enters the conversation.

Each `references/*.md` is 300 lines at most and is named from the body with when to read it. Frequently loaded
skills deserve the tightest bodies. Cut anything the assistant already knows, point to a
`--help` instead of documenting flags, and cross-reference other skills by name rather than repeating them.

## Voice

The description is third person. The body is imperative: "Validate the output before reporting", not "You should
validate". Refer to "the assistant", never to a persona name.

## No duplication

A fact lives in exactly one place, in the body or in a reference. Duplicates drift.

## Stateful sections need a maintainer

If a skill's output carries status markers, a progress checklist or a "last modified" field, a named step or a
companion skill must keep it current. Never template a stateful section that nothing updates.

## Wiring

Link every bundled file from the body, ending it with a Resources list that says when to read each file.
Keep references one level deep, linked directly from `SKILL.md`. Every cited path and URL must resolve.
Make scripts self-contained (inline dependency metadata for Python) and derive the project root from the working
directory or `git rev-parse --show-toplevel`, never from the script's own location, because the script ships in a
plugin but operates on the user's project.

## Matching the form to the failure

Classify the baseline failure before choosing the wording.

| Baseline failure | Right form | Wrong form |
|---|---|---|
| Breaks a rule under pressure while knowing better | Prohibition, rationalization table, red-flags list | Soft guidance ("prefer", "consider") |
| Complies but the output has the wrong shape | A positive recipe stating what the output is, in order | A list of prohibitions |
| Omits a required element | A required slot in a template | A prose reminder near the template |
| Behavior depends on a condition | A conditional on an observable predicate | An unconditional rule with exemption clauses |

Express a real exception as its own conditional. A "unless it matters" clause reopens the negotiation, and an
exemption clause does not scope the rule it exempts.

For discipline failures, close loopholes explicitly: state the spirit of the rule alongside the letter, record
each rationalization the baseline produced in a two-column table with its rebuttal, and list the red-flag
thoughts that mean stop.

## Testing a skill

A skill is code for the assistant, so test it before deploying.

- **Discipline skills** (rules and requirements): pressure scenarios that combine time pressure, sunk cost and
  authority; success is compliance under maximum pressure.
- **Technique skills** (how-to): application and variation scenarios; success is applying the technique to an
  unseen case.
- **Pattern skills** (mental models): recognition and counter-example scenarios.
- **Reference skills**: retrieval and gap scenarios.

Micro-test wording before a full run: one fresh-context sample per call, a no-guidance control (if the control
does not fail, there is nothing to fix), five or more repetitions per variant, and a manual read of every flagged
result. Variance is a signal: five different interpretations mean the wording is not binding.

## Models for dispatched agents

A skill that dispatches an agent names the model in the dispatch (haiku for exact-code or one-to-two-file work
and chores, sonnet for the default builder and per-task reviewer) and links the model map,
`plugins/build/skills/implement/references/models.md`. The most capable model is reserved for the secure
checklist review, the final review and fix rounds 4 to 5; `test_opus_only_in_allowed_roles` keeps it out of
other skills.

## Anti-patterns

- A narrative about how a problem was solved once. Skills are reusable techniques, not stories.
- Code in flowcharts, or generic labels such as `step3` and `helper1`.
- A skill batch: write, test and ship each skill before starting the next.
- A skill with no baseline failure behind it (a case that passes without the skill tests nothing).
- A dispatch that does not name its model.

## Done checklist

- [ ] Directory in a CTA plugin; `name` equals the directory; kebab-case; no plugin prefix.
- [ ] Description is at most 400 characters, says what and when, names concrete triggers, does not summarize the workflow.
- [ ] Body at most 150 lines, references at most 300, imperative, no duplication, every bundled file linked with when to read it.
- [ ] At least 2 eval cases under `evals/`, run with and without the skill, pass rates recorded (`references/evals.md`).
- [ ] `tests/test_skill_budgets.py` passes, or `scripts/check_skill.py` on a skill outside this repo.
- [ ] No personal data; no persona names; source line on adapted files.
- [ ] Conventional commit; versions and changelog left to release-please.
