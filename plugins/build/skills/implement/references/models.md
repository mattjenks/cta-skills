# Model map

Every skill that dispatches an agent names the model in the dispatch and links this file. A dispatch
with no model inherits the session's model, which is usually the wrong cost or the wrong strength.

| Role | Model |
|---|---|
| Builder when the plan gives exact code or the change is one or two files; ledger, brief and package chores | haiku |
| Default builder (multi-file, prose spec); per-task reviewer (default); re-review of a fix (floor: the reviewer's tier); design builder check; `retro`; `debug` investigation | sonnet |
| `secure` checklist review; final whole-branch review; re-review after a Critical finding from a sonnet reviewer; fix rounds 4 and 5 | opus |

Reviews default to sonnet, including tasks in sensitive paths (spec decision 13);
the most capable model is for the final whole-branch review, the `secure` checklist review, re-reviews where
a sonnet reviewer found a Critical issue, and fix rounds 4 and 5, on a fresh agent.

Re-reviewers never drop below sonnet: a re-review runs exactly where a Critical or Important issue was
found. Builders use the cheapest model that fits; reviewers use mid-tier at minimum. The most capable model is
allowed only in the `secure`, `review` and fix-loop texts and in this file; `tests/test_skill_budgets.py`
enforces it.

Fable is never dispatched without the owner's explicit approval, in any role; no skill text names it as a
dispatch model, and `tests/test_skill_budgets.py` enforces that too.
