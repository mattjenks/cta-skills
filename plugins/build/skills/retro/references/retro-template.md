# Retro template

## retro.md

```markdown
# Retro: <topic>

Date, slug, size (small or normal), branch, PR links.

## Plan vs actual
Tasks planned, done, added, dropped. Where the estimate was wrong and why.

## Corrections
What the owner corrected or overruled during the build, and what would have avoided each.

## Slow steps
Steps that took longest or looped (tool failures, rework, waiting), with the cause.

## Review findings
| Severity | Count | Categories |
| Critical | | |
| Important | | |
| Minor | | |
Categories: correctness, tests, spec fit, security, maintainability, docs. Counts come from the ledger
and `security.json`; say which source each number came from.

## Fix rounds
Per task: rounds used, escalated to a stronger model, any task that ended `blocked`.

## Gates fired
Which gates stopped or blocked work: commit gate, scanner stop, dependency stop, owner closures.

## Next time
Two or three concrete changes to the process, skills or plan format.

## Rating
The owner's 1 to 5 and their line, or "declined".
```

## Event fields (`retro-fields.json`)

```json
{"slug": "app", "topic": "login", "size": "normal", "tasks": 4, "fix_rounds": 2,
 "findings_critical": 0, "findings_important": 1, "findings_minor": 3,
 "gates": ["secure", "dependency-stop"], "rating": 4}
```

`size` is `small` or `normal`. Counts are non-negative integers; `fix_rounds` totals every task. `gates` lists
the gates that fired (empty list for none). `rating` is 1 to 5, or `null` when the owner declined.
