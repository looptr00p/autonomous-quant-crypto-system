"""Validate handoff records in docs/handoffs/HND-*.md.

These tests run only when handoff records exist. They pass trivially
when the directory is empty (no handoffs have been filed yet).

Required sections in every handoff:
- Handoff ID (HND-NNN)
- Task ID (TASK-NNN)
- Objective (OBJ-NNN)
- Files changed
- Tests run
- Risks
- Recommended next prompt
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_HANDOFFS_DIR = _PROJECT_ROOT / "docs/handoffs"

_HND_FILES = sorted(_HANDOFFS_DIR.glob("HND-*.md"))

REQUIRED_SECTIONS: list[str] = [
    "Handoff ID",
    "Task ID",
    "Objective",
    "Files changed",
    "Tests run",
    "Risks",
    "Recommended next prompt",
]


def test_handoffs_directory_exists() -> None:
    assert _HANDOFFS_DIR.is_dir()


def test_handoffs_readme_exists() -> None:
    assert (
        _HANDOFFS_DIR / "README.md"
    ).is_file(), "docs/handoffs/README.md must exist with naming convention and format docs"


# The following tests are parametrized by handoff file.
# If no HND-*.md files exist, pytest collects zero tests — no failure.


@pytest.mark.parametrize(
    "hnd_file",
    _HND_FILES,
    ids=[f.name for f in _HND_FILES],
)
def test_handoff_has_required_sections(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    assert not missing, (
        f"{hnd_file.name} is missing required sections:\n"
        + "\n".join(f"  - '{s}'" for s in missing)
        + "\nSee docs/ai/HANDOFF_TEMPLATE.md for the required format."
    )


@pytest.mark.parametrize(
    "hnd_file",
    _HND_FILES,
    ids=[f.name for f in _HND_FILES],
)
def test_handoff_has_hnd_id(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    ids_found = re.findall(r"HND-\d+", content)
    assert ids_found, f"{hnd_file.name}: must contain a Handoff ID in HND-NNN format"


@pytest.mark.parametrize(
    "hnd_file",
    _HND_FILES,
    ids=[f.name for f in _HND_FILES],
)
def test_handoff_references_existing_objective(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    obj_refs = set(re.findall(r"OBJ-\d+", content))
    obj_dir = _PROJECT_ROOT / "docs/objectives"
    missing: list[str] = []
    for ref in sorted(obj_refs):
        if not list(obj_dir.glob(f"{ref}-*.md")):
            missing.append(ref)
    assert not missing, (
        f"{hnd_file.name}: references objectives that do not exist: {missing}\n"
        "Create the objective file or correct the reference."
    )


@pytest.mark.parametrize(
    "hnd_file",
    _HND_FILES,
    ids=[f.name for f in _HND_FILES],
)
def test_handoff_references_existing_adrs(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    adr_refs = set(re.findall(r"ADR-\d+", content))
    decisions_dir = _PROJECT_ROOT / "docs/decisions"
    missing: list[str] = []
    for ref in sorted(adr_refs):
        if not list(decisions_dir.glob(f"{ref}-*.md")):
            missing.append(ref)
    assert not missing, f"{hnd_file.name}: references ADRs that do not exist: {missing}"
