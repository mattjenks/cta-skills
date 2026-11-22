"""Config loader for cta-core hooks. Never raises: problems are reported in `notes`."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config/cta/config.toml"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CtaConfig:
    persona: Path
    context: tuple[Path, ...] = ()
    kb: Path | None = None
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

    return CtaConfig(
        persona=persona,
        context=tuple(context),
        kb=kb,
        notes=tuple(notes),
    )


def _default_persona(plugin_root: Path) -> Path:
    return plugin_root / "personas" / "default.md"
