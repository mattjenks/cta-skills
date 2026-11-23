# Projects

A project is work with an outcome. Each project is a folder, `projects/<slug>/`, holding:

| File | Purpose |
|---|---|
| `design.md` | What is being built and why: goals, approach, decisions, what is out of scope |
| `reqs.md` | One row per requirement, with an id, the requirement and its status |
| `plan.md` | The ordered steps to deliver the design, small enough to review one at a time |
| `backlog.md` | Ideas and follow-ups that are not part of the current plan |
| `builds/<YYYY-MM-DD>-<topic>/` | One folder per build run, described below |

A new requirement is a row in `reqs.md`, added in the same commit as the work that meets it.

## Build folders

Each `builds/<YYYY-MM-DD>-<topic>/` folder holds the record of one build run:

| File | Purpose |
|---|---|
| `progress.md` | Where the run stands: steps done, in flight and blocked |
| `security.json` | Security findings with a status for each: `open`, `fixed`, `proposed-false-positive`, `false-positive` or `accepted-risk`. Only the owner closes a finding as `false-positive` or `accepted-risk` |
| `retro.md` | What went well, what did not, and what to change next time |

## Conventions

- Use lowercase, hyphenated slugs for project folders.
- Link each project from the area it touches.
- Finished projects stay in place with their status noted at the top of `design.md`.
