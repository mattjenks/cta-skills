"""Signal modules. Drop a module here with NAME, PANEL and evaluate(week, skill) and it is found.

A module that lacks the contract is skipped and named in the errors; it never stops the others.
"""

from __future__ import annotations

import importlib.util
import pkgutil
import sys
from types import ModuleType


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
        except Exception as exc:  # a broken signal must not stop the report
            errors.append(f"signal {info.name}: import failed ({type(exc).__name__})")
            continue
        if (isinstance(getattr(mod, "NAME", None), str) and isinstance(getattr(mod, "PANEL", None), str)
                and callable(getattr(mod, "evaluate", None))):
            mods.append(mod)
        else:
            errors.append(f"signal {info.name}: missing NAME, PANEL or evaluate")
    return sorted(mods, key=lambda m: m.__name__), errors
