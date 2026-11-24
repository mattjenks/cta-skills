#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""`[learn]` config for the learn plugin. Never raises: problems become `notes`."""

from __future__ import annotations

import os
import importlib.util
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path



def _load_hooks_config():
    """Load this plugin's own cta_config copy under a private name, so it never shadows another plugin's."""
    path = Path(__file__).resolve().parent.parent / "hooks" / "cta_config.py"
    spec = importlib.util.spec_from_file_location("learn_cta_config", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


cta_config = _load_hooks_config()

FALLBACK_REPO = re.compile(r"[\w.-]+/[\w.-]+")


@dataclass(frozen=True)
class Delivery:
    to: str | None
    channel: str = "email"
    format: str = "html"


@dataclass(frozen=True)
class LearnConfig:
    kb: Path | None
    kb_dir: str = "learn"
    organization_ids: tuple[str, ...] = ()
    exclude_owners: tuple[str, ...] = ()
    fallback_repo: str | None = None
    prometheus_url: str = "http://127.0.0.1:9090"
    loki_url: str = "http://127.0.0.1:3100"
    grafana_url: str = "http://127.0.0.1:3000"
    otlp_url: str = "http://127.0.0.1:4318"
    min_sessions: int = 3
    followup_reports: int = 4
    repos: tuple[Path, ...] = ()
    delivery: Delivery = Delivery(None)
    notes: tuple[str, ...] = ()


def _learn_section(path: Path | None) -> object:
    """The raw `[learn]` value, read from the same file cta_config.load_config reads."""
    if path is None:
        override = os.environ.get("CTA_CONFIG")
        path = Path(override) if override else cta_config.DEFAULT_CONFIG_PATH
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh).get("learn")
    except (OSError, ValueError):
        return None


def _str_list(section: dict, key: str, notes: list[str]) -> tuple[str, ...]:
    if key not in section:
        return ()
    value = section[key]
    if isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value):
        return tuple(value)
    notes.append(f"config invalid: learn.{key}: must be a list of non-empty strings")
    return ()


def _int(section: dict, key: str, default: int, notes: list[str]) -> int:
    if key not in section:
        return default
    value = section[key]
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    notes.append(f"config invalid: learn.{key}: must be an integer >= 1")
    return default


def _url(section: dict, key: str, default: str, notes: list[str]) -> str:
    if key not in section:
        return default
    value = section[key]
    if isinstance(value, str) and re.fullmatch(r"https?://\S+", value):
        return value
    notes.append(f"config invalid: learn.{key}: must be an http(s) URL")
    return default


def load_learn_config(path: Path | None = None) -> LearnConfig:
    base = cta_config.load_config(path)
    notes = list(base.notes)
    section = _learn_section(path)
    if section is None:
        section = {}
    elif not isinstance(section, dict):
        notes.append("config invalid: learn: must be a table")
        section = {}

    kb_dir = "learn"
    if "kb_dir" in section:
        value = section["kb_dir"]
        if (isinstance(value, str) and value.strip() and not Path(value).is_absolute()
                and ".." not in Path(value).parts):
            kb_dir = value
        else:
            notes.append("config invalid: learn.kb_dir: must be a relative folder with no '..'")

    fallback_repo = None
    if "fallback_repo" in section:
        value = section["fallback_repo"]
        if isinstance(value, str) and FALLBACK_REPO.fullmatch(value):
            fallback_repo = value
        else:
            notes.append("config invalid: learn.fallback_repo: must look like owner/name")

    delivery = Delivery(None)
    table = section.get("delivery")
    if table is not None and not isinstance(table, dict):
        notes.append("config invalid: learn.delivery: must be a table")
    elif table:
        fields: dict[str, str] = {}
        for key in ("to", "channel", "format"):
            if key in table:
                value = table[key]
                if isinstance(value, str) and value.strip():
                    fields[key] = value
                else:
                    notes.append(f"config invalid: learn.delivery.{key}: must be a non-empty string")
        delivery = Delivery(fields.pop("to", None), **fields)

    return LearnConfig(
        kb=base.kb,
        kb_dir=kb_dir,
        organization_ids=_str_list(section, "organization_ids", notes),
        exclude_owners=_str_list(section, "exclude_owners", notes),
        fallback_repo=fallback_repo,
        prometheus_url=_url(section, "prometheus_url", "http://127.0.0.1:9090", notes),
        loki_url=_url(section, "loki_url", "http://127.0.0.1:3100", notes),
        grafana_url=_url(section, "grafana_url", "http://127.0.0.1:3000", notes),
        otlp_url=_url(section, "otlp_url", "http://127.0.0.1:4318", notes),
        min_sessions=_int(section, "min_sessions", 3, notes),
        followup_reports=_int(section, "followup_reports", 4, notes),
        repos=tuple(Path(p) for p in base.projects),
        delivery=delivery,
        notes=tuple(notes),
    )


def learn_dir(cfg: LearnConfig) -> Path:
    if cfg.kb is None:
        raise ValueError("kb is not configured")
    return cfg.kb / cfg.kb_dir
