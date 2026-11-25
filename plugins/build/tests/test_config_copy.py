from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[2]


def test_config_copies_identical():
    core = (PLUGINS / "core/hooks/cta_config.py").read_bytes()
    build = (PLUGINS / "build/hooks/cta_config.py").read_bytes()
    learn = (PLUGINS / "learn/hooks/cta_config.py").read_bytes()
    assert core == build == learn
