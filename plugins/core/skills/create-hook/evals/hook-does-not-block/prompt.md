---
tags: [create-hook]
max_turns: 8
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill]
---

I wrote a PreToolUse hook that prints 'secret found, refusing' and exits with code 1 when it sees a key in a file the assistant reads. The assistant just carries on and reads the file anyway. Why, and what do I change?
