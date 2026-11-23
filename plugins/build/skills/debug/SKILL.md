---
name: debug
description: Finds the root cause of a bug, failing test or unexpected behavior before any fix - reproduce, gather evidence, form and test one hypothesis at a time, then hand a failing test to the fix. Use when something is broken, a test fails for no clear reason, or when asked to "debug", "figure out why" or "find the root cause".
argument-hint: "<symptom, error or issue>"
---

<!-- Adapted from obra/superpowers skills/systematic-debugging/SKILL.md (MIT); method, not copied prose. -->

# Debug

Understand the failure before touching code. A fix without a known cause moves the bug. No fix is proposed or
written until section 4 names the root cause with evidence. Model map: `../implement/references/models.md`.

## 1. Reproduce

State the symptom exactly: the command, input and output, what was expected. Run it and see it fail. A bug
you cannot reproduce gets more evidence (logs, versions, environment, recent `git log`), not a guess. If it is
intermittent, find what varies. Say so when you still cannot reproduce it, and stop there.

## 2. Gather evidence

Read the full error and stack trace, not the last line. Check what changed recently (`git log -10`,
`git diff`). Find a working case of the same thing and list how it differs from the broken one. In a multi-part
system, add a temporary print or log at each boundary and run once to see which stage first goes wrong. Trace
a bad value back to where it first became bad, not where it was noticed.

For a wide search across many files or a long log, dispatch one investigator subagent on sonnet (model map:
`../implement/references/models.md`) with the symptom and the paths to read, asking for evidence and
candidate causes, not a fix.

## 3. Hypothesize and test

Write one hypothesis: "X is the cause because Y". Test it with the smallest change or probe that would
disprove it, changing one thing at a time. Wrong: record that it is ruled out, form the next hypothesis from
what you learned, and do not stack fixes. After three failed hypotheses, stop and question the design or
ask the owner; more patches will not help.

## 4. Root cause

State the root cause in a sentence with the evidence that proves it (the probe that confirmed it and the one
that would have refuted it). Remove the temporary probes.

## 5. Hand off to the fix

1. Write the failing test that reproduces the bug at the level it occurs, and see it fail for the stated
   reason.
2. Fix at the cause, with the smallest change. See the test pass, then run the suite (`/build:validate`).
3. Commit with `/build:commit`: `fix(<scope>): ...` naming the cause. If the fix touches more than the cause
   needs, or a test cannot cover it, say so to the owner first.

Report: symptom, root cause, evidence, the test, the fix commit. Under `/build:fix-issue` or `/build:loop`,
return the root cause and the failing test as the design input instead of fixing past the build's gates.
