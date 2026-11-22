# CTA — Chief Technology Assistant

CTA is a prescriptive, Claude Code-specific system of skills and hooks for one loop:
**plan → build → deploy → monitor → learn**.

It is opinionated by design: one way through the loop, enforced by hooks rather than suggested.
The assistant's voice is a swappable persona. The bundled one is `default` ("CTA").

## Install

```text
/plugin marketplace add mattjenks/cta-skills
/plugin install core@cta
```

Skills are invoked as `/core:<skill>`.

| Plugin | Install | Skills |
|---|---|---|
| `core` | `/plugin install core@cta` | `/core:<skill>` |
| `build` | `/plugin install build@cta` | `/build:<skill>` (scaffold; skills land in later releases) |

## Requirements

- **macOS.** Desktop notifications (`osascript`), the scheduled jobs (launchd) and the telemetry
  stack (Docker via Colima or Docker Desktop) are macOS-only. Off macOS the hooks still run, but
  notifications are skipped.
- **[uv](https://docs.astral.sh/uv/) on your `PATH`.** Every hook runs as `uv run --script`.
  Without uv the hooks fail to start, and **the secrets guard is OFF**: nothing blocks reads of
  secret files or environment dumps.
- **Claude Code** with plugin marketplaces (`/plugin`) and the `SessionStart`, `PreToolUse`,
  `UserPromptSubmit`, `Stop` and `Notification` hook events. The telemetry stack needs Claude
  Code's OpenTelemetry export; its enhanced (skill-level) telemetry is a beta flag and may change
  between releases.

## Configuration

Personal settings live outside this repository, in `~/.config/cta/config.toml` (the
`CTA_CONFIG` environment variable points elsewhere). Paths are used as given, with `~` expanded;
they are not resolved against `kb` or any other folder.

```toml
persona = "~/notes/personas/me.md"    # persona file; omit for the bundled default ("CTA")
context = ["~/notes/BOUNDARIES.md"]   # files injected at session start, in order
kb = "~/notes"                        # reserved for later knowledge-base features; unused today

[notify]
min_turn_seconds = 300                # notify only for turns at least this long; 0 = every turn

[telemetry]
backup_dir = "~/Backups/cta-telemetry" # where the nightly telemetry backup copies the archive
```

| Key | Default | Meaning |
|---|---|---|
| `persona` | bundled `default` | Persona file injected at session start. If it is missing, CTA prints `[cta] missing: <path>` and uses the bundled default. |
| `context` | `[]` | Files injected after the persona, in order. A missing one is reported as `[cta] missing: <path>`. |
| `kb` | unset | Reserved for later knowledge-base features. |
| `[notify] min_turn_seconds` | `300` | Minimum turn length before a desktop notification; `0` notifies on every turn. |
| `[telemetry] backup_dir` | unset | Destination of the nightly telemetry backup; the backup exits 1 while it is unset. |

If the file is missing or unreadable, CTA starts with the default persona and a one-line note.

The local telemetry stack (OpenTelemetry Collector, Prometheus, Loki, Tempo, Grafana), its nightly
backup and how to turn on Claude Code's telemetry export are in
[`telemetry/README.md`](telemetry/README.md).

## Contributing / releases

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
`docs:`, `chore:`; `!` or a `BREAKING CHANGE:` footer for breaking changes). On every push to `main`,
release-please keeps a release PR open that bumps each plugin's version (in its `plugin.json` and its
`.claude-plugin/marketplace.json` entry) and its `CHANGELOG.md`. Merging that PR tags the release.

Pull requests need the `tests` check (the CI workflow) to pass before merging to `main`.

## Credits

Parts of CTA are adapted from [Cole Medin's skills](https://github.com/coleam00/skills) and
[superpowers](https://github.com/obra/superpowers). See `NOTICE`. Licensed under MIT.
