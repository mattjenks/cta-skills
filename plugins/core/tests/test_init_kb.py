import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / "skills" / "init-kb"
TEMPLATES = SKILL / "templates"
SCRIPTS = SKILL / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import init_kb  # noqa: E402

EXPECTED = [
    "README.md",
    "projects/README.md",
    "DECISIONS.md",
    "PREFERENCES.md",
    "BOUNDARIES.md",
    "SOUL.md",
    "USER.md",
    ".markdownlint-cli2.jsonc",
    ".github/workflows/lint.yml",
    ".github/workflows/secret-scan.yml",
]
FORBIDDEN = ["@gmail.com", "personal-kb", "mobile documents", "jax", "/users/", "matt"]


def _files():
    return [p for p in TEMPLATES.rglob("*") if p.is_file()]


def test_expected_templates_exist():
    for rel in EXPECTED:
        assert (TEMPLATES / rel).is_file(), rel


def test_templates_have_no_personal_data():
    hits = []
    for path in _files():
        text = path.read_text().lower()
        hits += [f"{path.name}: {t}" for t in FORBIDDEN if t in text]
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), path.name
    assert not hits, hits


def test_project_standard_stated():
    text = (TEMPLATES / "projects/README.md").read_text()
    for name in ("design.md", "reqs.md", "plan.md", "backlog.md", "progress.md",
                 "security.json", "retro.md", "builds/<YYYY-MM-DD>-<topic>/"):
        assert name in text, name


def test_workflows_sha_pinned():
    uses = []
    for wf in (TEMPLATES / ".github/workflows").glob("*.yml"):
        text = wf.read_text()
        uses += re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, re.M)
        assert re.search(r"^permissions:\s*\n\s+contents: read", text, re.M), wf.name
        assert "pull_request" in text and re.search(r"push:\s*\n\s+branches: \[main\]", text), wf.name
    assert len(uses) >= 3
    for ref, rest in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), ref


def test_workflow_jobs():
    lint = (TEMPLATES / ".github/workflows/lint.yml").read_text()
    scan = (TEMPLATES / ".github/workflows/secret-scan.yml").read_text()
    assert re.search(r"^  markdownlint:", lint, re.M)
    assert re.search(r"^  gitleaks:", scan, re.M)
    assert "fetch-depth: 0" in scan


def test_markdownlint_config_parses():
    text = (TEMPLATES / ".markdownlint-cli2.jsonc").read_text()
    stripped = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    data = json.loads(stripped)
    assert isinstance(data.get("config"), dict)


def test_skill_mentions_confirm_before_repo_create():
    text = (SKILL / "SKILL.md").read_text()
    assert "gh repo create" in text and "--private" in text
    idx = text.index("gh repo create")
    window = text[max(0, idx - 400): idx + 400].lower()
    assert "confirm" in window


def test_skill_mentions_key_contract():
    text = (SKILL / "SKILL.md").read_text()
    for needle in ("kb", "config.toml", "non-empty", "merge", "git init"):
        assert needle in text, needle


# --- script ---


def test_check_target(tmp_path):
    assert init_kb.target_state(tmp_path / "new") == "missing"
    empty = tmp_path / "e"
    empty.mkdir()
    assert init_kb.target_state(empty) == "empty"
    (empty / ".git").mkdir()
    assert init_kb.target_state(empty) == "empty"  # bare git dir alone is not content
    (empty / "x.md").write_text("x")
    assert init_kb.target_state(empty) == "non-empty"


def test_init_refuses_non_empty_without_merge(tmp_path):
    (tmp_path / "keep.md").write_text("mine")
    with pytest.raises(init_kb.InitError, match="not empty"):
        init_kb.init_kb(tmp_path)
    assert not (tmp_path / "README.md").exists()
    assert not (tmp_path / ".git").exists()


def test_init_fresh_copies_templates_and_git(tmp_path):
    target = tmp_path / "kb"
    result = init_kb.init_kb(target)
    for rel in EXPECTED:
        assert (target / rel).is_file(), rel
    assert (target / ".git").is_dir()
    assert sorted(result["copied"]) == sorted(EXPECTED)
    assert result["skipped"] == []


def test_merge_never_overwrites(tmp_path):
    (tmp_path / "README.md").write_text("mine")
    result = init_kb.init_kb(tmp_path, merge=True)
    assert (tmp_path / "README.md").read_text() == "mine"
    assert "README.md" in result["skipped"]
    assert (tmp_path / "SOUL.md").is_file()


def test_existing_repo_is_not_reinitialised(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.md").write_text("a")
    init_kb.init_kb(tmp_path, merge=True)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "--git-dir"],
                          capture_output=True, text=True)
    assert head.stdout.strip() == ".git"


def test_set_kb_creates_config(tmp_path):
    cfg = tmp_path / "sub" / "config.toml"
    init_kb.set_kb(cfg, tmp_path / "kb")
    assert tomllib.loads(cfg.read_text())["kb"] == str((tmp_path / "kb").resolve())


def test_set_kb_preserves_other_content(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('# mine\npersona = "p.md"\n\n[projects]\n"/r" = "r"\n')
    init_kb.set_kb(cfg, tmp_path / "kb")
    data = tomllib.loads(cfg.read_text())
    assert data["kb"] == str((tmp_path / "kb").resolve())
    assert data["persona"] == "p.md" and data["projects"] == {"/r": "r"}
    assert "# mine" in cfg.read_text()


def test_set_kb_same_value_is_noop(tmp_path):
    cfg = tmp_path / "config.toml"
    init_kb.set_kb(cfg, tmp_path / "kb")
    before = cfg.read_text()
    init_kb.set_kb(cfg, tmp_path / "kb")
    assert cfg.read_text() == before


def test_set_kb_refuses_different_existing(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('kb = "/elsewhere"\n')
    with pytest.raises(init_kb.InitError, match="already"):
        init_kb.set_kb(cfg, tmp_path / "kb")
    assert cfg.read_text() == 'kb = "/elsewhere"\n'


def test_set_kb_refuses_invalid_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is = = not toml\n")
    with pytest.raises(init_kb.InitError, match="not valid TOML"):
        init_kb.set_kb(cfg, tmp_path / "kb")
    assert cfg.read_text() == "this is = = not toml\n"


def test_set_kb_escapes_odd_paths(tmp_path):
    cfg = tmp_path / "config.toml"
    odd = tmp_path / 'we"ird\\dir'
    init_kb.set_kb(cfg, odd)
    assert tomllib.loads(cfg.read_text())["kb"] == str(odd.resolve())


def test_cli_uses_cta_config_env(tmp_path):
    cfg = tmp_path / "c.toml"
    env = {"CTA_CONFIG": str(cfg), "PATH": "/usr/bin:/bin"}
    kb = tmp_path / "kb"
    r = subprocess.run([sys.executable, str(SCRIPTS / "init_kb.py"), "init", "--target", str(kb)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, str(SCRIPTS / "init_kb.py"), "config", "--target", str(kb)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert tomllib.loads(cfg.read_text())["kb"] == str(kb.resolve())


def test_cli_refuses_non_empty(tmp_path):
    (tmp_path / "x").write_text("x")
    r = subprocess.run([sys.executable, str(SCRIPTS / "init_kb.py"), "init", "--target", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "not empty" in r.stderr
