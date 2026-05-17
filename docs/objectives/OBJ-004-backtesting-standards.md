# OBJ-004: Backtesting Standards Layer

**Objective ID:** OBJ-004  
**Status:** Complete  
**Phase:** 1  
**Date completed:** 2026-05-17  
**Parent:** OBJ-001

---

## Purpose

Define the institutional standards that govern all future AQCS backtesting before any simulation engine code is written. The goal is to prevent the known failure modes of quantitative research: lookahead bias, survivorship bias, zero-cost assumptions, overfitting to the backtest period, and non-reproducible results.

This objective is intentionally documentation-first. The standards document becomes the mandatory specification that all future implementations must satisfy.

---

## Scope

- `docs/architecture/backtesting-standards.md` — canonical policy document (12 sections)
- `docs/decisions/ADR-005-backtesting-standards-before-engine.md` — rationale
- Governance records (HND-003, AUD-003)
- Lightweight existence tests

Not in scope: backtesting engine implementation, strategy code, metrics computation library, walk-forward framework, execution simulation. These are Phase 2+ deliverables.

---

## Completed deliverables

| Deliverable | File | Notes |
|-------------|------|-------|
| Backtesting standards policy | `docs/architecture/backtesting-standards.md` | 12 sections, mandatory |
| Architecture Decision Record | `docs/decisions/ADR-005-backtesting-standards-before-engine.md` | Rationale + alternatives |
| Objective tracking | `docs/objectives/OBJ-004-backtesting-standards.md` | This file |
| Handoff record | `docs/handoffs/HND-003-backtesting-standards.md` | |
| Audit record | `docs/audits/AUD-003-backtesting-standards.md` | |

---

## Pending deliverables

The following are planned for Phase 2+ and are NOT in scope for OBJ-004:

| Deliverable | Phase | Notes |
|-------------|-------|-------|
| `src/aqcs/backtesting/engine.py` | 2 | Vectorised simulation loop |
| `src/aqcs/backtesting/execution.py` | 2 | Fee + slippage models |
| `src/aqcs/backtesting/metrics.py` | 2 | 11 required metrics from §I |
| `src/aqcs/backtesting/validation.py` | 3 | Walk-forward, OOS, Monte Carlo |
| `tests/unit/test_backtesting_engine.py` | 2 | Unit tests for engine |
| Walk-forward framework | 3 | §J of standards |
| Monte Carlo analysis | 3 | §J of standards |

---

## Acceptance criteria

- [x] `docs/architecture/backtesting-standards.md` exists and covers all 12 sections (A–L)
- [x] Standards document defines forbidden assumptions (§C)
- [x] Standards document defines lookahead bias prevention rules (§D)
- [x] Standards document defines execution timing rules (§E)
- [x] Standards document defines mandatory fee and slippage modelling (§F)
- [x] Standards document defines data standards (§G)
- [x] Standards document defines experiment tracking integration (§H)
- [x] Standards document defines minimum required metrics (§I)
- [x] Standards document declares Phase 1 prohibitions (§K)
- [x] Standards document describes intended future architecture (§L)
- [x] ADR-005 exists with rationale, alternatives, and consequences
- [x] No backtesting engine code introduced
- [x] No scope creep into Phase 2 deliverables

---

## Related ADRs

- ADR-005: Backtesting standards before engine
- ADR-002: Quant Core determinism (backtesting is part of Quant Core)
- ADR-003: Event-logged architecture (experiment events from backtesting)
