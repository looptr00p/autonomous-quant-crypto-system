# AI Handoff

## Handoff ID
HND-002

## Task ID
TASK-002 — Implement OBJ-003 Experiment Tracking Layer

## Objective
OBJ-003 — Experiment Tracking

## Agent
Claude Code (claude-sonnet-4-6)

## Date
2026-05-17

## Status
Complete

---

## What was changed

Implemented the Minimal Experiment Tracking Layer for AQCS Phase 1.

The package `src/aqcs/experiments/` was created with four modules:
- **`models.py`** — `ExperimentRecord` (Pydantic, 17 fields, UTC-enforced timestamps, mutable for status transitions) and `ExperimentStatus` enum (CREATED/RUNNING/COMPLETED/FAILED/CANCELLED)
- **`fingerprint.py`** — `get_git_commit_hash()` (safe subprocess, graceful fallback) and `fingerprint_dataset()` (path + size + mtime_ns → SHA-256, deterministic, order-independent)
- **`storage.py`** — `save_experiment_json()` (atomic tmp-then-rename, date-partitioned), `load_experiment_json()`, `list_experiments()`
- **`tracker.py`** — `ExperimentTracker` (no global singleton, optional EventBus, create/complete/fail/save API)

Architecture enforcement was updated: `aqcs.experiments` added to `ALLOWED` in `test_dependency_boundaries.py` (imports only from `aqcs.utils`), and backtesting's allowed set was extended to include `aqcs.experiments`.

## Files changed

```
src/aqcs/experiments/__init__.py               — new: package with public exports
src/aqcs/experiments/models.py                 — new: ExperimentRecord, ExperimentStatus
src/aqcs/experiments/fingerprint.py            — new: git hash + dataset fingerprinting
src/aqcs/experiments/storage.py                — new: JSON persistence
src/aqcs/experiments/tracker.py                — new: ExperimentTracker
tests/unit/test_experiment.py                  — new: 59 tests
scripts/list_experiments.py                    — new: CLI listing utility
docs/architecture/experiment-tracking.md       — new: documentation
docs/objectives/OBJ-003-experiment-tracking.md — updated: status Complete
tests/architecture/test_dependency_boundaries.py — updated: aqcs.experiments in DAG
tests/architecture/test_repo_structure.py       — updated: new files in EXPECTED
```

## Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: 502 passed in 2.53s
```

## Verification result

- [x] pytest: 502 passing, 0 failing, 0 skipped
- [x] ruff: 0 errors
- [x] black: 0 violations
- [x] mypy: 0 errors
- [x] architecture tests: passing (aqcs.experiments boundary enforced)
- [x] governance tests: passing
- [x] anti-live-trading tests: passing
- [x] anti-LLM-execution tests: passing
- [x] committed and pushed to origin/master

---

## Decisions made

1. **Lightweight fingerprinting only.** Full content hashing (SHA-256 of file bytes) was considered but rejected for Phase 1. Market data Parquet files can be hundreds of MB. Metadata-based fingerprinting (path + size + mtime_ns) is sufficient for detecting the most common change signals. Content hashing can be added as a separate function in Phase 2 without breaking the existing API.

2. **Mutable records, not immutable.** Status transitions require updating the record. Making the record fully frozen (like events) would require creating a new object for each transition, which complicates the tracker API. The identity fields (ID, name, started_utc, git_hash) are never changed after creation; only status, completed_utc, metrics, artifacts, and duration are updated.

3. **`aqcs.experiments` imports from `aqcs.utils` only.** Even though the tracker could theoretically import from `aqcs.data` (for path utilities), keeping it isolated from the data layer makes the experiments package usable independently and avoids circular dependencies.

4. **ExperimentStartedEvent reused.** The existing event type has backtesting-specific fields (`symbols`, `timeframe`, `start_date`, `end_date`). For generic experiments, these are populated with `dataset_paths` and empty strings. This is acceptable for Phase 1; a more general `GenericExperimentStartedEvent` can be added in Phase 2 if needed.

## Risks / concerns

- The `fingerprint_file` function uses `mtime_ns` from `stat()`. On some filesystems (FAT32, some NFS mounts), mtime resolution is seconds, not nanoseconds. This could cause false matches on very fast successive writes. Acceptable for Phase 1 (Parquet files are not written that fast).
- The tracker holds records in-memory by UUID. If a tracker instance is created, records are saved, then a new tracker instance is created for the same storage directory, the in-memory lookup (`get_experiment()`) returns None. Callers must use `load_experiment_json()` to retrieve historical records. This is by design (no global state).

## Deferred work

- Content-based file fingerprinting (full SHA-256 of Parquet bytes) — Phase 2
- Experiment comparison across runs — Phase 2
- Integration with backtesting engine — Phase 2
- Query interface (filter by tag, date range, status) — Phase 2+
- Remote backup/sync — out of AQCS Phase 1 scope permanently

---

## Recommended next prompt

```
Review the AQCS Phase 1 Foundation Layer and determine the next priority.

Current completed objectives:
- OBJ-001: Foundation Layer (complete)
- OBJ-002: Data Validation Layer (complete)
- OBJ-003: Experiment Tracking (complete)

The repository now has 502 tests passing. Before proceeding to Phase 2
(Feature Engineering, Backtesting Engine), consider:
1. Running a fresh audit of the full Phase 1 implementation.
2. Confirming all Phase 1 acceptance criteria from OBJ-001 are still met.
3. Deciding whether any Phase 1 "should fix soon" items from AUD-001 
   should be addressed before advancing phase.

Read AGENTS.md and docs/ai/AQCS_CONTEXT.md before recommending next steps.
```

## Human approval needed

- [ ] No — OBJ-003 is complete and within the approved Phase 1 roadmap. The next action (audit or phase advancement decision) is a human strategic decision, not a code change requiring prior approval.
