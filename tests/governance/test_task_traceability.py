"""Task traceability — cross-reference consistency across governance records.

Since TASK records live in conversations (not files), traceability is
checked through the documents that REFERENCE tasks: handoffs and audits.

Checks:
1. Every HND file that references an OBJ-NNN points to an existing objective.
2. Every AUD file that references an OBJ-NNN points to an existing objective.
3. Every HND file that references an ADR-NNN points to an existing ADR.
4. Every HND file that references another HND-NNN points to an existing handoff.
5. Governance docs directory has README files (index points exist).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_HANDOFFS_DIR = _PROJECT_ROOT / "docs/handoffs"
_AUDITS_DIR = _PROJECT_ROOT / "docs/audits"
_OBJECTIVES_DIR = _PROJECT_ROOT / "docs/objectives"
_DECISIONS_DIR = _PROJECT_ROOT / "docs/decisions"

_HND_FILES = sorted(_HANDOFFS_DIR.glob("HND-*.md"))
_AUD_FILES = sorted(_AUDITS_DIR.glob("AUD-*.md"))


def _find_ids(pattern: str, content: str) -> set[str]:
    return set(re.findall(pattern, content))


def _exists_in(ref: str, directory: Path, glob_prefix: str) -> bool:
    return bool(list(directory.glob(f"{glob_prefix}-*.md")))


# ── 1. Governance index files exist ───────────────────────────────────────────

def test_handoffs_directory_has_readme() -> None:
    assert (_HANDOFFS_DIR / "README.md").is_file()


def test_audits_directory_has_readme() -> None:
    assert (_AUDITS_DIR / "README.md").is_file()


def test_objectives_directory_is_non_empty() -> None:
    obj_files = list(_OBJECTIVES_DIR.glob("OBJ-*.md"))
    assert obj_files, "docs/objectives/ must contain at least one OBJ-*.md file"


def test_decisions_directory_has_template() -> None:
    assert (_DECISIONS_DIR / "ADR-000-template.md").is_file()


# ── 2. HND cross-references ───────────────────────────────────────────────────
# Parametrized on HND files — passes trivially if no handoffs exist.

@pytest.mark.parametrize("hnd_file", _HND_FILES, ids=[f.name for f in _HND_FILES])
def test_hnd_obj_refs_resolve(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    refs = _find_ids(r"OBJ-\d+", content)
    missing = [r for r in sorted(refs) if not list(_OBJECTIVES_DIR.glob(f"{r}-*.md"))]
    assert not missing, (
        f"{hnd_file.name}: OBJ references not found in docs/objectives/: {missing}"
    )


@pytest.mark.parametrize("hnd_file", _HND_FILES, ids=[f.name for f in _HND_FILES])
def test_hnd_adr_refs_resolve(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    refs = _find_ids(r"ADR-\d+", content)
    missing = [r for r in sorted(refs) if not list(_DECISIONS_DIR.glob(f"{r}-*.md"))]
    assert not missing, (
        f"{hnd_file.name}: ADR references not found in docs/decisions/: {missing}"
    )


@pytest.mark.parametrize("hnd_file", _HND_FILES, ids=[f.name for f in _HND_FILES])
def test_hnd_hnd_refs_resolve(hnd_file: Path) -> None:
    content = hnd_file.read_text(encoding="utf-8")
    own_id = re.match(r"HND-\d+", hnd_file.name)
    refs = _find_ids(r"HND-\d+", content)
    if own_id:
        refs.discard(own_id.group())  # self-references are fine
    missing = [r for r in sorted(refs) if not list(_HANDOFFS_DIR.glob(f"{r}-*.md")) and
               not list(_HANDOFFS_DIR.glob(f"*{r}*.md"))]
    assert not missing, (
        f"{hnd_file.name}: HND references not found in docs/handoffs/: {missing}"
    )


# ── 3. AUD cross-references ───────────────────────────────────────────────────
# Parametrized on AUD files — passes trivially if no audits exist.

@pytest.mark.parametrize("aud_file", _AUD_FILES, ids=[f.name for f in _AUD_FILES])
def test_aud_obj_refs_resolve(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    refs = _find_ids(r"OBJ-\d+", content)
    missing = [r for r in sorted(refs) if not list(_OBJECTIVES_DIR.glob(f"{r}-*.md"))]
    assert not missing, (
        f"{aud_file.name}: OBJ references not found in docs/objectives/: {missing}"
    )


@pytest.mark.parametrize("aud_file", _AUD_FILES, ids=[f.name for f in _AUD_FILES])
def test_aud_adr_refs_resolve(aud_file: Path) -> None:
    content = aud_file.read_text(encoding="utf-8")
    refs = _find_ids(r"ADR-\d+", content)
    missing = [r for r in sorted(refs) if not list(_DECISIONS_DIR.glob(f"{r}-*.md"))]
    assert not missing, (
        f"{aud_file.name}: ADR references not found in docs/decisions/: {missing}"
    )
