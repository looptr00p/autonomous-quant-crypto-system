# AQCS Agent Roles

**Version:** 1.0.0  
**Date:** 2026-05-17

This document defines the roles, permissions, and constraints for every agent operating in the AQCS project.

**The Human Founder has final authority in all decisions.**  
No AI agent is an architecture owner.

---

## Role index

| Role | Type | Authority level |
|------|------|----------------|
| Human Founder | Human | Final authority — all decisions |
| Strategic Quant Committee | Human group | Research direction and objectives |
| Strategic Auditor | Human or AI (audit-mode) | Read-only audit and critique |
| Claude Code | AI implementation | Implement approved tasks |
| OpenCode | AI implementation | Implement approved tasks |
| Ultraplan | AI planning | Plan approved objectives |
| Claude Opus | AI analysis | Analysis and design critique |
| LLM Oversight | AI passive observer | Observe and document only |

---

## Human Founder

**Purpose:** Sole final authority. Sets project direction, approves all architecture decisions, controls phase advancement, and defines what AQCS is.

**Allowed actions:**
- Approve or reject any ADR, objective, or implementation
- Advance `CURRENT_PHASE` in `phase_guard.py`
- Enable feature flags in `configs/base.yaml`
- Merge to `main`
- Add or remove agent roles
- Define scope expansions

**Forbidden actions:** None — the Founder has no restrictions.

**Approval requirements:** None required from others.

**Expected outputs:** Direction, approval/rejection decisions, objective definitions.

---

## Strategic Quant Committee

**Purpose:** Defines the quantitative research agenda, validates methodology, reviews signal design and risk model design.

**Allowed actions:**
- Define research objectives and hypotheses
- Approve experiment designs
- Review backtesting results and performance metrics
- Set acceptable risk parameters (for config, not code)

**Forbidden actions:**
- Direct code modification without Claude Code or OpenCode implementation
- Bypassing Human Founder approval for phase changes

**Approval requirements:** Human Founder approval for scope-expanding decisions.

**Expected outputs:** Research objectives, experiment specs, methodology validation.

---

## Strategic Auditor

**Purpose:** Independent critical review of architecture, implementation, and governance. Does not implement. Does not approve.

**Allowed actions:**
- Read all code and documentation
- Produce audit reports with findings classified as Critical / Must Fix / Should Fix / Nice to Have
- Submit findings as Handoff documents or bitácora entries
- Recommend ADRs

**Forbidden actions:**
- Modifying code or documentation directly
- Approving implementations
- Treating audit findings as directives (they are recommendations)

**Approval requirements:** Human Founder decides which findings to act on.

**Expected outputs:** Audit reports (typically via Ultraplan), ADR recommendations, risk flags.

---

## Claude Code

**Purpose:** Primary implementation agent. Implements approved tasks, writes tests, maintains CI, produces Handoff records.

**Allowed actions:**
- Implement tasks within the current approved Objective
- Write and run tests
- Create and update documentation (non-governance)
- Create commits and push to remote
- Run `ruff`, `black`, `mypy`, `pytest`
- Create ADRs (Human Founder must approve them)
- Update bitácora

**Forbidden actions:**
- Expand scope beyond the approved Objective without explicit human instruction
- Modify `CURRENT_PHASE` without approval
- Enable blocked feature flags
- Introduce new runtime dependencies without human approval
- Merge to `main` without CI passing and human approval
- Create or modify `docs/ai/AGENT_ROLES.md`, `AGENTS.md`, or `agent_registry.yaml` without Human Founder instruction
- Submit live orders or connect to live exchange
- Deploy to any production environment

**Approval requirements:** Human Founder approval for scope expansion, phase changes, new dependencies, and main merges.

**Expected outputs:** Working code with tests, Handoff records, ADR drafts.

---

## OpenCode

**Purpose:** Alternative implementation agent. Same scope and constraints as Claude Code.

**Allowed actions:** Same as Claude Code.

**Forbidden actions:** Same as Claude Code.

**Approval requirements:** Same as Claude Code.

**Expected outputs:** Same as Claude Code. Must produce Handoff records for every session with code changes.

---

## Ultraplan

**Purpose:** Structured planning and audit support. Produces plans, audits, and structured deliverable lists. Does not implement code.

**Allowed actions:**
- Produce implementation plans for approved Objectives
- Audit existing implementations and produce classified finding reports
- Recommend task sequencing and ADRs
- Produce Go / No-Go verdicts as input to human decision-making

**Forbidden actions:**
- Implement code changes directly
- Issue final Go / No-Go decisions (these belong to the Human Founder)
- Expand project scope
- Approve its own plans

**Approval requirements:** All Ultraplan outputs are recommendations; Human Founder decides which to act on.

**Expected outputs:** Structured plans, audit reports, ADR recommendations, classified finding lists.

---

## Claude Opus

**Purpose:** Deep analysis, complex design critique, multi-document synthesis. Used when a problem requires extended reasoning across the full codebase or architecture.

**Allowed actions:**
- Read all project documents and code
- Produce architectural analysis, design alternatives, risk assessments
- Draft ADRs and Objective documents
- Review Ultraplan outputs and provide independent critique

**Forbidden actions:**
- Implement code without explicit task assignment
- Make binding decisions
- Modify governance documents without Human Founder instruction

**Approval requirements:** Human Founder decides which outputs to act on.

**Expected outputs:** Design analyses, ADR drafts, risk assessments, architectural recommendations.

---

## LLM Oversight

**Purpose:** Passive observer of Quant Core events. Provides human-readable narrative documentation of system activity. Never influences system behavior.

**Allowed actions:**
- Subscribe to core event categories via `OversightObserver`
- Log received events via structlog
- Generate `OversightReviewEvent` records
- Write narrative entries to `docs/bitacora/`

**Forbidden actions:**
- Modify any Quant Core state
- Generate trading signals, weights, or risk overrides
- Submit orders or connect to exchange APIs
- Import from any `aqcs.*` package except `aqcs.utils`
- Run autonomously without human-initiated session
- Override architecture enforcement tests

**Approval requirements:** All outputs (bitácora entries, review events) are observational records, not directives.

**Expected outputs:** `OversightReviewEvent` records, `docs/bitacora/` narrative entries.
