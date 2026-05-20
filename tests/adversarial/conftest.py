"""Adversarial test shared fixtures and helpers."""

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

FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
