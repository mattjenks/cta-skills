"""Rot checks. Drop a module here with KIND and check(week, cfg) and it is found.

A module that lacks the contract is skipped and named in the errors; it never stops the others.
"""

from __future__ import annotations

import importlib.util
import pkgutil
import sys
from types import ModuleType

from model import RotItem

KINDS = ("broken", "stale", "permission")
CAP = 5


def _load(info: pkgutil.ModuleInfo) -> ModuleType:
    """Load one module of this package through the finder that listed it."""
    full = f"{__name__}.{info.name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = info.module_finder.find_spec(full)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(full, None)
        raise
    return module


def discover() -> tuple[list[ModuleType], list[str]]:
    mods: list[ModuleType] = []
    errors: list[str] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name == "__init__" or info.name.startswith("_"):
            continue
        try:
            mod = _load(info)
        except Exception as exc:  # a broken check must not stop the report
            errors.append(f"rot {info.name}: import failed ({type(exc).__name__})")
            continue
        if getattr(mod, "KIND", None) in KINDS and callable(getattr(mod, "check", None)):
            mods.append(mod)
        else:
            errors.append(f"rot {info.name}: missing KIND or check")
    return sorted(mods, key=lambda m: m.__name__), errors


def run_rot(week, cfg) -> tuple[dict[str, list[RotItem]], dict[str, int], list[str]]:
    """Items per kind (at most 5 each), the full count per kind, and the errors."""
    mods, errors = discover()
    found: dict[str, list[RotItem]] = {kind: [] for kind in KINDS}
    for mod in mods:
        name = mod.__name__.rsplit(".", 1)[-1]
        try:
            found[mod.KIND].extend(mod.check(week, cfg))
        except Exception as exc:  # one failing check is named, the rest still run
            errors.append(f"rot {name}: failed ({type(exc).__name__})")
    totals = {kind: len(items) for kind, items in found.items()}
    return {kind: items[:CAP] for kind, items in found.items()}, totals, errors
