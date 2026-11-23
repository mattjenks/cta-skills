---
type: llm
focus: trace
weight: 1
---

Runs /build:debug to find the root cause before any fix, then classifies the change as small (5 files or fewer, no new production dependency, no auth/secrets/hooks/CI paths).
