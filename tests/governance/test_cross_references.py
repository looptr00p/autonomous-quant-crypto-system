"""Cross-document consistency checks for governance documents.

Checks:
1. Every agent named in AGENT_ROLES.md appears in agent_registry.yaml (by name).
2. Every ADR-NNN referenced in objective docs exists as a file.
3. OBJ-NNN referenced in objective docs themselves exist.
4. AGENTS.md links to all required canonical governance documents.
5. agent_registry.yaml agents have at least one canonical doc from the governance set.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── Canonical governance docs that AGENTS.md must reference ──────────────────
_AGENTS_MD_REQUIRED_REFS = [
    "docs/ai/AQCS_CONTEXT.md",
    "docs/ai/AGENT_ROLES.md",
    "docs/ai/TASK_PROTOCOL.md",
    "docs/architecture/system-architecture-v1.md",
    "docs/standards/project-standards.md",
    "docs/standards/phase-constraints.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_ids(pattern: str, content: str) -> set[str]:
    return set(re.findall(pattern, content))


# ── 1. Agent roles ↔ registry consistency ────────────────────────────────────

def test_agent_roles_names_match_registry() -> None:
    roles_path = _PROJECT_ROOT / "docs/ai/AGENT_ROLES.md"
    registry_path = _PROJECT_ROOT / "docs/ai/agent_registry.yaml"

    roles_content = _read(roles_path)
    registry = yaml.safe_load(_read(registry_path))

    # Extract ## section names from AGENT_ROLES.md
    role_names = set(re.findall(r"^## (.+)$", roles_content, re.MULTILINE))
    # Remove non-role sections (e.g., "Role index")
    non_role_sections = {"Role index"}
    role_names -= non_role_sections

    registry_names = {a["name"] for a in registry["agents"]}

    missing_in_registry = role_names - registry_names
    missing_in_roles = registry_names - role_names

    assert not missing_in_registry, (
        f"Agents defined in AGENT_ROLES.md but missing from agent_registry.yaml:\n"
        + "\n".join(f"  - '{n}'" for n in sorted(missing_in_registry))
    )
    assert not missing_in_roles, (
        f"Agents in agent_registry.yaml but not defined in AGENT_ROLES.md:\n"
        + "\n".join(f"  - '{n}'" for n in sorted(missing_in_roles))
    )


# ── 2. ADR references in objective docs exist ─────────────────────────────────

def test_adr_references_in_objectives_exist() -> None:
    obj_dir = _PROJECT_ROOT / "docs/objectives"
    decisions_dir = _PROJECT_ROOT / "docs/decisions"
    missing: list[str] = []

    for obj_file in sorted(obj_dir.glob("OBJ-*.md")):
        content = _read(obj_file)
        adr_refs = _find_ids(r"ADR-\d+", content)
        for ref in sorted(adr_refs):
            matching = list(decisions_dir.glob(f"{ref}-*.md"))
            if not matching:
                missing.append(f"  {obj_file.name} → {ref} (no matching file in docs/decisions/)")

    assert not missing, (
        "The following ADR references in objective docs do not resolve to existing files:\n"
        + "\n".join(missing)
    )


# ── 3. OBJ cross-references within objective docs ────────────────────────────

def test_obj_references_within_objectives_exist() -> None:
    obj_dir = _PROJECT_ROOT / "docs/objectives"
    obj_files = {f.stem: f for f in obj_dir.glob("OBJ-*.md")}
    missing: list[str] = []

    for obj_file in sorted(obj_dir.glob("OBJ-*.md")):
        content = _read(obj_file)
        # Find references like OBJ-001, OBJ-002, etc.
        refs = _find_ids(r"OBJ-\d+", content)
        # Remove self-reference
        self_id = re.match(r"OBJ-\d+", obj_file.stem)
        if self_id:
            refs.discard(self_id.group())

        for ref in sorted(refs):
            matching = list(obj_dir.glob(f"{ref}-*.md"))
            if not matching:
                missing.append(
                    f"  {obj_file.name} → {ref} (no matching file in docs/objectives/)"
                )

    assert not missing, (
        "The following OBJ references within objective docs do not resolve to existing files:\n"
        + "\n".join(missing)
    )


# ── 4. AGENTS.md links to canonical governance docs ──────────────────────────

def test_agents_md_links_to_required_docs() -> None:
    agents_content = _read(_PROJECT_ROOT / "AGENTS.md")
    missing = [ref for ref in _AGENTS_MD_REQUIRED_REFS if ref not in agents_content]
    assert not missing, (
        "AGENTS.md does not reference the following required governance documents:\n"
        + "\n".join(f"  - '{ref}'" for ref in missing)
        + "\nAll canonical docs must be listed in the 'Required reading' section of AGENTS.md."
    )


# ── 5. Every canonical doc in registry actually exists ───────────────────────
# (Also tested in test_agent_registry.py — kept here for cross-document framing)

def test_governance_canonical_docs_exist() -> None:
    registry = yaml.safe_load(_read(_PROJECT_ROOT / "docs/ai/agent_registry.yaml"))
    all_docs: set[str] = set()
    for agent in registry["agents"]:
        all_docs.update(agent.get("canonical_docs_to_read", []))

    missing = [doc for doc in sorted(all_docs) if not (_PROJECT_ROOT / doc).is_file()]
    assert not missing, (
        "The following canonical docs referenced across all agents do not exist:\n"
        + "\n".join(f"  - '{doc}'" for doc in missing)
    )
