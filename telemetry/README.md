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

The dashboard's "Installed skills" variable is a fixed list (create-skill, create-hook,
config-audit); edit it in `grafana/dashboards/cta-skills.json`.

## Where data lives

Under `~/.local/share/cta/telemetry/` (override with `CTA_DATA`): `archive/`, `prometheus/`,
`loki/`, `tempo/`, `grafana/`.

| Store | Retention |
|---|---|
| Loki | 90 days (`retention_period: 2160h`, compactor retention on) |
| Prometheus | 400 days |
| Archive | collector `file` exporter writes `archive/otel.jsonl` (JSON, uncompressed), rotating at 100 MB; rotated files get timestamped names and are pruned after 3 days (`max_days`). Task 10's backup copies them off by mtime date. |

Metrics reach Prometheus with dotted names underscored and the unit appended, e.g.
`claude_code_cost_usage_USD_total`, `claude_code_token_usage_tokens_total` (label `skill_name`).
Delta counters from Claude Code are converted to cumulative by the collector.
Log attributes land in Loki as structured metadata (`event_name`, `skill_name`, ...).

## Privacy

**The archive contains prompt text** (`claude_code.user_prompt`) and is private. Never commit it,
share it or sync it to a shared location. Loki holds the same content.
