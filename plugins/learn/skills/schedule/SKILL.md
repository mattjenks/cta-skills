---
name: schedule
description: Sets up the weekly learn report as a Claude desktop scheduled task that builds and emails the report every Monday at 07:00. Use to schedule or reschedule the weekly report ("schedule the report", "set up the weekly run"); safe to run again, it updates the existing task.
---

# Schedule

Create or update one desktop scheduled task, `cta-weekly-report`, cron `0 7 * * 1` (Mondays 07:00, local
time). Each run builds the report with `/learn:report` and sends it with `/learn:deliver`.

## 1. Check the tools

You need the desktop app's scheduled-tasks tools: `list_scheduled_tasks`, `create_scheduled_task`,
`update_scheduled_task` and `run_scheduled_task` (the `mcp__scheduled-tasks__` tools). If they are not
loaded, look for them in the deferred tool list and load them. If they are not there, say the schedule
needs the Claude desktop app and stop. Do not try another scheduler.

## 2. Read the prompt

Read `${CLAUDE_PLUGIN_ROOT}/skills/schedule/references/task-prompt.md`. Pass its content as the task's
`prompt` verbatim: do not paraphrase, shorten or add to it. Each run starts fresh, so the file is the
whole instruction.

## 3. List, then update or create

Call `list_scheduled_tasks` first.

- `cta-weekly-report` is in the list: call `update_scheduled_task` with `taskId: cta-weekly-report`, the
  `prompt`, `cronExpression: 0 7 * * 1` and `enabled: true`.
- It is not in the list: call `create_scheduled_task` with `taskId: cta-weekly-report`, the `prompt`,
  `cronExpression: 0 7 * * 1`, a one-line `description` and the title "CTA weekly report".

Never create a second task. If a create is refused because the ID is taken and suggests `cta-weekly-report-2`
or any other ID, do not take the suggestion: list again and update the existing task.

## 4. Tell the owner

One short message: the task ID, the schedule (Mondays 07:00, local time), whether it was created or
updated, and that a run missed while the app is closed happens at next launch (the app also adds a small
dispatch delay).

## 5. Offer one test run

Ask whether to run it once now to test delivery. Call `run_scheduled_task` with `taskId:
cta-weekly-report` only after the owner says yes, and only once. It starts a new session; say so and that
the result will be in that session. If the answer is no, finish.
