"""Validate docs/ai/agent_registry.yaml structure and cross-references.

Checks:
- Required fields present on every agent entry
- agent_id values are unique
- AI agents have non-empty forbidden_actions
- Every canonical doc referenced by each agent actually exists
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _PROJECT_ROOT / "docs/ai/agent_registry.yaml"

REQUIRED_AGENT_FIELDS = [
    "agent_id",
    "name",
    "role",
    "allowed_actions",
    "forbidden_actions",
    "canonical_docs_to_read",
    "requires_human_approval_for",
]

# AI agents (not human roles) must have at least one forbidden action
_AI_AGENT_IDS = {
    "claude-code",
    "opencode",
    "ultraplan",
    "claude-opus",
    "llm-oversight",
    "strategic-auditor",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    with _REGISTRY_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_registry_file_exists() -> None:
    assert _REGISTRY_PATH.is_file(), f"Registry file not found: {_REGISTRY_PATH}"


def test_registry_has_agents_key(registry: dict) -> None:
    assert "agents" in registry, "Registry must have a top-level 'agents' key"


def test_registry_has_at_least_one_agent(registry: dict) -> None:
    assert len(registry["agents"]) >= 1, "Registry must define at least one agent"


@pytest.mark.parametrize("field", REQUIRED_AGENT_FIELDS)
def test_all_agents_have_required_field(registry: dict, field: str) -> None:
    for agent in registry["agents"]:
        assert field in agent, (
            f"Agent '{agent.get('agent_id', '?')}' is missing required field '{field}'"
        )


def test_agent_ids_are_unique(registry: dict) -> None:
    ids = [a["agent_id"] for a in registry["agents"]]
    duplicates = [aid for aid in ids if ids.count(aid) > 1]
    assert not duplicates, f"Duplicate agent_ids found: {set(duplicates)}"


def test_agent_ids_are_non_empty_strings(registry: dict) -> None:
    for agent in registry["agents"]:
        assert isinstance(agent["agent_id"], str) and agent["agent_id"].strip(), (
            f"agent_id must be a non-empty string, got: {agent.get('agent_id')!r}"
        )


def test_ai_agents_have_non_empty_forbidden_actions(registry: dict) -> None:
    for agent in registry["agents"]:
        if agent["agent_id"] in _AI_AGENT_IDS:
            assert agent.get("forbidden_actions"), (
                f"AI agent '{agent['agent_id']}' must have at least one forbidden_action. "
                f"An AI agent without explicit prohibitions is a governance gap."
            )


def test_canonical_docs_referenced_exist(registry: dict) -> None:
    missing: list[str] = []
    for agent in registry["agents"]:
        for doc in agent.get("canonical_docs_to_read", []):
            path = _PROJECT_ROOT / doc
            if not path.is_file():
                missing.append(f"  agent '{agent['agent_id']}' → '{doc}'")
    assert not missing, (
        "The following canonical docs referenced in agent_registry.yaml do not exist:\n"
        + "\n".join(missing)
    )
