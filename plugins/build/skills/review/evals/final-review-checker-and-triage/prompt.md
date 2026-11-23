---
tags: [review]
max_turns: 6
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Do the final review of this branch before the PR (base main). The diff adds plugins/x/skills/foo/SKILL.md, and the ledger has two lines marked minor (deferred). You cannot run commands here, so walk me through the steps: which model does the final review, how you check the new SKILL.md and where that checker script lives relative to the build plugin, and what you do with the two deferred minors.
