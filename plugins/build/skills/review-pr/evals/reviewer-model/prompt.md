---
tags: [review-pr]
max_turns: 6
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Use the build plugin's review-pr skill on PR 7. Which model does the reviewer subagent run on, which reference file holds its prompt, what severities and fields does it output, and what do you do with a finding that you cannot tie to a line of the diff? You cannot run commands or edit files here, so answer in prose. Do not ask me questions first.
