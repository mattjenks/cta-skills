---
tags: [create-hook]
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit]
---

I want a guarantee that the assistant can never edit anything under db/migrations/. Build the hook in plugins/tools and add tests. Don't ask me questions, just make reasonable choices.
