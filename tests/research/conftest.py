"""Make scripts/research importable from research tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_RESEARCH = Path(__file__).resolve().parents[2] / "scripts" / "research"
if str(_SCRIPTS_RESEARCH) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_RESEARCH))
