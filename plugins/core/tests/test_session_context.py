import json
import subprocess
import sys
from pathlib import Path

from cta_config import CtaConfig
from session_context import build_context

SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "session_context.py"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path):
    path.mkdir(exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "-c", "user.name=Ada", "-c", "user.email=ada@example.com",
         "commit", "-q", "--allow-empty", "-m", "first")
    return path


def _cfg(tmp_path, persona_text="I am Ada.", ctx=(), notes=()):
    persona = tmp_path / "persona.md"
    persona.write_text(persona_text)
    return CtaConfig(persona=persona, context=tuple(ctx), notes=tuple(notes))


def test_injects_persona_then_context_in_order(tmp_path):
    a = tmp_path / "A.md"
    a.write_text("alpha text")
    b = tmp_path / "B.md"
    b.write_text("beta text")
    out = build_context(_cfg(tmp_path, ctx=[a, b], notes=["a note"]), tmp_path)
    assert out.startswith("<cta-context>")
    assert out.rstrip().endswith("</cta-context>")
    p = out.index("===== persona: persona.md =====")
    ia = out.index("===== A.md =====")
    ib = out.index("===== B.md =====")
    assert p < ia < ib
    assert "I am Ada." in out and "alpha text" in out and "beta text" in out
    assert "a note" in out


def test_missing_context_file_is_named(tmp_path):
    gone = Path("/x/BOUNDARIES.md")
    out = build_context(_cfg(tmp_path, ctx=[gone]), tmp_path)
    assert "[cta] missing: /x/BOUNDARIES.md" in out


def test_missing_persona_is_named(tmp_path):
    cfg = CtaConfig(persona=tmp_path / "nope.md")
    out = build_context(cfg, tmp_path)
    assert f"[cta] missing: {tmp_path / 'nope.md'}" in out


def test_missing_persona_falls_back_to_bundled_default(tmp_path):
    cfg = CtaConfig(persona=tmp_path / "nope.md")
    out = build_context(cfg, tmp_path)
    bundled = (SCRIPT.parent.parent / "personas" / "default.md").read_text().strip()
    assert "===== persona: default.md =====" in out
    assert bundled in out
    assert f"[cta] missing: {tmp_path / 'nope.md'}" in out


def test_cap_drops_git_then_later_files_never_first(tmp_path):
    repo = _repo(tmp_path / "repo")
    first = tmp_path / "FIRST.md"
    first.write_text("f" * 300)
    second = tmp_path / "SECOND.md"
    second.write_text("s" * 300)
    cfg = _cfg(tmp_path, persona_text="p", ctx=[first, second])
    out = build_context(cfg, repo, cap=500)
    assert "f" * 300 in out
    assert "s" * 300 not in out
    assert "branch" not in out.lower()
    last = out.rstrip().splitlines()[-1]
    assert last.startswith("[cta] dropped for size:")
    assert "SECOND.md" in last and "git" in last
    assert len(out) <= 500


def test_not_a_repo_has_no_git_block(tmp_path):
    out = build_context(_cfg(tmp_path), tmp_path)
    assert "git state" not in out


def test_repo_has_git_block(tmp_path):
    repo = _repo(tmp_path / "repo")
    out = build_context(_cfg(tmp_path), repo)
    assert "git state" in out and "main" in out and "first" in out


def _run(stdin, env_cfg, tmp_path):
    env = {"PATH": __import__("os").environ["PATH"], "CTA_CONFIG": str(env_cfg),
           "HOME": str(tmp_path)}
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, text=True,
                          capture_output=True, env=env)


def test_main_emits_nested_additional_context(tmp_path):
    persona = tmp_path / "p.md"
    persona.write_text("persona body")
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'persona = "{persona}"\n')
    r = _run(json.dumps({"cwd": str(tmp_path)}), cfg, tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "additionalContext" not in data
    out = data["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert "persona body" in out["additionalContext"]


def test_main_fails_open(tmp_path):
    r = _run("{not json", tmp_path / "absent.toml", tmp_path)
    assert r.returncode == 0
    assert "Traceback" not in r.stderr
    assert "hookSpecificOutput" in r.stdout
