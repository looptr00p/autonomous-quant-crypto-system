# Bitácora — 0006 — Decision: Minimal Multi-Agent Governance

**Date:** 2026-05-17  
**Author:** Human Founder + Claude Code  
**ADR:** ADR-004

---

## Decision

**AQCS will implement a minimal viable governance system for human + AI collaboration before scaling the number of operational AI agents.**

This decision was taken after observing that AQCS is already using multiple AI systems (Claude Code, OpenCode, Ultraplan, Claude Opus, LLM Oversight) without a shared context document, explicit role boundaries, task traceability, or a handoff protocol. As the project grows and more agents are involved, the risk of architectural drift, scope creep, and inconsistent decisions grows proportionally.

---

## What was implemented

### AGENTS.md (root)

Primary entry point for every AI agent. Contains:
- Project identity and current phase
- Official architecture summary
- Non-negotiable constraints (9 rules)
- Forbidden actions table (13 items)
- Required reading list before changes
- Required workflow before implementation
- Verification commands
- Handoff requirement
- Human approval requirement

Every AI agent must read `AGENTS.md` before making any change.

### docs/ai/AQCS_CONTEXT.md

Canonical project context. Summarises purpose, phase, architecture, Quant Core responsibilities, LLM Oversight boundaries, Phase 1 constraints, implemented layers, and next planned layers.

### docs/ai/AGENT_ROLES.md

Defines 8 roles with explicit allowed/forbidden actions and approval requirements:
- Human Founder (final authority)
- Strategic Quant Committee (research direction)
- Strategic Auditor (read-only critique)
- Claude Code (implementation)
- OpenCode (implementation)
- Ultraplan (planning support)
- Claude Opus (deep analysis)
- LLM Oversight (passive observer)

### docs/ai/TASK_PROTOCOL.md

Task format, ID system (OBJ, TASK, ADR, AUD, HND), required workflow, scope control rules, and escalation rules.

### docs/ai/HANDOFF_TEMPLATE.md

Mandatory handoff record for every agent session that modifies the repository. Sections: Handoff ID, Task ID, Objective, what was changed, files changed, tests run, verification result, decisions made, risks, deferred work, recommended next prompt, human approval needed.

### docs/ai/agent_registry.yaml

Static YAML registry of all 8 agents with allowed/forbidden actions and canonical docs. Not loaded at runtime.

### ADR system

- `docs/decisions/ADR-000-template.md` — template
- `docs/decisions/ADR-002-quant-core-llm-oversight.md` — formalises the deterministic/passive boundary
- `docs/decisions/ADR-003-event-logged-architecture.md` — formalises the non-distributed event design
- `docs/decisions/ADR-004-governance-minimal-viable-system.md` — formalises this decision

### Objective tracking

- `docs/objectives/OBJ-001-foundation-layer.md` — complete
- `docs/objectives/OBJ-002-data-validation-layer.md` — complete
- `docs/objectives/OBJ-003-experiment-tracking.md` — planned next

---

## Critical restriction

**AQCS will NOT implement autonomous agent orchestration, distributed agent systems, vector memory systems, dynamic delegation, or self-modifying agent runtimes in this phase.**

The governance system is documentation and protocol. It has no runtime components, no new Python dependencies, and no infrastructure requirements. It is enforced through:
1. `AGENTS.md` — AI agents read it and comply
2. `tests/architecture/test_repo_structure.py` — CI verifies governance files exist
3. Human Founder — final authority on all decisions

---

## Invariants preserved

All project invariants remain unchanged:
- `CURRENT_PHASE = 1` in `phase_guard.py`
- All Phase 1 feature flags remain `false` in `configs/base.yaml`
- Architecture enforcement tests still pass
- No new Python runtime dependencies added
- No autonomous trading logic introduced

---

*Bitácora 0006 — AQCS v0.1.0 — 2026-05-17*
