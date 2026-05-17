# ADR-004: Implement minimal viable governance before scaling AI agents

**Status:** Accepted  
**Date:** 2026-05-17  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-001

---

## Context

AQCS is developed using multiple AI systems: Claude Code, OpenCode, Ultraplan, Claude Opus, and LLM Oversight. As the number of operational agents grows, the risk of architectural drift, scope creep, inconsistent decisions, and undocumented changes increases proportionally.

Two approaches were considered:
1. Continue with ad-hoc AI collaboration and fix governance issues reactively.
2. Implement a minimal governance layer before scaling agent usage.

## Decision

**AQCS will implement a minimal viable governance system for human + AI collaboration before further scaling the number of operational AI agents.**

The governance system consists of:
- `AGENTS.md` — primary entry point and constraint document for all agents
- `docs/ai/AQCS_CONTEXT.md` — canonical project context
- `docs/ai/AGENT_ROLES.md` — roles, permissions, and forbidden actions per agent
- `docs/ai/TASK_PROTOCOL.md` — task format, ID system, workflow, escalation rules
- `docs/ai/HANDOFF_TEMPLATE.md` — mandatory handoff record format
- `docs/ai/agent_registry.yaml` — static registry (documentation only, not runtime)
- `docs/decisions/ADR-000-template.md` — ADR format
- `docs/objectives/OBJ-*.md` — objective tracking
- `tests/architecture/test_repo_structure.py` — governance file existence checked in CI

**Critical restriction:** This governance system does NOT introduce autonomous agent orchestration, distributed agent systems, vector memory systems, dynamic delegation, or self-modifying agent runtimes. It is a documentation and protocol system for human-supervised AI collaboration.

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Autonomous agent orchestration (e.g., CrewAI, AutoGen) | Not compatible with AQCS's human-as-final-authority principle; adds non-determinism; creates undocumented decision paths |
| Vector memory / RAG for agents | Adds infrastructure complexity; RAG retrieval is non-deterministic; not needed when canonical docs are well-maintained |
| No governance system | Works while one human uses one agent, but fails as team and agent count grow |
| Enterprise policy engine | Overengineered for current scale; requires custom tooling to maintain |

## Consequences

**Positive:**
- Every AI agent has a shared entry point (`AGENTS.md`) and context (`AQCS_CONTEXT.md`)
- Role boundaries are explicit and documented
- Task traceability via IDs (OBJ, TASK, ADR, AUD, HND)
- Handoff records ensure no context is lost between sessions
- Architecture drift is prevented by explicit forbidden actions
- Humans retain final authority at every decision point

**Negative:**
- Agents must read governance docs at the start of each session (overhead)
- Governance docs must be maintained as the project evolves (ongoing effort)
- Protocol adds structure that may feel bureaucratic for simple changes

**Neutral:**
- The governance system is designed to evolve: new agent types can be added to `agent_registry.yaml`, new objectives to `docs/objectives/`, and new ADRs to `docs/decisions/` without changing the protocol itself.

## Related documents

- `AGENTS.md`
- `docs/ai/AQCS_CONTEXT.md`
- `docs/ai/AGENT_ROLES.md`
- `docs/ai/TASK_PROTOCOL.md`
- `docs/ai/HANDOFF_TEMPLATE.md`
- `docs/ai/agent_registry.yaml`
- `docs/bitacora/0006-multi-agent-governance.md`
