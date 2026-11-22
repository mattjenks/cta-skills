import pytest
from pathlib import Path

import cta_config
from cta_config import load_config

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BAD_USER = "~nosuchuser-cta/x.md"


def _write(tmp_path, text):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(text)
    return cfg_file


def test_missing_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("CTA_CONFIG", raising=False)
    cfg = load_config(path=tmp_path / "absent.toml", plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.context == ()
    assert cfg.kb is None
    assert cfg.notes == ()


def test_missing_default_path_is_silent(tmp_path, monkeypatch):
    monkeypatch.delenv("CTA_CONFIG", raising=False)
    monkeypatch.setattr(cta_config, "DEFAULT_CONFIG_PATH", tmp_path / "absent.toml")
    cfg = load_config(plugin_root=tmp_path)
    assert cfg.notes == ()


def test_default_persona_resolves_to_plugin_root(tmp_path):
    cfg = load_config(path=tmp_path / "absent.toml")
    assert cfg.persona == PLUGIN_ROOT / "personas" / "default.md"


def test_reads_persona_context_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_file = _write(
        tmp_path,
        'persona = "~/p.md"\n'
        'kb = "~/kb"\n'
        'context = ["~/b.md", "~/a.md", "/abs/c.md"]\n',
    )
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "p.md"
    assert cfg.kb == tmp_path / "kb"
    assert cfg.context == (tmp_path / "b.md", tmp_path / "a.md", Path("/abs/c.md"))
    assert cfg.notes == ()


def test_unknown_keys_are_ignored(tmp_path):
    cfg_file = _write(tmp_path, "[telemetry]\nenabled = true\n\nunknown = 1\n")
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.notes == ()
    assert cfg.context == ()


def test_malformed_toml_fails_soft(tmp_path):
    cfg_file = _write(tmp_path, "persona = [unterminated\n")
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.context == ()
    assert cfg.kb is None
    assert cfg.notes[0].startswith("config unreadable:")


def test_invalid_utf8_fails_soft(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_bytes(b'persona = "\xff\xfe"\n')
    cfg = load_config(path=cfg_file, plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
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


def test_explicit_path_beats_env(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('persona = "/explicit/p.md"\n')
    other = tmp_path / "env.toml"
    other.write_text('persona = "/env/p.md"\n')
    monkeypatch.setenv("CTA_CONFIG", str(other))
    cfg = load_config(path=explicit, plugin_root=tmp_path)
    assert cfg.persona == Path("/explicit/p.md")


def test_env_names_missing_file(tmp_path, monkeypatch):
    missing = tmp_path / "nope.toml"
    monkeypatch.setenv("CTA_CONFIG", str(missing))
    cfg = load_config(plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.notes == (f"config not found: {missing}",)


def test_persona_unknown_user_falls_back(tmp_path):
    cfg = load_config(path=_write(tmp_path, f'persona = "{BAD_USER}"\n'), plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.notes[0].startswith("config invalid: persona:")


def test_context_unknown_user_entry_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = load_config(
        path=_write(tmp_path, f'context = ["{BAD_USER}", "~/b.md"]\n'),
        plugin_root=tmp_path,
    )
    assert cfg.context == (tmp_path / "b.md",)
    assert cfg.notes[0].startswith("config invalid: context:")


def test_kb_unknown_user_becomes_none(tmp_path):
    cfg = load_config(path=_write(tmp_path, f'kb = "{BAD_USER}"\n'), plugin_root=tmp_path)
    assert cfg.kb is None
    assert cfg.notes[0].startswith("config invalid: kb:")


def test_persona_wrong_type(tmp_path):
    cfg = load_config(path=_write(tmp_path, "persona = 5\n"), plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.notes == ("config invalid: persona: must be a string path",)


def test_persona_empty_string(tmp_path):
    cfg = load_config(path=_write(tmp_path, 'persona = ""\n'), plugin_root=tmp_path)
    assert cfg.persona == tmp_path / "personas" / "default.md"
    assert cfg.notes == ("config invalid: persona: must not be empty",)


def test_context_not_a_list(tmp_path):
    cfg = load_config(path=_write(tmp_path, 'context = "x"\n'), plugin_root=tmp_path)
    assert cfg.context == ()
    assert cfg.notes == ("config invalid: context: must be a list of string paths",)


def test_context_entry_wrong_type_is_skipped(tmp_path):
    cfg = load_config(path=_write(tmp_path, "context = [1]\n"), plugin_root=tmp_path)
    assert cfg.context == ()
    assert cfg.notes == ("config invalid: context: must be a string path",)


def test_kb_wrong_type(tmp_path):
    cfg = load_config(path=_write(tmp_path, "kb = []\n"), plugin_root=tmp_path)
    assert cfg.kb is None
    assert cfg.notes == ("config invalid: kb: must be a string path",)


def test_notify_default_is_300(tmp_path):
    cfg = load_config(path=_write(tmp_path, ""), plugin_root=tmp_path)
    assert cfg.notify_min_seconds == 300
    assert cfg.notes == ()


def test_notify_min_turn_seconds_read(tmp_path):
    cfg = load_config(
        path=_write(tmp_path, "[notify]\nmin_turn_seconds = 60\n"), plugin_root=tmp_path
    )
    assert cfg.notify_min_seconds == 60
    assert cfg.notes == ()


def test_notify_zero_is_valid(tmp_path):
    cfg = load_config(
        path=_write(tmp_path, "[notify]\nmin_turn_seconds = 0\n"), plugin_root=tmp_path
    )
    assert cfg.notify_min_seconds == 0


@pytest.mark.parametrize("raw", ["-1", '"x"', "1.5", "true"])
def test_notify_invalid_value_defaults_with_note(tmp_path, raw):
    cfg = load_config(
        path=_write(tmp_path, f"[notify]\nmin_turn_seconds = {raw}\n"), plugin_root=tmp_path
    )
    assert cfg.notify_min_seconds == 300
    assert cfg.notes == ("config invalid: notify.min_turn_seconds: must be an integer >= 0",)


def test_notify_not_a_table(tmp_path):
    cfg = load_config(path=_write(tmp_path, 'notify = "x"\n'), plugin_root=tmp_path)
    assert cfg.notify_min_seconds == 300
    assert cfg.notes == ("config invalid: notify: must be a table",)


def test_backup_dir(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('[telemetry]\nbackup_dir = "~/Backups/cta"\n')
    c = load_config(cfg)
    assert c.backup_dir == Path("~/Backups/cta").expanduser() and not c.notes


def test_backup_dir_default_and_invalid(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("")
    assert load_config(cfg).backup_dir is None
    cfg.write_text("[telemetry]\nbackup_dir = 5\n")
    c = load_config(cfg)
    assert c.backup_dir is None and any("telemetry.backup_dir" in n for n in c.notes)
