# AUD-003: Backtesting Standards Layer — Acceptance Audit

**Audit ID:** AUD-003  
**Date:** 2026-05-17  
**Auditor:** Claude Code (acting as Strategic Auditor for record completion)  
**Scope:** OBJ-004 — Backtesting Standards Layer (documentation-only)  
**Objective:** OBJ-004  
**Related handoff:** HND-003

---

## Scope

This audit covers the documentation-first Backtesting Standards Layer:
- `docs/architecture/backtesting-standards.md` — 12-section policy document
- `docs/decisions/ADR-005-backtesting-standards-before-engine.md`
- `docs/objectives/OBJ-004-backtesting-standards.md`

**Explicitly not in scope:** backtesting engine implementation (none exists — intentionally).

---

## Critical blockers

None.

---

## Must fix before continuing

None identified.

---

## Should fix soon

1. **Structural validation tests for backtesting-standards.md.** Currently, existence checks verify that the file is present. A future governance test should verify that all 12 sections (A–L) exist in the document, similar to how ADR structure is validated. This prevents accidental deletion of critical sections.

2. **Fee and slippage defaults need to be in configs/base.yaml.** Section §F of the standards defines default values (10 bps taker fee, 5 bps slippage) as documentation only. Before any backtesting engine is implemented, these defaults must be added to `configs/base.yaml` under a `backtesting:` key. The engine should read from config, not hardcode these values.

3. **Gap handling policy should be in config.** Section §G defines "halt" as the default gap policy. This should also appear in `configs/base.yaml` so the backtesting engine reads it from config.

---

## Nice to have

- A `backtesting-standards-checklist.md` that a reviewer can use when reviewing a PR that introduces a backtesting engine — a mechanical list of compliance questions
- A test fixture that creates a known-bad backtest (with lookahead) and verifies it would be rejected
- A cross-reference from `system-architecture-v1.md §4.7` (Backtesting Engine) to `backtesting-standards.md` — currently the architecture doc describes the component but not the standards

---

## Findings summary

| Area | Status | Notes |
|------|--------|-------|
| Standards document completeness | ✓ Accepted | 12 sections cover all required content |
| Forbidden assumptions (§C) | ✓ Accepted | 9 explicit prohibitions with rationale |
| Lookahead bias rules (§D) | ✓ Accepted | Signal timestamping, feature availability, cold-start, target leakage |
| Execution timing (§E) | ✓ Accepted | T-close signal → T+1-open execution default |
| Fee and slippage (§F) | ✓ Accepted | Mandatory, conservative defaults, configurable |
| Data standards (§G) | ✓ Accepted | Validated OHLCV only, UTC, fingerprinting, gap policy |
| Experiment tracking (§H) | ✓ Accepted | ExperimentRecord mandatory, required fields defined |
| Metrics (§I) | ✓ Accepted | 11 required metrics, disclaimer on predictive value |
| Validation standards (§J) | ✓ Accepted | Defined as future requirements, not yet implemented |
| Phase 1 prohibitions (§K) | ✓ Accepted | Consistent with Phase Guard and anti-live-trading tests |
| Future architecture (§L) | ✓ Accepted | 4 modules specified, none implemented |
| ADR-005 | ✓ Accepted | Rationale clear, alternatives documented |
| No engine code introduced | ✓ Confirmed | src/aqcs/backtesting/ contains only __init__.py |

---

## Risks / concerns

**Medium risk:**
- The standards are only as good as the enforcement. Until the backtesting engine exists, it is impossible to verify that the engine satisfies §C–§H. The existence of the standards document does not guarantee the engine will implement them correctly — that requires code review against the checklist at implementation time.

**Low risk:**
- Section §J (validation standards — walk-forward, OOS, Monte Carlo) is aspirational. The complexity of correct implementation is high. There is a risk that these techniques are implemented incompletely or incorrectly when Phase 3 begins. Mitigation: treat §J as a specification requiring its own ADR before implementation begins.

---

## Recommendations

1. **Proceed to Phase 1 closure audit.** All Phase 1 objectives (OBJ-001 through OBJ-004) are now complete. A formal Phase 1 closure audit should precede any Phase 2 work.
2. **Add `backtesting:` key to `configs/base.yaml`** in the first Phase 2 task, before any engine code is written.
3. **Treat §J as a Phase 3 specification.** Do not attempt to implement walk-forward or Monte Carlo in Phase 2.
4. **At engine implementation time,** use `backtesting-standards.md` as a PR review checklist. Every section marked "Must" is a mandatory review point.

---

## Go / No-Go verdict

**GO** — OBJ-004 Backtesting Standards is accepted as complete.

The standards document is comprehensive, internally consistent, and correctly scoped. No engine code was introduced. The document satisfies its purpose: providing a non-negotiable specification that constrains future implementation.

---

## Final technical verdict

The Backtesting Standards Layer (documentation phase) is accepted.

AQCS Phase 1 is now complete across all four objectives:
- OBJ-001: Foundation Layer ✓
- OBJ-002: Data Validation Layer ✓
- OBJ-003: Experiment Tracking Layer ✓
- OBJ-004: Backtesting Standards Layer ✓

**540 tests passing. No architectural boundary violations. No live trading pathway. No ML/RL. Documentation-first governance applied correctly.**

A Phase 1 closure audit is recommended before Phase 2 begins.

---

## Related documents

- OBJ-004: `docs/objectives/OBJ-004-backtesting-standards.md`
- HND-003: `docs/handoffs/HND-003-backtesting-standards.md`
- ADR-005: `docs/decisions/ADR-005-backtesting-standards-before-engine.md`
- `docs/architecture/backtesting-standards.md`
- `tests/architecture/test_repo_structure.py`
