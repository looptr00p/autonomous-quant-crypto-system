# OBJ-003: Experiment Tracking

**Objective ID:** OBJ-003  
**Status:** Complete  
**Phase:** 1  
**Date completed:** 2026-05-17  
**Parent:** OBJ-001

---

## Purpose

Create a minimal, reproducible experiment tracking layer for AQCS. Every experiment run produces a structured JSON record that captures enough context for reproducibility and auditability. This is NOT an ML experiment platform — it is an institutional audit trail for quantitative research.

---

## Scope

- `ExperimentRecord` model with all required metadata fields
- `ExperimentTracker` for creating and transitioning experiment state
- Local JSON storage, date-partitioned, atomic writes
- Git commit hash capture (safe, graceful fallback)
- Lightweight dataset fingerprinting (path + size + mtime → SHA-256)
- Optional EventBus integration
- CLI utility for listing experiments
- Architecture enforcement updated (aqcs.experiments in DAG)

Not in scope: content-based file hashing, experiment comparison, backtesting engine, ML hyperparameter tracking, dashboards, remote storage.

---

## Completed deliverables

| Deliverable | Files | Tests |
|-------------|-------|-------|
| ExperimentRecord model | `src/aqcs/experiments/models.py` | `test_experiment.py::TestExperimentRecord` |
| ExperimentStatus enum | `src/aqcs/experiments/models.py` | `test_experiment.py::TestExperimentStatus` |
| ExperimentTracker | `src/aqcs/experiments/tracker.py` | `test_experiment.py::TestExperimentTracker` |
| Local JSON storage | `src/aqcs/experiments/storage.py` | `test_experiment.py::TestLocalStorage` |
| Dataset fingerprinting | `src/aqcs/experiments/fingerprint.py` | `test_experiment.py::TestDatasetFingerprinting` |
| Git hash capture | `src/aqcs/experiments/fingerprint.py` | `test_experiment.py::TestGitHashCapture` |
| EventBus integration | `tracker.py` + `events.py` | `test_experiment.py::TestEventBusIntegration` |
| Package `__init__.py` | `src/aqcs/experiments/__init__.py` | — |
| CLI listing utility | `scripts/list_experiments.py` | — |
| Architecture enforcement | `test_dependency_boundaries.py` | passing |
| Documentation | `docs/architecture/experiment-tracking.md` | — |

---

## Acceptance criteria

- [x] `ExperimentRecord` has all 17 required fields
- [x] UTC timestamps enforced; naive datetimes rejected
- [x] Non-UTC aware timestamps rejected
- [x] Status transitions: CREATED → RUNNING → COMPLETED/FAILED
- [x] Cannot complete/fail an already-completed/failed experiment
- [x] Duration computed automatically on completion/failure
- [x] Metrics and artifacts stored on completion
- [x] JSON serializable (all fields)
- [x] Local JSON persistence, date-partitioned
- [x] Atomic write via tmp-then-rename
- [x] No .tmp files after successful save
- [x] Roundtrip: save then load produces identical record
- [x] Git hash capture returns string always; empty when git unavailable
- [x] Dataset fingerprint is deterministic and order-independent
- [x] EventBus events emitted: Started, Completed, Failed
- [x] No bus = no error
- [x] Architecture boundary: aqcs.experiments → aqcs.utils only
- [x] `aqcs.experiments` in DAG for `test_dependency_boundaries.py`
- [x] 59 tests passing in `test_experiment.py`
- [x] No databases, no cloud, no dashboards

---

## Related ADRs

- ADR-002: Quant Core determinism (experiment tracker is deterministic; reproducibility is the first goal)
- ADR-003: Event-logged architecture (optional EventBus integration uses existing EventBus)
