#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
# Adapted from coleam00/skills hooks/session_start_context.py (MIT)
"""SessionStart hook: inject the persona, configured context files, and git state.

A configured persona file that is missing is reported with `[cta] missing: <path>` and
the bundled default persona is injected in its place.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CAP = 9500
DEFAULT_PERSONA = Path(__file__).resolve().parent.parent / "personas" / "default.md"
OPEN, CLOSE = "<cta-context>", "</cta-context>"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _git(cwd: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_block(cwd: Path) -> str | None:
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return None
    status = (_git(cwd, "status", "--short") or "").splitlines()
    log = (_git(cwd, "log", "-5", "--oneline") or "").strip()
    shown = status[:20]
    if len(status) > 20:
        shown.append(f"... {len(status) - 20} more")
    return (
        "===== git state =====\n"
        f"branch: {branch.strip()}\n"
        f"status:\n{chr(10).join(shown) or '(clean)'}\n"
        f"recent commits:\n{log or '(none)'}"
    )


def _render(blocks: list[str], dropped: list[str]) -> str:
    out = OPEN + "\n" + "\n".join(blocks) + "\n" + CLOSE
    if dropped:
        out += "\n[cta] dropped for size: " + ", ".join(dropped)
    return out


def build_context(cfg, cwd: Path, cap: int = CAP) -> str:
    fixed: list[str] = []  # missing lines and notes: always kept
    # (name, text, protected)
    items: list[tuple[str, str, bool]] = []

    first_ctx = True
    sources = [(cfg.persona, True)] + [(p, False) for p in cfg.context]
    for path, is_persona in sources:
        text = _read(path)
        if text is None:
            fixed.append(f"[cta] missing: {path}")
            if not is_persona or path == DEFAULT_PERSONA:
                continue
            text = _read(DEFAULT_PERSONA)
            if text is None:
                continue
            path = DEFAULT_PERSONA
        head = f"===== persona: {path.name} =====" if is_persona else f"===== {path.name} ====="
        # the persona and the first context file are never dropped
        protected = is_persona or first_ctx
        if not is_persona:
            first_ctx = False
        items.append((path.name, f"{head}\n{text.rstrip()}", protected))

    fixed.extend(f"[cta] note: {n}" for n in cfg.notes)
    git = _git_block(cwd)
    if git:
        items.append(("git state", git, False))

    def assemble(entries):
        # file blocks first, then missing/notes, git last
        files = [t for n, t, _ in entries if n != "git state"]
        gits = [t for n, t, _ in entries if n == "git state"]
        return files + fixed + gits

    kept = list(items)
    dropped: list[str] = []
    while len(_render(assemble(kept), dropped)) > cap:
        victim = next((e for e in reversed(kept) if not e[2]), None)
        if victim is None:
            break
        kept.remove(victim)
        dropped.append(victim[0])
    return _render(assemble(kept), dropped)


def _emit(text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": text}}))


def _fallback(note: str) -> str:
    body = _read(DEFAULT_PERSONA) or ""
    return f"{OPEN}\n===== persona: default.md =====\n{body.rstrip()}\n[cta] note: {note}\n{CLOSE}"


def main() -> int:
    try:
        try:
            data = json.loads(sys.stdin.read() or "{}")
            cwd = Path(data["cwd"]) if isinstance(data, dict) and data.get("cwd") else Path.cwd()
        except (ValueError, OSError):
            cwd = Path.cwd()
        try:
            import cta_config
            cfg = cta_config.load_config()
        except Exception as exc:  # includes unresolvable HOME at import time
            _emit(_fallback(f"config could not be loaded: {type(exc).__name__}"))
            return 0
        _emit(build_context(cfg, cwd))
    except Exception:
        try:
            _emit(_fallback("session-context hook failed"))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
