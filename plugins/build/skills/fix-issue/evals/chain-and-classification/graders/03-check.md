---
type: llm
focus: trace
weight: 1
---

Classifies small as 5 files or fewer (tests and docs not counted), no new production dependency, and no change to a security boundary, then runs /build:loop and puts `Fixes #42` in the design and PR body.
