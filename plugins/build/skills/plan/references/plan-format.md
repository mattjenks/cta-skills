<!-- Adapted from obra/superpowers skills/writing-plans/SKILL.md (MIT) -->
<!-- Adapted from coleam00/skills .claude/skills/piv-plan-implementation/SKILL.md (MIT) -->

# Plan format

Read before writing `plan.md`. The plan argues from the design, so the design travels with it.

## Header (every plan starts with this)

```markdown
# <Feature> Implementation Plan

> **For agentic workers:** run with `/build:implement`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** one sentence.
**Architecture:** two or three sentences on the approach.
**Tech stack:** key technologies and libraries, with versions.
**Spec:** path to the design this implements.

## Global Constraints

The design's project-wide requirements (version floors, dependency limits, naming and copy rules, platform
requirements), one line each, exact values verbatim. Every task includes this section implicitly.

## Review Focus

Five input classes or failure modes the design implies but no task's tests exercise, most likely to bite a
person using the software first, one line each: the input or condition and the behavior a reasonable person
expects. The design's silence on an input is not permission for it to break. For each line, add the test that
pins it to the task that owns the code. An empty section means you checked and found none.

## Out of scope

What a reasonable reader might assume is included but is not (and what must not change).

---
```

## Task shape

````markdown
### Task N: <component>

**Files:**
- Create: `exact/path.py`
- Modify: `exact/existing.py:123-145`
- Test: `tests/exact/test_path.py`

**Interfaces:**
- Consumes: what this task uses from earlier tasks, exact signatures.
- Produces: what later tasks rely on, exact names, parameter and return types. An implementer sees only
  their own task; this block is how they learn the neighbors' names and types.

- [ ] **Step 1: write the failing test** (name and assertions as code, the design's exact values in them)
- [ ] **Step 2: run it, expect FAIL** (`<exact command>`, expected failure text)
- [ ] **Step 3: implement `name(args) -> Return` in `path.py`** (one line of approach when a choice is left)
- [ ] **Step 4: run it, expect PASS**
- [ ] **Step 5: commit** (`feat(<scope>): <summary>`)
````

Optional per-task lines where they help: `PATTERN:` (file and line to mirror), `GOTCHA:` (a known trap),
`SATISFIES:` (which requirement or acceptance criterion the task advances), `Depends on:` when order is not
simply top to bottom.

## What a step contains

A step is done when the implementer can write exactly one reasonable thing from it, and nothing more:

- **Test step:** the test's name and assertions as code, with the design's exact values.
- **Code step:** the exact signature, the file, and the specific values the design pins. A body appears only for
  an algorithm the signature and tests do not determine, or for exact copy the design fixes.
- **Verification step:** the command and the output that means it passed. Non-interactive commands only.
- **Reference to another task:** that task's Interfaces block says what to use; do not repeat its code.

Lines that decide nothing ("TBD", "handle edge cases", "write tests for the above", a type no task defines)
and function bodies the signature and tests already determine are both failures.

## Task sizing

A task is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate. Fold setup,
configuration and documentation into the task whose deliverable needs them. Each task ends with an
independently testable deliverable and a commit.

## Closing sections

- **Production dependencies:** each new one with name, version, license, reason (verified by the owner before
  approval), or the line "none".
- **Validation commands:** the repo's lint, type, unit and integration commands, exactly as run.
- **Open questions and assumptions:** every `Assumed:` line and any question that would change the plan.
- **Amendments:** append-only dated list of changes after approval; empty at creation.
