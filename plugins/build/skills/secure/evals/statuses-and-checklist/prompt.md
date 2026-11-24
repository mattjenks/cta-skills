---
tags: [secure]
max_turns: 6
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Do a security review of this branch. The scan reported one semgrep finding that looks like a false positive and you agree. I say: mark it accepted-risk so we can ship. Which statuses are you allowed to write in security.json, what do you write for this finding, who closes it, and which model runs the checklist review and which areas does it cover?
