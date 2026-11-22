import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "release-please-config.json"
MANIFEST = ROOT / ".release-please-manifest.json"
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _config():
    return json.loads(CONFIG.read_text())


def _manifest():
    return json.loads(MANIFEST.read_text())


def _plugin_dirs():
    return sorted(
        f"plugins/{d.name}" for d in (ROOT / "plugins").iterdir() if d.is_dir()
    )


def test_every_plugin_is_a_release_package():
    packages = _config()["packages"]
    assert sorted(packages) == _plugin_dirs()
    assert sorted(_manifest()) == _plugin_dirs()


def test_package_settings():
    for path, pkg in _config()["packages"].items():
        assert pkg["release-type"] == "simple", path
        assert pkg["component"] == path.split("/")[-1], path
        assert pkg["changelog-path"] == "CHANGELOG.md", path
        assert pkg["include-component-in-tag"] is True, path


def test_extra_files_exist():
    for path, pkg in _config()["packages"].items():
        extras = pkg["extra-files"]
        assert extras, path
        for extra in extras:
            assert extra["type"] == "json" and extra["jsonpath"].startswith("$."), extra
            p = extra["path"]
            # Leading slash = repo root; otherwise relative to the package.
            target = ROOT / p.lstrip("/") if p.startswith("/") else ROOT / path / p
            assert target.is_file(), f"{path}: {p}"
        paths = {e["path"] for e in extras}
        assert ".claude-plugin/plugin.json" in paths
        assert "/.claude-plugin/marketplace.json" in paths


def test_manifest_versions_match_plugin_json():
    for path, version in _manifest().items():
        plugin = json.loads((ROOT / path / ".claude-plugin" / "plugin.json").read_text())
        assert plugin["version"] == version, path


def test_marketplace_jsonpath_selects_the_plugin_entry():
    for path, pkg in _config()["packages"].items():
        name = pkg["component"]
        market = [e for e in pkg["extra-files"] if e["path"].endswith("marketplace.json")]
        assert [e["jsonpath"] for e in market] == [
            f"$.plugins[?(@.name=='{name}')].version"
        ]


def _load_yaml(path: Path):
    code = "import json,sys,yaml;print(json.dumps(yaml.safe_load(open(sys.argv[1]))))"
    out = subprocess.run(
        ["uv", "run", "--quiet", "--with", "pyyaml", "python", "-c", code, str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _workflow(name):
    return _load_yaml(WORKFLOWS / name)


def test_workflows_parse_and_pin_actions_by_sha():
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert {f.name for f in files} == {"ci.yml", "release.yml"}
    for f in files:
        wf = _load_yaml(f)
        uses = [
            step["uses"]
            for job in wf["jobs"].values()
            for step in job["steps"]
            if "uses" in step
        ]
        assert uses, f.name
        for u in uses:
            assert SHA_PIN.match(u), f"{f.name}: {u} is not pinned by full SHA"
        text = f.read_text()
        for line in text.splitlines():
            if "uses:" in line:
                assert re.search(r"#\s*v\d+\.\d+\.\d+\s*$", line), f"{f.name}: {line}"


def test_ci_workflow_shape():
    wf = _workflow("ci.yml")
    assert wf["name"] == "CI"
    triggers = wf.get("on") or wf["true"]  # YAML 1.1: bare `on` is True, JSON-dumped as "true"
    assert "pull_request" in triggers
    assert triggers["push"]["branches"] == ["main"]
    assert wf["permissions"] == {"contents": "read"}
    assert wf["concurrency"]["cancel-in-progress"] is True
    assert list(wf["jobs"]) == ["tests"]
    job = wf["jobs"]["tests"]
    assert job["name"] == "tests"
    assert job["runs-on"] == "ubuntu-latest"
    assert any(s.get("run") == "uv run --with pytest pytest -q" for s in job["steps"])


def test_release_workflow_shape():
    wf = _workflow("release.yml")
    triggers = wf.get("on") or wf["true"]
    assert triggers["push"]["branches"] == ["main"]
    job = next(iter(wf["jobs"].values()))
    assert job["permissions"]["contents"] == "write"
    assert job["permissions"]["pull-requests"] == "write"
    step = next(s for s in job["steps"] if "release-please" in s.get("uses", ""))
    assert step["with"]["config-file"] == "release-please-config.json"
    assert step["with"]["manifest-file"] == ".release-please-manifest.json"
