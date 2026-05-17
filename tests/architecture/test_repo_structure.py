"""Verify the expected repository layout exists.

These tests catch regressions where a component is accidentally deleted,
moved, or renamed. They do not test behaviour — only presence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXPECTED_PACKAGES = [
    "src/aqcs/data",
    "src/aqcs/experiments",
    "src/aqcs/features",
    "src/aqcs/signals",
    "src/aqcs/portfolio",
    "src/aqcs/risk",
    "src/aqcs/execution",
    "src/aqcs/backtesting",
    "src/aqcs/monitoring",
    "src/aqcs/llm_oversight",
    "src/aqcs/utils",
]

EXPECTED_FILES = [
    # Source
    "src/aqcs/experiments/tracker.py",
    "src/aqcs/experiments/models.py",
    "src/aqcs/experiments/storage.py",
    "src/aqcs/experiments/fingerprint.py",
    "src/aqcs/features/returns.py",
    "src/aqcs/features/volatility.py",
    "src/aqcs/features/trend.py",
    "src/aqcs/signals/types.py",
    "src/aqcs/signals/momentum.py",
    "src/aqcs/signals/trend.py",
    "src/aqcs/signals/combined.py",
    "src/aqcs/utils/phase_guard.py",
    "src/aqcs/utils/events.py",
    "src/aqcs/utils/event_bus.py",
    "src/aqcs/utils/config.py",
    "src/aqcs/utils/logging.py",
    "src/aqcs/data/ohlcv.py",
    "src/aqcs/data/validator.py",
    "src/aqcs/llm_oversight/observer.py",
    # Architecture docs
    "docs/architecture/system-architecture-v1.md",
    "docs/architecture/event-schema.md",
    "docs/architecture/data-validation.md",
    "docs/architecture/experiment-tracking.md",
    "docs/architecture/backtesting-standards.md",
    # Standards docs
    "docs/standards/project-standards.md",
    "docs/standards/phase-constraints.md",
    # Governance docs
    "AGENTS.md",
    "docs/ai/AQCS_CONTEXT.md",
    "docs/ai/AGENT_ROLES.md",
    "docs/ai/TASK_PROTOCOL.md",
    "docs/ai/HANDOFF_TEMPLATE.md",
    "docs/ai/agent_registry.yaml",
    # Handoff and audit directories
    "docs/handoffs/README.md",
    "docs/audits/README.md",
    # ADR system
    "docs/decisions/ADR-000-template.md",
    # Config
    "pyproject.toml",
    "configs/base.yaml",
    ".env.example",
]


@pytest.mark.parametrize("pkg", EXPECTED_PACKAGES)
def test_package_directory_exists(pkg: str) -> None:
    assert Path(pkg).is_dir(), (
        f"Expected package directory '{pkg}' not found. "
        f"If this component was intentionally removed, update EXPECTED_PACKAGES in this test."
    )


@pytest.mark.parametrize("pkg", EXPECTED_PACKAGES)
def test_package_has_init(pkg: str) -> None:
    init = Path(pkg) / "__init__.py"
    assert init.exists(), (
        f"'{init}' is missing. Every aqcs/ package must have an __init__.py."
    )


@pytest.mark.parametrize("fp", EXPECTED_FILES)
def test_required_file_exists(fp: str) -> None:
    assert Path(fp).is_file(), (
        f"Required file '{fp}' not found. "
        f"If this file was intentionally removed or renamed, update EXPECTED_FILES in this test."
    )
