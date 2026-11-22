from pathlib import Path

import cta_config
from cta_config import load_config

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_missing_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("CTA_CONFIG", raising=False)
    cfg = load_config(path=tmp_path / "absent.toml", plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.context == ()
    assert cfg.kb is None
    assert cfg.notes == ()


def test_default_persona_resolves_to_plugin_root(tmp_path):
    cfg = load_config(path=tmp_path / "absent.toml")
    assert cfg.persona == PLUGIN_ROOT / "personas" / "default.md"


def test_reads_persona_context_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'persona = "~/p.md"\n'
        'kb = "~/kb"\n'
        'context = ["~/b.md", "~/a.md", "/abs/c.md"]\n'
    )
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "p.md"
    assert cfg.kb == tmp_path / "kb"
    assert cfg.context == (tmp_path / "b.md", tmp_path / "a.md", Path("/abs/c.md"))


def test_unknown_keys_are_ignored(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[telemetry]\nenabled = true\n\nunknown = 1\n')
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.notes == ()
    assert cfg.context == ()


def test_malformed_toml_fails_soft(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("persona = [unterminated\n")
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.context == ()
    assert cfg.kb is None
    assert cfg.notes[0].startswith("config unreadable:")


def test_unreadable_path_fails_soft(tmp_path):
    cfg = load_config(path=tmp_path, plugin_root=tmp_path)  # a directory, not a file
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.notes[0].startswith("config unreadable:")


def test_env_override(tmp_path, monkeypatch):
    other = tmp_path / "other.toml"
    other.write_text('persona = "/custom/p.md"\n')
    monkeypatch.setenv("CTA_CONFIG", str(other))
    cfg = load_config(plugin_root=tmp_path)
    assert cfg.persona == Path("/custom/p.md")


def test_default_config_path():
    assert cta_config.DEFAULT_CONFIG_PATH == Path.home() / ".config/cta/config.toml"
