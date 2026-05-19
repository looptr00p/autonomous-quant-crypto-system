"""Integration test configuration — shared path setup and constants.

All integration tests use deterministic local fixtures only.
No network access.  No wall-clock dependence.  No random state beyond
fixed-seed generators.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

for _scripts_dir in (
    _REPO_ROOT / "scripts" / "research",
    _REPO_ROOT / "scripts" / "data",
):
    if str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))

# Fixed reference timestamp — injected into all artifact generators to ensure
# generation_timestamp_utc is deterministic across runs.
FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
