# CTA telemetry stack

Local Docker Compose stack that receives Claude Code's native OpenTelemetry export:
OpenTelemetry Collector -> Prometheus (metrics), Loki (logs, via native OTLP), Tempo (traces),
plus a rotating JSONL archive of every signal, and Grafana with a provisioned **CTA Skills** dashboard.

## Start / stop

```sh
docker compose -f telemetry/compose.yaml up -d      # start (Colima or Docker Desktop must be running)
docker compose -f telemetry/compose.yaml down       # stop; data is kept
uv run telemetry/smoke_test.py                      # exit 0 if a log, a metric and the archive all landed
```

If the stack is down, Claude Code behaves normally; it just exports nothing.

## Enable Claude Code telemetry export

Claude Code exports nothing until telemetry is turned on. Add these keys under `"env"` in
`~/.claude/settings.json` (merge with any `env` block already there), then start a new session:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
    "OTEL_LOG_TOOL_DETAILS": "1",
    "OTEL_LOG_USER_PROMPTS": "1",
    "OTEL_METRICS_INCLUDE_VERSION": "true"
  }
}
```

**Privacy:** `OTEL_LOG_USER_PROMPTS=1` records the text of your prompts. It stays on this machine,
but it is kept in Loki for 90 days and in the archive and its backups indefinitely. It is optional:
drop the key to log prompt lengths only. Without `OTEL_LOG_TOOL_DETAILS=1`, skill names from
third-party plugins are anonymized, so the dashboard cannot tell those skills apart.

## Ports (all bound to 127.0.0.1 only)

| Port | Service |
|---|---|
| 4317 / 4318 | OTLP gRPC / HTTP (Collector) |
| 3000 | Grafana |
| 9090 | Prometheus |
| 3100 | Loki |
| 3200 | Tempo |

## Grafana

Open <http://127.0.0.1:3000/d/cta-skills>. Anonymous Viewer access is on (localhost only). To edit,
sign in as `admin`; the password comes from `CTA_GRAFANA_ADMIN_PASSWORD`, defaulting to the
**local-only** value `cta-local-only`. Set the variable if the machine is shared.

The dashboard's "Installed skills" variable is a fixed list (`core:create-skill`,
`core:create-hook`, `core:config-audit`); edit it in `grafana/dashboards/cta-skills.json`.

## Where data lives

Under `~/.local/share/cta/telemetry/` (override with `CTA_DATA`): `archive/`, `prometheus/`,
`loki/`, `tempo/`, `grafana/`.

| Store | Retention |
|---|---|
| Loki | 90 days (`retention_period: 2160h`, compactor retention on) |
| Prometheus | 400 days |
| Archive | collector `file` exporter writes `archive/otel.jsonl` (JSON, uncompressed), rotating at 100 MB; rotated files get timestamped names and are pruned after 3 days (`max_days`). The nightly backup copies them off by mtime date. |

Metrics reach Prometheus with dotted names underscored and the unit appended, e.g.
`claude_code_cost_usage_USD_total`, `claude_code_token_usage_tokens_total` (label `skill_name`).
Delta counters from Claude Code are converted to cumulative by the collector.
Log attributes land in Loki as structured metadata (`event_name`, `skill_name`, ...). Claude Code's
`event_name` values are bare (`skill_activated`, `tool_result`, `user_prompt`, `api_request`; the
log body carries the `claude_code.` prefix), and `skill_name` is plugin-namespaced
(`core:create-skill`) in both Loki and Prometheus.

## Drift enrichment

```sh
uv run telemetry/enrich_drift.py --since 26h    # 30m, 26h, 7d
```

Reads `~/.claude/projects/**/*.jsonl` (never calls a model), derives one episode per skill
invocation with an outcome (`success`, `drifted`, `abandoned`) and drift signals, and posts each as
a `cta.skill_episode` log (`service_name="claude-code"`, attributes `skill`, `skill_short`,
`outcome`, `signals`, `turns`, `start`, `end`, `duration_ms`). Records are stamped with the run
time, since Loki rejects entries far behind the newest in a stream; use `start`/`end` for when the
episode happened. A per-transcript high-water mark in `~/.local/share/cta/state/drift.json`
advances only after the Collector accepts the POST; with the Collector down it exits 1 and writes
nothing. Episodes in a transcript still being written wait until they have two follow-up prompts
or the file has been idle for 5 minutes.

## Privacy

**The archive contains prompt text** (`claude_code.user_prompt`) and is private. Never commit it,
share it or sync it to a shared location. Loki holds the same content.

## Nightly backup and schedules (launchd)

Set the destination in `~/.config/cta/config.toml` (no personal path lives in the repo):

```toml
[telemetry]
backup_dir = "~/Backups/cta-telemetry"   # any folder, e.g. one inside a synced drive
```

Three user agents live in `telemetry/launchd/`: `net.cta.drift-enrich` (02:00, `--since 26h`),
`net.cta.telemetry-backup` (02:30) and `net.cta.telemetry-health` (at login: waits up to 5 minutes
for Docker, runs `smoke_test.py`, notifies **only on failure**). All set `CTA_UNATTENDED=1`, so the
notify hook stays silent.

```sh
telemetry/launchd/install.sh     # substitutes __REPO__ / __HOME__, writes ~/Library/LaunchAgents, bootstraps
telemetry/launchd/uninstall.sh   # boots them out and removes the installed plists
launchctl kickstart gui/$(id -u)/net.cta.telemetry-backup    # run one now
```

Logs: `~/.local/share/cta/logs/<label>.log`.

**Login autostart for containers:** run Colima at login with `brew services start colima`
(containers already have `restart: unless-stopped`).

**What the backup does:** `uv run --script telemetry/backup.py [--day YYYY-MM-DD]` copies rotated
archive files dated on or before the day that are not yet at the destination, plus a snapshot of the
live file as `otel-live-<YYYY-MM-DD>.jsonl` (replaced on a same-day re-run). Each copy goes to a temp
file, is verified by size and SHA-256, then renamed, so a failed copy leaves no partial file. The
source is never modified. After a successful run only the 7 newest `otel-live-*.jsonl` snapshots
are kept at the destination; rotated copies are never pruned. With nothing to copy it logs
"nothing to back up" and exits 0. With `backup_dir` unset, a copy failure or any other error it
exits 1, prints the cause (including any problem reading `config.toml`) to stderr, and raises a
macOS notification "CTA telemetry backup failed: <reason>".

**Restore:** the files are plain JSONL (OTLP JSON from the collector's file exporter). Copy the
needed `otel-*.jsonl` / `otel-live-*.jsonl` files from the backup folder back into
`~/.local/share/cta/telemetry/archive/` for reference or `jq` analysis. Re-ingesting into Loki or
Prometheus is a manual step; the archive is the raw record, not a database dump.
