---
name: fix-issue
description: Fixes a GitHub issue end to end - reads the issue, finds the root cause with /build:debug, classifies the work as small or normal and runs the build loop. Use when asked to "fix issue 42", "work on this issue" or given an issue number or URL.
argument-hint: "<issue-number-or-url>"
---

<!-- Adapted from coleam00/skills .claude/skills/piv-fix-github-issue/SKILL.md (MIT) -->

# Fix issue

A GitHub issue becomes a build: understand it, find the cause, then take the same path as any change.

## Steps

1. **Read.** `gh issue view <issue> --comments --json number,title,body,labels,state,url`. A closed issue or
   one that is a question rather than a defect: say so and ask the owner. Quote the reproduction steps and the
   expected behavior; if they are missing, ask the reporter's questions of the owner once, in one message.
2. **Find the cause.** Run `/build:debug` with the issue as the symptom. It ends at a stated root cause and a
   failing test, and writes no fix.
3. **Classify** the fix by the loop's rule: **small** is 5 files or fewer changed, no new production
   dependency, and no path matching auth, secrets, hooks or CI; anything else is **normal**. Say which and
   why; the owner can override.
4. **Run the loop.** `/build:loop` with the issue, the root cause and the failing test as the request,
   passing the classification so the design stays short. The design names the issue (`Fixes #<n>`), and the
   PR body carries the same line so the issue closes on the owner's merge.
5. **Report** the issue, the cause, the PR links, and anything the issue asked for that was left out.

Never close or comment on the issue yourself; posting to a public issue needs the owner's yes.
