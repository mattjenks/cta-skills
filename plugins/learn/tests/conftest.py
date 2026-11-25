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
