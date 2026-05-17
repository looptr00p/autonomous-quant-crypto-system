# AQCS Experiment Tracking — Phase 1

**Version:** 1.0.0  
**Date:** 2026-05-17  
**Status:** Active  
**Implementation:** `src/aqcs/experiments/`

---

## Goals

The Experiment Tracking Layer provides a minimal, reproducible audit trail for quantitative research runs. Every experiment produces a structured JSON record that captures enough context to reconstruct the run.

Goals, in priority order:
1. **Reproducibility** — record git commit, dataset fingerprint, parameters, Python version, platform
2. **Traceability** — unique IDs, status transitions, timestamps
3. **Auditability** — immutable identity fields, structured JSON, local storage
4. **Simplicity** — no database, no server, no external service

---

## What this is NOT

| Pattern | Why AQCS rejects it |
|---------|-------------------|
| MLflow | Requires a server; adds UI complexity; designed for ML hyperparameter tracking |
| Weights & Biases | Cloud-first; requires API keys; not reproducible in air-gapped environments |
| DVC | Primarily a data versioning tool; different problem |
| SQLite experiment database | Adds a binary format; harder to read/audit without tooling |
| Distributed experiment store | Not needed for single-researcher local workflow |

AQCS is a quantitative research lab, not an ML platform. The tracking system is deliberately minimal.

---

## Scope (Phase 1)

**In scope:**
- Creating experiment records with metadata
- Status transitions: RUNNING → COMPLETED / FAILED
- Local JSON file storage, date-partitioned
- Git commit hash capture
- Lightweight dataset fingerprinting (path + size + mtime)
- EventBus integration (optional)

**Explicitly out of scope:**
- Content-based file hashing (too slow for Phase 1 datasets)
- Experiment comparison across runs
- Hyperparameter search
- Remote storage
- Dashboard or TUI
- Backtesting engine (Phase 2+)
- Strategy optimisation

---

## Storage layout

```
experiments/
  YYYY-MM-DD/
    experiment_<uuid>.json
    experiment_<uuid>.json
    ...
```

Files are named by experiment UUID. Directories are named by the start date (UTC). This layout makes it easy to find recent experiments and avoids naming collisions.

Each experiment produces exactly one file that is overwritten on each status transition (RUNNING → COMPLETED/FAILED). The file always represents the current state.

Writes use tmp-then-rename (atomic on POSIX systems) to prevent partial files.

---

## ExperimentRecord fields

| Field | Type | Purpose |
|-------|------|---------|
| `experiment_id` | UUID | Unique identity |
| `experiment_name` | str | Human-readable name |
| `experiment_type` | str | Category (e.g., "signal_research", "data_quality") |
| `status` | ExperimentStatus | CREATED / RUNNING / COMPLETED / FAILED / CANCELLED |
| `timestamp_started_utc` | datetime (UTC) | When the experiment began |
| `timestamp_completed_utc` | datetime (UTC) or None | When it ended |
| `duration_seconds` | float or None | Wall-clock duration |
| `git_commit_hash` | str | HEAD commit at start; empty if unavailable |
| `python_version` | str | `sys.version` |
| `platform` | str | `platform.platform()` |
| `config_path` | str | Path to config file used |
| `dataset_fingerprint` | str | SHA-256 of sorted file fingerprints |
| `dataset_paths` | list[str] | Input data file paths |
| `parameters` | dict[str, Any] | Experiment parameters |
| `metrics` | dict[str, float] | Output metrics (Sharpe, max_dd, etc.) |
| `tags` | list[str] | Searchable labels |
| `notes` | str | Human-readable context |
| `artifacts` | list[str] | Output file paths |

All timestamps are UTC. Naive datetimes are rejected at construction time.

---

## Reproducibility philosophy

An experiment is reproducible if a second researcher can run it from scratch and get the same result. The record provides the inputs needed to attempt reproduction:

1. **git_commit_hash** — exact code version
2. **dataset_fingerprint** — lightweight signal that the data files haven't changed
3. **parameters** — all tunable values
4. **python_version + platform** — environment context (for debugging differences)
5. **config_path** — which configuration was active

This does NOT guarantee reproduction in all cases (external data, random state, time-based logic), but it provides the minimum context for a principled attempt.

---

## Dataset fingerprinting

Phase 1 uses a lightweight fingerprint: **path + file size + mtime_ns → SHA-256**.

This is intentionally cheap:
- Does not hash file contents (too slow for large Parquet files)
- Detects the most common data change signals (file replaced, truncated, or timestamp changed)
- Deterministic given the same file metadata
- Order-independent for multi-file datasets

A change in the underlying data that preserves file size and mtime (rare in practice for downloaded market data) would produce the same fingerprint. This is an accepted limitation for Phase 1.

---

## Git metadata

Git hash capture uses `subprocess.run(["git", "rev-parse", "HEAD"])` with no `shell=True` (no injection risk). If git is unavailable, the function returns an empty string and the experiment continues normally.

**Reproducibility requirement from `project-standards.md §4`:** Before running any experiment intended for the record, verify `git status` shows a clean working tree. An experiment run on modified uncommitted code has a valid git hash but the hash does not capture those modifications.

---

## EventBus integration

The tracker emits three events when an `EventBus` is injected:

| Event | Trigger |
|-------|---------|
| `ExperimentStartedEvent` | `create_experiment()` |
| `ExperimentCompletedEvent` | `complete_experiment()` |
| `ExperimentFailedEvent` | `fail_experiment()` |

The bus is optional. If `None`, no events are emitted and the tracker operates normally. No global bus singleton exists.

---

## API

```python
from pathlib import Path
from aqcs.experiments import ExperimentTracker, ExperimentStatus

tracker = ExperimentTracker(storage_dir=Path("experiments"))

# Create and start an experiment
record = tracker.create_experiment(
    name="btc_momentum_baseline_v1",
    experiment_type="signal_research",
    parameters={"lookback_days": 90, "threshold": 0.02},
    dataset_paths=["data/raw/BTC_USDT_1d.parquet"],
    tags=["baseline", "btc", "momentum"],
    notes="First pass with no transaction costs",
)

# ... run the research logic ...

# Complete with results
tracker.complete_experiment(
    record.experiment_id,
    metrics={"annualised_return": 0.18, "sharpe": 1.4, "max_drawdown": -0.12},
    artifacts=["experiments/2024-01-15/equity_curve.parquet"],
)

# Or fail with a reason
tracker.fail_experiment(record.experiment_id, reason="Data gap at 2024-01-15")
```

---

## Phase 1 limitations

- No content-based file hashing
- No experiment comparison across runs
- No query interface (use `scripts/list_experiments.py` for basic listing)
- No remote backup or sync
- No automatic backtest integration (Phase 2)
- No parameter sweep / grid search
- Tracker holds records in memory only for the session lifetime; load via `load_experiment_json()` for historical records
