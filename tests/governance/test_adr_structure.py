"""Validate that every non-template ADR contains the required sections.

Required sections (based on ADR-000-template.md):
- Status:
- Date:
- ## Context
- ## Decision
- ## Alternatives considered
- ## Consequences
- ## Related documents

ADR-000-template.md is excluded from production validation (it is the template itself).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DECISIONS_DIR = _PROJECT_ROOT / "docs/decisions"

REQUIRED_SECTIONS: list[str] = [
    "Status:",
    "Date:",
    "## Context",
    "## Decision",
    "## Alternatives considered",
    "## Consequences",
    "## Related documents",
]

_ADR_FILES = [f for f in sorted(_DECISIONS_DIR.glob("ADR-*.md")) if f.name != "ADR-000-template.md"]


def test_decisions_directory_exists() -> None:
    assert _DECISIONS_DIR.is_dir(), f"decisions directory not found: {_DECISIONS_DIR}"


def test_at_least_one_adr_exists() -> None:
    assert _ADR_FILES, "No ADR files found in docs/decisions/ (excluding template)"


def test_template_exists() -> None:
    assert (
        _DECISIONS_DIR / "ADR-000-template.md"
    ).is_file(), "ADR-000-template.md must exist as the canonical ADR format reference"


@pytest.mark.parametrize(
    "adr_file",
    _ADR_FILES,
    ids=[f.name for f in _ADR_FILES],
)
def test_adr_has_required_sections(adr_file: Path) -> None:
    content = adr_file.read_text(encoding="utf-8")
    missing = [section for section in REQUIRED_SECTIONS if section not in content]
    assert not missing, (
        f"{adr_file.name} is missing required sections:\n"
        + "\n".join(f"  - '{s}'" for s in missing)
        + "\nSee docs/decisions/ADR-000-template.md for the required format."
    )


@pytest.mark.parametrize(
    "adr_file",
    _ADR_FILES,
    ids=[f.name for f in _ADR_FILES],
)
def test_adr_status_is_known_value(adr_file: Path) -> None:
    content = adr_file.read_text(encoding="utf-8")
    valid_statuses = {"Proposed", "Accepted", "Deprecated", "Superseded"}
    found = any(status in content for status in valid_statuses)
    assert found, (
        f"{adr_file.name}: Status must be one of {valid_statuses}. " f"Check the 'Status:' field."
    )
