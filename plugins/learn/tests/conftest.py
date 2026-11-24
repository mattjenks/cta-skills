import sys
from pathlib import Path

# Only scripts/ goes on the path: learn_config finds its own hooks/ copy of cta_config, and
# a hooks/ entry here would shadow core's cta_config in a combined run.
SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
