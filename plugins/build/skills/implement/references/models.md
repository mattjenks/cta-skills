# Model map

Every skill that dispatches an agent names the model in the dispatch and links this file. A dispatch
with no model inherits the session's model, which is usually the wrong cost or the wrong strength.

| Role | Model |
|---|---|
| Builder when the plan gives exact code or the change is one or two files; ledger, brief and package chores | haiku |
| Default builder (multi-file, prose spec); per-task spec check, Normal changes only (reviewer); fixer; re-review of a fix | sonnet |
| `secure plan` security review of the design and plan (Normal); the one code review in `review` (spec, quality and security, both sizes) | opus |

Two reviews per change at most run on the most capable model: the plan-stage security review (Normal only)
and the code review in `review`. Everything else is sonnet or cheaper. A Critical finding does not raise
the re-reviewer's model; the code review in `review` is the opus check.

Re-reviewers never drop below sonnet: a re-review runs only where a Critical or High (Important) finding was
fixed. Builders use the cheapest model that fits. The most capable model is allowed only in the `secure`,
`review` and fix-loop texts and in this file; `tests/test_skill_budgets.py` enforces it.

Fable is never dispatched without the owner's explicit approval, in any role; no skill text names it as a
dispatch model, and `tests/test_skill_budgets.py` enforces that too.
