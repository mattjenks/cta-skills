---
tags: [fix-issue]
max_turns: 6
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Use the build plugin's fix-issue skill on issue 42 (CSV export drops the last row; probably a one-line change in export.py). Give the exact gh command you run to read it, the next skill you invoke and what it must produce before any fix, the numeric rule you use to classify small versus normal, which skill you then run, and what line goes in the design and PR body. You cannot run commands or edit files here, so answer in prose. Do not ask me questions first.
