# OBJ-003: Experiment Tracking

**Objective ID:** OBJ-003  
**Status:** Planned  
**Phase:** 1  
**Parent:** OBJ-001

---

## Purpose

Create a minimal, reproducible experiment tracking system that records the inputs, parameters, outputs, and metadata of every research run. Every experiment must be reproducible from its recorded context.

This is not an ML experiment tracking system (no MLflow, no Weights & Biases). It is a lightweight, file-based audit trail for quantitative research runs.

---

## Scope

- Experiment record schema (ID, git commit, dataset, symbols, timeframe, parameters, metrics, outputs)
- Experiment runner that captures and persists the record
- Integration with the Event Schema (`ExperimentStartedEvent`, `ExperimentCompletedEvent`, `ExperimentFailedEvent`)
- Storage in `experiments/` as Markdown + optional Parquet for metrics
- Helper to verify experiment reproducibility (same commit + data + params → same result)

Not in scope: ML hyperparameter search, distributed experiment runs, experiment comparison UI, backtesting engine (OBJ-004+).

---

## Pending deliverables

| Deliverable | Files | Notes |
|-------------|-------|-------|
| Experiment record dataclass | `src/aqcs/backtesting/experiment.py` | Schema from `docs/standards/project-standards.md §4` |
| Experiment runner | `src/aqcs/backtesting/runner.py` | Emits ExperimentStartedEvent, captures exceptions |
| Experiment storage | `experiments/<id>/record.md` + `metrics.json` | Human-readable + machine-readable |
| Tests | `tests/unit/test_experiment.py` | No network calls |
| Documentation | `docs/architecture/experiment-tracking.md` | |

---

## Acceptance criteria

- [ ] Every experiment has a unique ID
- [ ] Experiment record includes git commit hash (from `git rev-parse HEAD`)
- [ ] Experiment record includes: symbol universe, timeframe, date range, parameters, metrics, output paths
- [ ] Experiment record is persisted before any output files are written
- [ ] `ExperimentStartedEvent` is emitted at the start
- [ ] `ExperimentCompletedEvent` is emitted with metrics at completion
- [ ] `ExperimentFailedEvent` is emitted with reason on failure
- [ ] Tests verify the record schema and event emission
- [ ] No ML experiment tracking framework added as dependency

---

## Related ADRs

- ADR-002: Quant Core determinism (experiment runner must be deterministic)
- ADR-003: Event-logged architecture (experiment events use the existing EventBus)
