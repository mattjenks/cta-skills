"""Config loader for core hooks. Never raises: problems are reported in `notes`."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config/cta/config.toml"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NOTIFY_MIN_SECONDS = 300
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")


def state_dir() -> Path:
    """Per-user state directory. CTA_STATE_DIR overrides it (used by tests)."""
    override = os.environ.get("CTA_STATE_DIR")
    return Path(override) if override else Path.home() / ".local/share/cta/state"


def turn_file(session_id: object) -> Path | None:
    """Path of the turn-start record for a session, or None for an unsafe session id."""
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        return None
    return state_dir() / "turns" / session_id


@dataclass(frozen=True)
class CtaConfig:
    persona: Path
    context: tuple[Path, ...] = ()
    kb: Path | None = None
    notify_min_seconds: int = DEFAULT_NOTIFY_MIN_SECONDS
    backup_dir: Path | None = None
    notes: tuple[str, ...] = ()


def _path_value(value: object, key: str, notes: list[str]) -> Path | None:
    """Validate one string path from the config. Returns None and notes a problem otherwise."""
    if not isinstance(value, str):
        notes.append(f"config invalid: {key}: must be a string path")
        return None
    if not value.strip():
        notes.append(f"config invalid: {key}: must not be empty")
        return None
    try:
        return Path(value).expanduser()
    except (RuntimeError, ValueError) as exc:
        notes.append(f"config invalid: {key}: cannot expand {value!r} ({exc})")
        return None


def load_config(path: Path | None = None, plugin_root: Path | None = None) -> CtaConfig:
    """Load config.toml.

    An explicit `path` argument always wins. Otherwise the CTA_CONFIG environment
    variable overrides DEFAULT_CONFIG_PATH. A missing file is silent at the default
    path; when CTA_CONFIG names a missing file, a `config not found` note is added.
    """
    root = plugin_root if plugin_root is not None else PLUGIN_ROOT
    notes: list[str] = []
    from_env = False

    if path is None:
        env = os.environ.get("CTA_CONFIG")
        if env:
            path = Path(env)
            from_env = True
        else:
            path = DEFAULT_CONFIG_PATH

    data: dict = {}
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        if from_env:
            notes.append(f"config not found: {path}")
    except (OSError, ValueError) as exc:  # ValueError covers TOML and UTF-8 decode errors
        notes.append(f"config unreadable: {exc}")
        data = {}

    persona = _default_persona(root)
    if "persona" in data:
        resolved = _path_value(data["persona"], "persona", notes)
        if resolved is not None:
            persona = resolved

    context: list[Path] = []
    if "context" in data:
        entries = data["context"]
        if not isinstance(entries, list):
            notes.append("config invalid: context: must be a list of string paths")
        else:
            for entry in entries:
                resolved = _path_value(entry, "context", notes)
                if resolved is not None:
                    context.append(resolved)

    kb: Path | None = None
    if "kb" in data:
        kb = _path_value(data["kb"], "kb", notes)

    notify_min_seconds = DEFAULT_NOTIFY_MIN_SECONDS
    section = data.get("notify")
    if section is not None and not isinstance(section, dict):
        notes.append("config invalid: notify: must be a table")
    elif section and "min_turn_seconds" in section:
        value = section["min_turn_seconds"]
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            notify_min_seconds = value
        else:
            notes.append("config invalid: notify.min_turn_seconds: must be an integer >= 0")

    backup_dir: Path | None = None
    telemetry = data.get("telemetry")
    if telemetry is not None and not isinstance(telemetry, dict):
        notes.append("config invalid: telemetry: must be a table")
    elif telemetry and "backup_dir" in telemetry:
        backup_dir = _path_value(telemetry["backup_dir"], "telemetry.backup_dir", notes)

    return CtaConfig(
        persona=persona,
        context=tuple(context),
        kb=kb,
        notify_min_seconds=notify_min_seconds,
        backup_dir=backup_dir,
        notes=tuple(notes),
    )


def _default_persona(plugin_root: Path) -> Path:
    return plugin_root / "personas" / "default.md"
