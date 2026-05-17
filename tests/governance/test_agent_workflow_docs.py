"""Validate canonical coding-agent workflow governance documentation."""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STANDARD_PATH = _PROJECT_ROOT / "docs/governance/agent_workflow_standard.md"
_AGENTS_PATH = _PROJECT_ROOT / "AGENTS.md"

_REQUIRED_SECTIONS = [
    "AQCS Standard Prompt Footer",
    "Mandatory Git Workflow",
    "Mandatory Commit Discipline",
    "Mandatory Push and PR Workflow",
    "Mandatory Merge Discipline",
    "Required Handoff Content",
    "Required Final Delivery State",
]

_REQUIRED_PHRASES = [
    "Never work directly on master",
    "Human review required before merge",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _markdown_h2_sections(content: str) -> list[str]:
    return re.findall(r"^##\s+(.+?)\s*$", content, flags=re.MULTILINE)


def test_agent_workflow_standard_document_exists() -> None:
    assert _STANDARD_PATH.is_file(), "docs/governance/agent_workflow_standard.md must exist"


def test_agents_md_references_agent_workflow_standard() -> None:
    agents_content = _read(_AGENTS_PATH)
    assert "docs/governance/agent_workflow_standard.md" in agents_content


def test_agent_workflow_standard_has_required_sections() -> None:
    sections = _markdown_h2_sections(_read(_STANDARD_PATH))
    missing = [section for section in _REQUIRED_SECTIONS if section not in sections]
    assert not missing, "Missing required agent workflow sections:\n" + "\n".join(
        f"  - {section}" for section in missing
    )


def test_agent_workflow_standard_protects_required_wording() -> None:
    content = _read(_STANDARD_PATH)
    missing = [phrase for phrase in _REQUIRED_PHRASES if phrase not in content]
    assert not missing, "Missing required governance wording:\n" + "\n".join(
        f"  - {phrase}" for phrase in missing
    )


def test_agent_workflow_doc_parsing_is_deterministic() -> None:
    first_parse = _markdown_h2_sections(_read(_STANDARD_PATH))
    second_parse = _markdown_h2_sections(_read(_STANDARD_PATH))
    assert first_parse == second_parse
    assert first_parse == _REQUIRED_SECTIONS
