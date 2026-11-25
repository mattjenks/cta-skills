from pathlib import Path

import pytest

from learn_config import Delivery, LearnConfig, learn_dir, load_learn_config


def _write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_defaults_without_learn_section(tmp_path):
    cfg = load_learn_config(_write(tmp_path, f'kb = "{tmp_path}"\n'))
    assert cfg.kb == tmp_path
    assert cfg.exclude_organization_ids == ()
    assert cfg.min_sessions == 3
    assert cfg.delivery.to is None
    assert cfg.delivery == Delivery(None)
    assert cfg.notes == ()


def test_reads_learn_and_delivery(tmp_path):
    path = _write(tmp_path, f'''kb = "{tmp_path}"
[learn]
exclude_organization_ids = ["org-a"]
exclude_owners = ["Corp"]
fallback_repo = "me/kb"
kb_dir = "projects/x/learn"
[learn.delivery]
to = "owner@example.test"
''')
    cfg = load_learn_config(path)
    assert cfg.exclude_organization_ids == ("org-a",)
    assert cfg.exclude_owners == ("Corp",)
    assert cfg.fallback_repo == "me/kb"
    assert cfg.kb_dir == "projects/x/learn"
    assert cfg.delivery.to == "owner@example.test"
    assert cfg.notes == ()
    assert learn_dir(cfg) == tmp_path / "projects/x/learn"


def test_leftover_organization_ids_key_notes_rename_and_is_ignored(tmp_path):
    cfg = load_learn_config(_write(tmp_path, f'''kb = "{tmp_path}"
[learn]
organization_ids = ["org-a"]
'''))
    assert cfg.exclude_organization_ids == ()
    assert len(cfg.notes) == 1
    assert "organization_ids" in cfg.notes[0] and "exclude_organization_ids" in cfg.notes[0]


def test_bad_values_note_and_default(tmp_path):
    path = _write(tmp_path, f'''kb = "{tmp_path}"
[learn]
min_sessions = "three"
fallback_repo = "no-slash"
kb_dir = "../escape"
''')
    cfg = load_learn_config(path)
    assert cfg.min_sessions == 3
    assert cfg.fallback_repo is None
    assert cfg.kb_dir == "learn"
    assert len(cfg.notes) == 3
    for key in ("min_sessions", "fallback_repo", "kb_dir"):
        assert sum(key in n for n in cfg.notes) == 1, (key, cfg.notes)


def test_repos_from_projects(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cfg = load_learn_config(_write(tmp_path, f'''kb = "{tmp_path}"
[projects]
"{a}" = "alpha"
"{b}" = "beta"
'''))
    assert set(cfg.repos) == {a.resolve(), b.resolve()}


def test_learn_dir_requires_kb():
    with pytest.raises(ValueError):
        learn_dir(LearnConfig(kb=None))
