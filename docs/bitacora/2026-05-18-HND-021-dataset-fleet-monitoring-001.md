## AI Handoff

### Handoff ID
`HND-021`

### Task ID
`TASK-DATASET-FLEET-MONITORING-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-007 Dataset Fleet Monitoring`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Implemented deterministic dataset fleet monitoring snapshots.
Each snapshot captures the full local dataset registry state, hashes it
deterministically, and supports longitudinal comparison against prior
snapshots to detect data drift, freshness degradation, and registry
consistency changes.

### Branch
`feat/task-dataset-fleet-monitoring-001`

### Commit
`540a3dc` — TASK-DATASET-FLEET-MONITORING-001: add deterministic fleet monitoring snapshots

---

### Files Changed

```text
src/aqcs/data/dataset_registry.py         — copied from PR #12 (prerequisite)
src/aqcs/monitoring/fleet_monitoring.py   — core fleet monitoring module
scripts/monitoring/build_fleet_snapshot.py  — CLI: scan + build snapshot JSON
scripts/monitoring/compare_fleet_snapshots.py — CLI: compare two snapshots
tests/monitoring/test_fleet_monitoring.py  — 46 tests
docs/bitacora/2026-05-18-HND-021-dataset-fleet-monitoring-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

### PR #10–14 status note

PRs #10–14 were all still open at implementation time. `src/aqcs/data/dataset_registry.py`
(from PR #12) was copied directly onto this branch since it is purely additive
(no conflict with master). The fleet monitoring module depends on `scan_directory`
from that module.

---

## Snapshot Schema

**`FleetSnapshotEntry`** (frozen dataclass — per dataset):

| Field | Type | Notes |
|---|---|---|
| `dataset_path` | `str` | Relative to data_dir |
| `manifest_path` | `str \| None` | Relative to data_dir; None if missing |
| `exchange` | `str` | From manifest or parquet metadata |
| `symbol` | `str` | ccxt format (e.g. "BTC/USDT") |
| `timeframe` | `str` | e.g. "1h" |
| `row_count` | `int` | |
| `start_timestamp_utc` | `str` | ISO-8601 |
| `end_timestamp_utc` | `str` | ISO-8601 |
| `content_hash` | `str` | SHA-256 from manifest; `""` if no manifest |
| `schema_hash` | `str` | SHA-256 from manifest; `""` if no manifest |
| `manifest_verified` | `bool` | True only when verification was requested and passed |

**`FleetSnapshot`** (frozen dataclass — fleet-level):

| Field | Type | Notes |
|---|---|---|
| `snapshot_version` | `str` | Always `"1"` |
| `generation_timestamp_utc` | `str` | ISO-8601; injectable via `now_utc` |
| `registry_hash` | `str` | SHA-256 of full registry state |
| `registry_entries_hash` | `str` | SHA-256 of path + content_hash pairs only |
| `total_datasets` | `int` | |
| `total_manifests` | `int` | |
| `symbols` | `tuple[str, ...]` | Sorted |
| `timeframes` | `tuple[str, ...]` | Sorted |
| `datasets_by_symbol` | `dict[str, int]` | |
| `datasets_by_timeframe` | `dict[str, int]` | |
| `orphan_manifest_count` | `int` | |
| `duplicate_identity_count` | `int` | |
| `issue_count` | `int` | |
| `issues` | `tuple[str, ...]` | All registry issue strings |
| `snapshot_entries` | `tuple[FleetSnapshotEntry, ...]` | Sorted by (symbol, timeframe, path) |

**`FleetDrift`** (frozen dataclass — comparison result):

| Field | Type | Notes |
|---|---|---|
| `baseline_timestamp_utc` | `str` | From baseline snapshot |
| `candidate_timestamp_utc` | `str` | From candidate snapshot |
| `added_datasets` | `tuple[str, ...]` | Paths in candidate but not baseline |
| `removed_datasets` | `tuple[str, ...]` | Paths in baseline but not candidate |
| `modified_datasets` | `tuple[str, ...]` | Paths in both but content_hash changed |
| `freshness_changes` | `tuple[FreshnessChange, ...]` | end_timestamp changed |
| `new_issues` | `tuple[str, ...]` | Issues in candidate not in baseline |
| `resolved_issues` | `tuple[str, ...]` | Issues in baseline not in candidate |
| `has_drift` | `bool` | True when added/removed/modified/new_issues non-empty |
| `summary` | `str` | Human-readable one-line summary |

---

## Determinism Strategy

| Property | Implementation |
|---|---|
| Entry ordering | Inherited from registry: sorted by (symbol, timeframe, path) |
| registry_hash | SHA-256 of JSON {total_datasets, issues, orphans, duplicates, entries} with sort_keys |
| registry_entries_hash | SHA-256 of [{path, content_hash}] sorted by path |
| Comparison ordering | All paths union sorted lexicographically |
| Drift list ordering | added/removed/modified all use `sorted()` |
| Wall-clock independence | only `generation_timestamp_utc` uses wall clock; injected in tests |
| JSON output | `json.dumps(..., sort_keys=True, indent=2)` |
| Two scans of identical directory | produce identical FleetSnapshot |

---

## Drift Detection Logic

`compare_snapshots(baseline, candidate)`:

1. Index entries by `dataset_path` in both snapshots
2. Union all paths; iterate in sorted order
3. Path only in candidate → **added**
4. Path only in baseline → **removed**
5. Path in both:
   - `content_hash` changed → **modified**
   - `end_timestamp_utc` changed → **freshness_change** (direction: "updated" or "truncated")
6. Issue set difference: candidate − baseline → **new_issues**
7. Issue set difference: baseline − candidate → **resolved_issues**
8. `has_drift = bool(added or removed or modified or new_issues)`

---

## CLI Behavior

**`build_fleet_snapshot.py`**
```bash
PYTHONPATH=src python scripts/monitoring/build_fleet_snapshot.py \
  --data-dir data/burn_in/ \
  --output-json data/fleet/fleet_snapshot.json
```
- Exit 0: no issues
- Exit 1: issues in registry
- Exit 2: invalid args / unreadable dir

**`compare_fleet_snapshots.py`**
```bash
PYTHONPATH=src python scripts/monitoring/compare_fleet_snapshots.py \
  --baseline data/fleet/fleet_snapshot_v1.json \
  --candidate data/fleet/fleet_snapshot_v2.json
```
- Exit 0: no drift
- Exit 1: drift or new issues detected
- Exit 2: snapshot file unreadable or malformed

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/monitoring/test_fleet_monitoring.py -q --no-cov
# 46 passed in 1.75s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1178 passed in 6.67s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 99 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 40 source files
```

## Test Coverage Summary

| Class | Tests | What is verified |
|---|---|---|
| `TestSnapshotGeneration` | 11 | Empty dir, single/multiple entries, timestamp injection, symbols sorted, by_symbol, manifest count, issues, orphan, duplicate |
| `TestSnapshotHashing` | 5 | Deterministic, changes on data mod, entries hash format, changes on new issue, two scans identical |
| `TestDriftDetection` | 6 | No drift, dataset added, dataset removed, content modified, added sorted, removed sorted |
| `TestFreshnessChanges` | 3 | Updated, truncated, unchanged |
| `TestIssuePropagation` | 3 | New issue, resolved issue, orphan in issues |
| `TestSerialization` | 7 | Round-trip dict, JSON deterministic, save/load, invalid JSON, missing field, immutable, drift dict |
| `TestCLIBuild` | 5 | Exit 0, exit 1, writes JSON, stdout JSON, nonexistent dir |
| `TestCLICompare` | 4 | Exit 0, exit 1, exit 2, required fields |
| `TestTimezoneValidation` | 1 | Naive timestamp recorded as issue |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (40 source files) | PASS |
| pytest fleet monitoring (46 tests) | PASS |
| pytest full suite (1178 tests) | PASS |
| Architecture boundary (41 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies introduced | PASS |
| No database, scheduler, or daemon | PASS |
| No filesystem mutation | PASS |

---

## Risks

- `src/aqcs/data/dataset_registry.py` is duplicated from PR #12 (not yet merged to master). When PR #12 is merged, this file will exist in two branches with identical content. The merge must be ordered: PR #12 first, then this PR rebases. Or this file is removed from this branch before merging if PR #12 merges first.
- Fleet monitoring depends on `aqcs.monitoring` → `aqcs.data` (dataset_registry). This is within the allowed DAG (`aqcs.monitoring: {aqcs.data, aqcs.utils}`). ✓
- Two trailing spaces in Markdown header retained from architecture doc style — not relevant here.

## Unresolved Issues

- PRs #10–14 still open. This PR includes `dataset_registry.py` from PR #12.
  Recommended merge order: PR #12 → this PR (rebase to remove the duplicate file).
  Or: merge both simultaneously — no conflict since PR #12 doesn't exist on master yet.

## Rollback Notes

Delete 4 new files + `src/aqcs/data/dataset_registry.py` if it was added from PR #12.
No existing files modified. No DB or config changes.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master
- [x] PRs #10-14 noted as open; dataset_registry.py included from PR #12
- [x] No forbidden files modified
- [x] No existing files modified
- [x] No new dependencies introduced
- [x] Architecture boundary preserved (aqcs.monitoring → aqcs.data ✓)
- [x] black / ruff / mypy pass
- [x] 46 fleet monitoring tests pass
- [x] 1178 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
