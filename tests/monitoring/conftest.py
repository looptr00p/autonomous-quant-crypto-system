"""Make scripts/monitoring importable from monitoring tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_MONITORING = Path(__file__).resolve().parents[2] / "scripts" / "monitoring"
if str(_SCRIPTS_MONITORING) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_MONITORING))
