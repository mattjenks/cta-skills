#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Set up a knowledge-base folder: check it, git init, copy templates, record `kb`.

CLI (prints JSON; errors go to stderr with exit 2):
  init_kb.py check  --target DIR
  init_kb.py init   --target DIR [--merge]     git init if needed, copy templates, never overwrite
  init_kb.py config --target DIR [--config PATH]   write top-level kb = "<DIR>" (default: $CTA_CONFIG
                                                   or ~/.config/cta/config.toml)
Stdlib only. The skill, not this script, asks the user before merging or creating a remote.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
DEFAULT_CONFIG = Path.home() / ".config" / "cta" / "config.toml"


class InitError(Exception):
    """The folder or config cannot be set up safely."""


def target_state(target: Path) -> str:
    """'missing', 'empty' (nothing but a .git directory) or 'non-empty'."""
    target = Path(target)
    if not target.exists():
        return "missing"
    if not target.is_dir():
        raise InitError(f"{target} is not a directory")
    names = {p.name for p in target.iterdir()} - {".git"}
    return "non-empty" if names else "empty"


def _template_files() -> list[Path]:
    return sorted(p.relative_to(TEMPLATES) for p in TEMPLATES.rglob("*") if p.is_file())


def init_kb(target: Path, merge: bool = False) -> dict:
    target = Path(target).expanduser()
    state = target_state(target)
    if state == "non-empty" and not merge:
        raise InitError(f"{target} is not empty; pass --merge only after the user agrees to merge")
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        r = subprocess.run(["git", "init", "-q", str(target)], capture_output=True, text=True)
        if r.returncode != 0:
            raise InitError(f"git init failed: {r.stderr.strip()}")
    copied, skipped = [], []
    for rel in _template_files():
        dest = target / rel
        if dest.exists():
            skipped.append(rel.as_posix())
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATES / rel, dest)
        copied.append(rel.as_posix())
    return {"target": str(target.resolve()), "state": state, "copied": copied, "skipped": skipped}


def _toml_str(value: str) -> str:
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def set_kb(config_path: Path, target: Path) -> str:
    """Write top-level `kb` without disturbing other content. Returns 'written' or 'unchanged'."""
    value = str(Path(target).expanduser().resolve())
    path = Path(os.path.realpath(Path(config_path).expanduser()))
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise InitError(f"{path} is not valid TOML ({exc}); not editing it") from exc
    if "kb" in before:
        if before["kb"] == value:
            return "unchanged"
        raise InitError(f"{path} already sets kb = {before['kb']!r}; ask the user before changing it")
    nl = "\r\n" if "\r\n" in text else "\n"
    out = f"kb = {_toml_str(value)}{nl}" + (nl + text if text and not text.startswith(("\n", "\r")) else text)
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError as exc:
        raise InitError(f"{path}: edit would produce invalid TOML ({exc}); not editing it") from exc
    if after != {**before, "kb": value}:
        raise InitError(f"{path}: edit did not round-trip; not editing it")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-init-kb")
    tmp.write_bytes(out.encode("utf-8"))
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)
    return "written"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "init", "config"):
        p = sub.add_parser(name)
        p.add_argument("--target", required=True)
        if name == "init":
            p.add_argument("--merge", action="store_true")
        if name == "config":
            p.add_argument("--config")
    args = ap.parse_args(argv)
    target = Path(args.target).expanduser()
    try:
        if args.cmd == "check":
            result = {"target": str(target), "state": target_state(target)}
        elif args.cmd == "init":
            result = init_kb(target, merge=args.merge)
        else:
            cfg = args.config or os.environ.get("CTA_CONFIG") or str(DEFAULT_CONFIG)
            result = {"config": cfg, "kb": str(target.resolve()), "result": set_kb(Path(cfg), target)}
    except InitError as exc:
        print(f"init-kb: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
