import sys
from pathlib import Path

# Only scripts/ goes on the path: learn_config finds its own hooks/ copy of cta_config, and
# a hooks/ entry here would shadow core's cta_config in a combined run.
SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


import pytest


@pytest.fixture(autouse=True)
def _isolated_worktree_root(tmp_path_factory, monkeypatch):
    """No test reads or writes the real ~/.local/share/cta/kb-worktrees."""
    import decide
    monkeypatch.setattr(decide, "WORKTREE_ROOT", tmp_path_factory.mktemp("kb-worktrees"))


@pytest.fixture(autouse=True)
def _default_reports_dir_in_tmp(tmp_path_factory, monkeypatch):
    """A LearnConfig built without reports_dir points at a tmp folder, never ~/.local/share/cta.

    Only the constructor default is patched; learn_config.DEFAULT_REPORTS_DIR (what a loaded
    config falls back to) stays real so the config tests can assert it.
    """
    import inspect
    import learn_config
    init = learn_config.LearnConfig.__init__
    names = [n for n, p in inspect.signature(init).parameters.items()
             if p.default is not inspect.Parameter.empty]
    defaults = list(init.__defaults__)
    defaults[names.index("reports_dir")] = tmp_path_factory.mktemp("learn-local")
    monkeypatch.setattr(init, "__defaults__", tuple(defaults))
