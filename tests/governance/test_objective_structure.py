"""Validate that every OBJ-*.md contains required sections and metadata.

Required content:
- Objective ID (OBJ-NNN pattern)
- Status field
- ## Purpose section
- ## Scope section
- At least one deliverables section (Completed or Pending)
- ## Acceptance criteria section
- Related documents or ADRs section
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OBJECTIVES_DIR = _PROJECT_ROOT / "docs/objectives"

_OBJ_FILES = sorted(_OBJECTIVES_DIR.glob("OBJ-*.md"))

REQUIRED_SECTIONS: list[str] = [
    "## Purpose",
    "## Scope",
    "## Acceptance criteria",
]

DELIVERABLE_SECTION_OPTIONS: list[str] = [
    "## Completed deliverables",
    "## Pending deliverables",
]

RELATED_SECTION_OPTIONS: list[str] = [
    "## Related",
]

VALID_STATUSES: set[str] = {"Complete", "In Progress", "Planned", "Deferred", "Cancelled"}


def test_objectives_directory_exists() -> None:
    assert _OBJECTIVES_DIR.is_dir(), f"Objectives directory not found: {_OBJECTIVES_DIR}"


def test_at_least_one_objective_exists() -> None:
    assert _OBJ_FILES, "No OBJ-*.md files found in docs/objectives/"


@pytest.mark.parametrize(
    "obj_file",
    _OBJ_FILES,
    ids=[f.name for f in _OBJ_FILES],
)
def test_objective_has_required_sections(obj_file: Path) -> None:
    content = obj_file.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    assert not missing, (
        f"{obj_file.name} is missing required sections:\n"
        + "\n".join(f"  - '{s}'" for s in missing)
    )


@pytest.mark.parametrize(
    "obj_file",
    _OBJ_FILES,
    ids=[f.name for f in _OBJ_FILES],
)
def test_objective_has_deliverables_section(obj_file: Path) -> None:
    content = obj_file.read_text(encoding="utf-8")
    has_deliverables = any(s in content for s in DELIVERABLE_SECTION_OPTIONS)
    assert has_deliverables, (
        f"{obj_file.name}: must contain at least one of: "
        f"{DELIVERABLE_SECTION_OPTIONS}"
    )


@pytest.mark.parametrize(
    "obj_file",
    _OBJ_FILES,
    ids=[f.name for f in _OBJ_FILES],
)
def test_objective_has_related_documents_section(obj_file: Path) -> None:
    content = obj_file.read_text(encoding="utf-8")
    has_related = any(s in content for s in RELATED_SECTION_OPTIONS)
    assert has_related, (
        f"{obj_file.name}: must contain a '## Related' section (ADRs or documents)"
    )


@pytest.mark.parametrize(
    "obj_file",
    _OBJ_FILES,
    ids=[f.name for f in _OBJ_FILES],
)
def test_objective_has_objective_id(obj_file: Path) -> None:
    content = obj_file.read_text(encoding="utf-8")
    # Matches "OBJ-001" pattern anywhere in the file
    ids_found = re.findall(r"OBJ-\d+", content)
    assert ids_found, (
        f"{obj_file.name}: must contain an Objective ID in OBJ-NNN format"
    )


@pytest.mark.parametrize(
    "obj_file",
    _OBJ_FILES,
    ids=[f.name for f in _OBJ_FILES],
)
def test_objective_has_status(obj_file: Path) -> None:
    content = obj_file.read_text(encoding="utf-8")
    has_status = any(f"**Status:** {s}" in content for s in VALID_STATUSES)
    assert has_status, (
        f"{obj_file.name}: must contain '**Status:** <value>' where value is one of "
        f"{VALID_STATUSES}"
    )
