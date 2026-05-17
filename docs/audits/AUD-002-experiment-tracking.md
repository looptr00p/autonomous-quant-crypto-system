# AUD-002: Experiment Tracking Layer — Acceptance Audit

**Audit ID:** AUD-002  
**Date:** 2026-05-17  
**Auditor:** Claude Code (acting as Strategic Auditor for record completion)  
**Scope:** OBJ-003 — Minimal Experiment Tracking Layer  
**Objective:** OBJ-003  
**Related handoff:** HND-002

---

## Scope

This audit covers the implementation of the Minimal Experiment Tracking Layer:
- `src/aqcs/experiments/` package (4 modules + `__init__.py`)
- `tests/unit/test_experiment.py` (59 tests)
- `scripts/list_experiments.py` (CLI utility)
- `docs/architecture/experiment-tracking.md`
- Architecture enforcement updates (`test_dependency_boundaries.py`, `test_repo_structure.py`)

---

## Critical blockers

None.

---

## Must fix before continuing

None identified.

---

## Should fix soon

1. **Content-based dataset fingerprinting option** — The current fingerprint uses path + size + mtime_ns. For high-confidence reproducibility, a SHA-256 of file contents would be more reliable. However, for large Parquet files (100+ MB), this is slow. A `fingerprint_file_content(path)` function should be added in Phase 2 and offered as an opt-in parameter to `create_experiment()`.

2. **Tracker does not reload from disk** — `ExperimentTracker.get_experiment()` returns None for experiments loaded from a previous session. The caller must use `load_experiment_json()` directly. This is by design but should be documented more prominently and ideally a `load_experiment()` method should be added to the tracker.

3. **ExperimentStartedEvent reuses backtesting fields** — `symbols`, `timeframe`, `start_date`, `end_date` are populated with dataset_paths/empty strings for non-backtesting experiments. The semantics are slightly wrong. In Phase 2, a more general `GenericExperimentEvent` type should be added to `events.py`.

---

## Nice to have

- Experiment record validation test that verifies field count doesn't silently decrease (guards against refactoring that removes fields)
- `scripts/list_experiments.py` could accept a `--name-filter` argument for basic search
- Git dirty-state detection (`git diff --quiet`) to warn when running experiments on uncommitted changes
- Duration formatting in the CLI (`2h 3m 14s` instead of `7394.0`)

---

## Findings summary

| Area | Status | Notes |
|------|--------|-------|
| ExperimentRecord model | ✓ Accepted | 17 fields, UTC enforced, Pydantic v2 |
| ExperimentStatus enum | ✓ Accepted | 5 statuses match spec |
| Status transitions | ✓ Accepted | Cannot complete/fail a final-state experiment |
| Duration calculation | ✓ Accepted | Computed automatically on completion/failure |
| UTC timestamp enforcement | ✓ Accepted | Naive and non-UTC rejected at construction |
| Git hash capture | ✓ Accepted | Safe subprocess; graceful fallback to "" |
| Dataset fingerprinting | ✓ Accepted | Deterministic, order-independent, cheap |
| JSON storage | ✓ Accepted | Date-partitioned, atomic tmp-then-rename |
| EventBus integration | ✓ Accepted | Optional, no global singleton |
| Architecture boundary | ✓ Accepted | aqcs.experiments → aqcs.utils only |
| No ML frameworks | ✓ Confirmed | No MLflow, W&B, DVC, databases, dashboards |
| No global singleton | ✓ Confirmed | ExperimentTracker is injected, not a module global |
| No live trading | ✓ Confirmed | No exchange calls, no order methods |

---

## Risks / concerns

**Low risk:**
- `mtime_ns` resolution varies by filesystem. On FAT32 or some NFS mounts, mtime is seconds, not nanoseconds. Fast repeated writes could produce matching fingerprints despite different data. Unlikely for market data Parquet files; documented as a Phase 1 limitation.
- The tracker in-memory store and the disk store can diverge if two tracker instances write to the same directory. Since there is no locking, concurrent writes could produce inconsistent state. Single-process batch research eliminates this risk in Phase 1.

---

## Recommendations

1. **Mark OBJ-003 as complete.** All acceptance criteria are met.
2. **File HND-002 as the authoritative handoff** for this implementation.
3. **Before advancing to Phase 2**, conduct a full Phase 1 audit to confirm all OBJ-001 criteria are still met with the expanded codebase (502 tests).
4. Address the "should fix soon" items (content fingerprinting, tracker reload, general experiment events) in the first Phase 2 task.

---

## Go / No-Go verdict

**GO** — OBJ-003 Experiment Tracking is accepted as complete.

The implementation is minimal, deterministic, and correctly scoped to Phase 1. No databases, no cloud, no dashboards, no ML frameworks were introduced. The architecture boundary is enforced. All 502 tests pass.

---

## Final technical verdict

The Experiment Tracking Layer is accepted as Phase 1 complete.

AQCS Phase 1 Foundation Layer (OBJ-001 + OBJ-002 + OBJ-003) is now complete:
- Package structure, config, logging, events, phase guard, event bus ✓
- Data acquisition (OHLCV from Binance Spot) ✓
- Data validation (13-step validator, UTC enforcement, gap detection) ✓
- Experiment tracking (record, tracker, storage, fingerprint) ✓
- Architecture enforcement (DAG, forbidden imports, governance) ✓
- Governance system (MVS, enforcement, operational enforcement) ✓

**502 tests passing. No architectural boundary violations. Ready for Phase 1 closure audit before Phase 2.**

---

## Related documents

- OBJ-003: `docs/objectives/OBJ-003-experiment-tracking.md`
- HND-002: `docs/handoffs/HND-002-experiment-tracking.md`
- ADR-002: `docs/decisions/ADR-002-quant-core-llm-oversight.md`
- ADR-003: `docs/decisions/ADR-003-event-logged-architecture.md`
- `docs/architecture/experiment-tracking.md`
- `tests/unit/test_experiment.py`
