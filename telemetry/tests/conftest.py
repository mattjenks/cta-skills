import sys
from pathlib import Path

TELEMETRY_DIR = Path(__file__).resolve().parent.parent
if str(TELEMETRY_DIR) not in sys.path:
    sys.path.insert(0, str(TELEMETRY_DIR))
