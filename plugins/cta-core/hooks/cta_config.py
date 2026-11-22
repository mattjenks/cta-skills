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


def _default_persona(plugin_root: Path) -> Path:
    return plugin_root / "personas" / "default.md"


def load_config(path: Path | None = None, plugin_root: Path | None = None) -> CtaConfig:
    """Load config.toml. Explicit `path` wins; otherwise CTA_CONFIG, then the default path."""
    root = plugin_root if plugin_root is not None else PLUGIN_ROOT
    notes: list[str] = []

    if path is None:
        env = os.environ.get("CTA_CONFIG")
        path = Path(env) if env else DEFAULT_CONFIG_PATH

    data: dict = {}
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        pass  # no config is a normal state: defaults, no note
    except (OSError, tomllib.TOMLDecodeError) as exc:
        notes.append(f"config unreadable: {exc}")
        data = {}

    persona = _default_persona(root)
    value = data.get("persona")
    if isinstance(value, str):
        persona = Path(value).expanduser()
    elif value is not None:
        notes.append("config invalid: persona must be a string path")

    context: list[Path] = []
    value = data.get("context")
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        context = [Path(v).expanduser() for v in value]
    elif value is not None:
        notes.append("config invalid: context must be a list of string paths")

    kb: Path | None = None
    value = data.get("kb")
    if isinstance(value, str):
        kb = Path(value).expanduser()
    elif value is not None:
        notes.append("config invalid: kb must be a string path")

    return CtaConfig(
        persona=persona,
        context=tuple(context),
        kb=kb,
        notes=tuple(notes),
    )
