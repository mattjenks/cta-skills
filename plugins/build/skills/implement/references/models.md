# Model map

Every skill that dispatches an agent names the model in the dispatch and links this file. A dispatch
with no model inherits the session's model, which is usually the wrong cost or the wrong strength.

| Role | Model |
|---|---|
| Builder when the plan gives exact code or the change is one or two files; ledger, brief and package chores; re-review of a small fix diff | haiku |
| Default builder (multi-file, prose spec); per-task reviewer; design builder check; `retro`; `debug` investigation | sonnet |
| `secure` checklist review; final whole-branch review; fix rounds 4–5; review of tasks that touch hooks, guards, auth or secrets | opus |

Builders use the cheapest model that fits; reviewers use mid-tier at minimum. The most capable model is
allowed only in the `secure`, `review` and fix-loop texts and in this file; `tests/test_skill_budgets.py`
enforces it.
