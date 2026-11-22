import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
FORBIDDEN = ["@gmail.com", "personal-kb", "mobile documents", "jax"]


def _marketplace():
    return json.loads(MARKETPLACE.read_text())


def test_marketplace_lists_every_plugin_dir():
    plugins = _marketplace()["plugins"]
    sources = {(ROOT / p["source"]).resolve() for p in plugins}
    for p in plugins:
        assert (ROOT / p["source"]).is_dir(), p["source"]
    dirs = {d.resolve() for d in (ROOT / "plugins").glob("*/") if d.is_dir()}
    assert dirs <= sources, f"plugin dirs missing from marketplace: {dirs - sources}"


def test_plugin_versions_match():
    for entry in _marketplace()["plugins"]:
        plugin_dir = ROOT / entry["source"]
        manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
        assert manifest["version"] == entry["version"]
        changelog = (plugin_dir / "CHANGELOG.md").read_text()
        assert re.search(rf"^## {re.escape(entry['version'])}\b", changelog, re.M)


def _candidate_files():
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    for rel in out:
        parts = Path(rel).parts
        name = parts[-1]
        if rel == "NOTICE" or "tests" in parts[:-1]:
            continue
        if name.startswith(("test_", "_test_")):
            continue
        path = ROOT / rel
        if path.is_file():
            yield rel, path


def test_no_personal_data():
    hits = []
    for rel, path in _candidate_files():
        try:
            text = path.read_text().lower()
        except UnicodeDecodeError:
            continue
        hits += [f"{rel}: {term}" for term in FORBIDDEN if term in text]
    assert not hits, hits
