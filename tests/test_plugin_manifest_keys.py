import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def test_plugin_json_has_no_schema_key():
    """claude.ai warns on unknown plugin.json keys and strips them; `$schema` is one."""
    for entry in json.loads(MARKETPLACE.read_text())["plugins"]:
        manifest = json.loads((ROOT / entry["source"] / ".claude-plugin" / "plugin.json").read_text())
        assert "$schema" not in manifest, entry["name"]
