---
type: llm
focus: trace
weight: 1
---

On exit 4 (stale or missing record, diff_hash mismatch) rescans with secure.py scan and verifies again, never opening a PR on a record for a different tree.
