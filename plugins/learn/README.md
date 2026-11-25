# learn

The CTA learn stage. It reads the local telemetry, writes a weekly report on how your skills
performed, and records your decision on each recommendation in it.

## Install

```text
/plugin marketplace add mattjenks/cta-skills
/plugin install learn@cta
```

## Requirements

- `uv` on your `PATH`; every script runs as `uv run --script`.
- `gh`, authenticated, to open the report PR and to file issues.
- `gitleaks`, for `learn:decide`: it scans an issue body before filing and refuses on a hit or when
  the scan cannot run.
- The telemetry stack from [`telemetry/README.md`](../../telemetry/README.md) running, so Prometheus
  and Loki have data. With the stack down the report is still written and says "No data".
- A knowledge base (`kb` in the CTA config) that is a git repo.
- The Claude desktop app, for `learn:schedule` only.

## Skills

| Skill | What it does |
|---|---|
| `learn:report` | Drafts the report from telemetry, writes the prose for each recommendation, renders markdown, HTML and JSON, and opens a knowledge-base PR. Takes an optional date. |
| `learn:decide` | Records accept, defer or reject for a recommendation ID such as `2026-11-23-R2`. Accept files a GitHub issue; a reject needs a reason and is remembered so the idea is not suggested again. Deciding the same ID twice shows the first decision and changes nothing. |
| `learn:deliver` | Emails the report to the configured address. With no mail tool connected, or on a failed send, it raises a notification that points at the markdown file. The result is recorded and the next report lists a fallback under Run errors. |
| `learn:schedule` | Creates or updates the desktop scheduled task `cta-weekly-report`, Mondays 07:00 local time, which runs `learn:report` then `learn:deliver`. Safe to run again. |

`learn:report`, `learn:decide` and `learn:deliver` never write in the live knowledge-base checkout.
They work in git worktrees on `learn/...` branches and open pull requests.

## The `/cta-reports` pane

A pane (a mod in `hooks/register.tsx`) that lists the reports in your knowledge base, shows each
recommendation and lets you accept, defer or reject it with a reason. It uses only the `claude-code`
mod API.

## Where things live

Under `<kb>/<kb_dir>/`, with `kb_dir` defaulting to `learn`:

| Path | Holds |
|---|---|
| `reports/<YYYY-MM-DD>.md`, `.json`, `.html` | The weekly report in three forms |
| `reports/index.json` | The list of reports |
| `decisions.jsonl` | One line per decision |
| `backlog.md` | Recommendations past the cap of five |

## Config

Settings live in `~/.config/cta/config.toml` (the `CTA_CONFIG` environment variable points
elsewhere). Every key is optional. A bad value is replaced by its default and reported as a note.
The values below are placeholders.

```toml
kb = "~/notes"

[learn]
kb_dir = "learn"
exclude_organization_ids = ["example-org-id"]
exclude_owners = ["example-owner"]
fallback_repo = "owner/repo"

[learn.delivery]
to = "you@example.com"
```

| Key | Default | Meaning |
|---|---|---|
| `kb` (top level) | unset | Knowledge-base repo. The learn scripts refuse to write reports without it. |
| `[learn] kb_dir` | `learn` | Folder under `kb` for reports, `decisions.jsonl` and `backlog.md`. Relative, no `..`. |
| `[learn] exclude_organization_ids` | `[]` | Work organization IDs. Their events are dropped before ranking. Replaces the old `organization_ids` key, which is now ignored with a note. |
| `[learn] exclude_owners` | `[]` | Marketplace repo owners whose skills are left out of the report. |
| `[learn] fallback_repo` | unset | `owner/name` repo where `learn:decide` files an issue when the skill's own repo is not writable. |
| `[learn] prometheus_url` | `http://127.0.0.1:9090` | Prometheus the report reads. |
| `[learn] loki_url` | `http://127.0.0.1:3100` | Loki the report reads. |
| `[learn] grafana_url` | `http://127.0.0.1:3000` | Grafana the report links to. |
| `[learn] otlp_url` | `http://127.0.0.1:4318` | OTLP endpoint that receives the `cta.learn.decision` event. |
| `[learn] min_sessions` | `3` | Fewest sessions a skill needs to become a recommendation candidate. |
| `[learn] followup_reports` | `4` | Reports a follow-up on a decision appears in before it ends. |
| `[learn.delivery] to` | unset | The one address `learn:deliver` emails. `deliver` exits 2 while it is unset. |
| `[learn.delivery] channel` | `email` | Delivery channel. |
| `[learn.delivery] format` | `html` | Delivery format. |
| `projects` (top level) | `{}` | Repo path to slug table. The learn report scans each listed repo for broken skills and stale rules. |

`exclude_organization_ids` replaces the earlier `organization_ids`. A leftover `organization_ids`
is ignored and adds a note. A skill, event or episode counts unless its organization is in
`exclude_organization_ids` or its marketplace owner is in `exclude_owners`; until the work
organization ID is listed, work skills appear in the report.

## Email

The unattended weekly email goes only to `[learn.delivery] to`. `learn:deliver` takes the address
from the config, sends a single recipient with no cc or bcc, and does not send when the report
text asks for another recipient.
