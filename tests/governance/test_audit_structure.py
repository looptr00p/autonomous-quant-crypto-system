"""Validate audit records in docs/audits/AUD-*.md.

These tests run only when audit records exist. They pass trivially
when the directory is empty (no audits have been filed yet).

Required sections in every audit:
- Audit ID (AUD-NNN)
- Scope
- Findings (at least one classification: Critical blockers | Must fix | Should fix | Nice to have)
- Go / No-Go verdict
- Final technical verdict
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AUDITS_DIR = _PROJECT_ROOT / "docs/audits"

_AUD_FILES = sorted(_AUDITS_DIR.glob("AUD-*.md"))

REQUIRED_SECTIONS: list[str] = [
    "Scope",
    "Go / No-Go",
]

FINDINGS_SECTION_OPTIONS: list[str] = [
    "Critical blockers",
    "Must fix",
    "Should fix",
    "Nice to have",
    "## Findings",
]

VERDICT_SECTION_OPTIONS: list[str] = [
    "Final technical verdict",
    "Final verdict",
    "## Verdict",
]


def test_audits_directory_exists() -> None:
    assert _AUDITS_DIR.is_dir()


def test_audits_readme_exists() -> None:
    assert (
        _AUDITS_DIR / "README.md"
    ).is_file(), "docs/audits/README.md must exist with naming convention and format docs"


# Parametrized tests — pass trivially when no AUD-*.md files exist.


@pytest.mark.parametrize(
    "aud_file",
    _AUD_FILES,
    ids=[f.name for f in _AUD_FILES],
)
def test_audit_has_required_sections(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SECTIONS if s not in content]
    assert not missing, (
        f"{aud_file.name} is missing required sections:\n"
        + "\n".join(f"  - '{s}'" for s in missing)
        + "\nSee docs/audits/README.md for the required format."
    )


@pytest.mark.parametrize(
    "aud_file",
    _AUD_FILES,
    ids=[f.name for f in _AUD_FILES],
)
def test_audit_has_aud_id(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    ids_found = re.findall(r"AUD-\d+", content)
    assert ids_found, f"{aud_file.name}: must contain an Audit ID in AUD-NNN format"


@pytest.mark.parametrize(
    "aud_file",
    _AUD_FILES,
    ids=[f.name for f in _AUD_FILES],
)
def test_audit_has_findings_classification(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    has_findings = any(s in content for s in FINDINGS_SECTION_OPTIONS)
    assert has_findings, (
        f"{aud_file.name}: must contain a findings classification section.\n"
        f"Expected one of: {FINDINGS_SECTION_OPTIONS}"
    )


@pytest.mark.parametrize(
    "aud_file",
    _AUD_FILES,
    ids=[f.name for f in _AUD_FILES],
)
def test_audit_has_verdict(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    has_verdict = any(s in content for s in VERDICT_SECTION_OPTIONS)
    assert has_verdict, (
        f"{aud_file.name}: must contain a verdict section.\n"
        f"Expected one of: {VERDICT_SECTION_OPTIONS}"
    )


@pytest.mark.parametrize(
    "aud_file",
    _AUD_FILES,
    ids=[f.name for f in _AUD_FILES],
)
def test_audit_references_existing_objectives_or_tasks(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    obj_refs = set(re.findall(r"OBJ-\d+", content))
    obj_dir = _PROJECT_ROOT / "docs/objectives"
    missing: list[str] = []
    for ref in sorted(obj_refs):
        if not list(obj_dir.glob(f"{ref}-*.md")):
            missing.append(ref)
    assert not missing, f"{aud_file.name}: references objectives that do not exist: {missing}"
