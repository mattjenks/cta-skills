import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
for sub in ("hooks", "scripts"):
    path = str(PLUGIN_DIR / sub)
    if path not in sys.path:
        sys.path.insert(0, path)
