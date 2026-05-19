## AI Handoff

### Handoff ID
`HND-018`

### Task ID
`TASK-DATASET-REGISTRY-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-006 Deterministic Local Dataset Registry`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Implemented a deterministic local dataset registry system for AQCS.
The registry scans a local directory for OHLCV Parquet files and manifest
JSONs, validates linkage, detects anomalies, and produces a reproducible
inventory. No database, no scheduler, no filesystem mutation.

### Branch
`feat/task-dataset-registry-001`

### Commit
`60850a1` — TASK-DATASET-REGISTRY-001: add deterministic local dataset registry

---

### Files Changed

```text
src/aqcs/data/dataset_registry.py       — core module
scripts/data/build_dataset_registry.py  — CLI: scan + build registry JSON
scripts/data/validate_dataset_registry.py — CLI: validate existing registry
tests/data/test_dataset_registry.py     — 48 tests
docs/bitacora/2026-05-18-HND-018-dataset-registry-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

### PR #10 and #11 status note

PRs #10 (smoke test) and #11 (burn-in) were still open at implementation time.
The registry uses only `aqcs.data.manifest` and `pandas` (both already on
master) — fully independent of PRs #10 and #11.

---

## Registry Schema

**`DatasetRegistryEntry`** (frozen dataclass):

| Field | Type | Source |
|---|---|---|
| `dataset_path` | `str` | Relative to `data_dir` |
| `manifest_path` | `str \| None` | Relative to `data_dir`; None if missing |
| `exchange` | `str` | From manifest or parquet metadata |
| `symbol` | `str` | From manifest or parquet metadata |
| `timeframe` | `str` | From manifest or parquet metadata |
| `row_count` | `int` | From manifest or parquet |
| `start_timestamp_utc` | `str` | ISO-8601 from manifest or parquet |
| `end_timestamp_utc` | `str` | ISO-8601 from manifest or parquet |
| `content_hash` | `str` | SHA-256 from manifest; `""` if no manifest |
| `schema_hash` | `str` | SHA-256 from manifest; `""` if no manifest |
| `manifest_version` | `str` | From manifest; `""` if no manifest |
| `generation_timestamp_utc` | `str` | From manifest; `""` if no manifest |
| `has_manifest` | `bool` | True when manifest file exists and is valid |
| `manifest_verified` | `bool` | True when re-verification passed (`verify_manifests=True`) |

**`DatasetRegistry`** (frozen dataclass):

| Field | Type | Notes |
|---|---|---|
| `registry_version` | `str` | Always `"1"` |
| `data_dir` | `str` | Absolute path of scanned directory |
| `generation_timestamp_utc` | `str` | ISO-8601; injectable via `now_utc` |
| `total_datasets` | `int` | Count of parquet files found |
| `entries` | `tuple[DatasetRegistryEntry, ...]` | Sorted by (symbol, timeframe, path) |
| `orphan_manifests` | `tuple[str, ...]` | Manifest paths with no matching parquet |
| `duplicate_identities` | `tuple[tuple[str, ...], ...]` | Groups sharing same `content_hash` |
| `issues` | `tuple[str, ...]` | All detected anomalies as human-readable strings |

---

## Determinism Strategy

| Property | Implementation |
|---|---|
| Entry ordering | Sorted by `(symbol, timeframe, dataset_path)` |
| Orphan list ordering | `sorted()` |
| Duplicate group ordering | Groups sorted by first element; paths within group sorted |
| Filesystem traversal | `sorted(data_dir.rglob(...))` |
| JSON output | `json.dumps(..., sort_keys=True)` |
| Wall-clock independence | `generation_timestamp_utc` uses injectable `now_utc` |
| Reproducibility guarantee | Two scans of same unchanged directory → identical registry |

---

## Naming Convention

Parquets and manifests are paired by **file stem + suffix**:

```
{stem}.parquet  ←→  {stem}_manifest.json  (same directory)
```

Examples:
- `BTC_USDT_1h.parquet` ↔ `BTC_USDT_1h_manifest.json`
- `ETH_USDT_1h.parquet` ↔ `ETH_USDT_1h_manifest.json`

This is the naming convention used by `scripts/data/run_public_ohlcv_burn_in.py`.
Manifests that do not follow this convention appear as orphans.

---

## Validation Logic

For each parquet:
1. Look for `{stem}_manifest.json` in the same directory
2. If found: load and parse; if malformed → issue + best-effort metadata
3. If not found: issue "Missing manifest"; read parquet for metadata
4. If `verify_manifests=True`: call `verify_manifest(pq, manifest)` → mismatch issues

Registry-level:
5. Any manifest not matched to a parquet → orphan issue
6. Two parquets sharing the same non-empty `content_hash` → duplicate identity issue

---

## CLI Behavior

**`build_dataset_registry.py`**
```bash
PYTHONPATH=src python scripts/data/build_dataset_registry.py \
  --data-dir data/burn_in/ \
  --output-json data/registry/dataset_registry.json
```
- Exit 0: no issues
- Exit 1: issues detected
- Exit 2: invalid args or unreadable dir

**`validate_dataset_registry.py`**
```bash
PYTHONPATH=src python scripts/data/validate_dataset_registry.py \
  --registry-json data/registry/dataset_registry.json
```
- Exit 0: registry is clean
- Exit 1: issues present
- Exit 2: registry file unreadable or malformed

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/data/test_dataset_registry.py -q --no-cov
# 48 passed in 1.10s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1175 passed in 4.96s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 98 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 39 source files
```

## Test Coverage Summary

| Class | Tests | What is verified |
|---|---|---|
| `TestRegistryGeneration` | 8 | Empty dir, single entry, multiple entries, total count, version, timestamp injection, data_dir, relative paths |
| `TestDeterministicOrdering` | 4 | Symbol ordering, two-scan identity, JSON deterministic, orphan sorting |
| `TestMissingManifest` | 3 | Issue recorded, has_manifest=False, parquet metadata still extracted |
| `TestOrphanManifest` | 3 | Detected, relative path, not counted as orphan when matched |
| `TestDuplicateIdentity` | 3 | Identical data flagged, distinct data not flagged, no-manifest not flagged |
| `TestManifestVerification` | 3 | Clean pass, corrupted parquet detected, verify=False skips |
| `TestMalformedManifest` | 2 | Invalid JSON, missing required field |
| `TestTimezoneValidation` | 2 | Naive timestamps issue, UTC no issue |
| `TestSerialization` | 7 | Round-trip dict, JSON serializable, save/load, invalid JSON, missing field, immutable, save creates parent dirs |
| `TestCLIBuild` | 5 | Exit 0 clean, exit 1 issues, writes JSON, stdout JSON, nonexistent dir |
| `TestCLIValidate` | 4 | Exit 0 clean, exit 1 issues, exit 2 malformed, required fields |
| `TestReplayInventory` | 4 | All datasets identified, content_hash stable, UTC timestamps, nested dir discovery |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (39 source files) | PASS |
| pytest registry (48 tests) | PASS |
| pytest full suite (1175 tests) | PASS |
| Architecture boundary (40 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies introduced | PASS |
| No database introduced | PASS |
| No filesystem mutation | PASS |

---

## Risks

- Manifest matching is name-based only (`{stem}_manifest.json`). Manifests at
  non-standard paths appear as orphans. This is intentional and documented.
- `verify_manifests=True` re-reads every parquet — O(n) in total data size.
  For large fleets, this is a slower operation than a plain scan.
- The `manifest_verified` field is `False` when `verify_manifests=False` (the
  default). This does NOT mean the manifest is invalid — it means verification
  was not requested. Callers should consult the flag meaning.

## Unresolved Issues

- PRs #10 and #11 still open. Registry is fully self-contained and independent.
  Recommend merging all pending PRs (#10, #11) before this one.

## Rollback Notes

Delete 4 new files. No existing files were modified. No DB or config changes.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master (`f8692c0`)
- [x] PRs #10/#11 noted as open; registry is independent
- [x] No forbidden files modified
- [x] No existing files modified
- [x] No database introduced
- [x] No new dependencies introduced
- [x] black / ruff / mypy pass
- [x] 48 registry tests pass
- [x] 1175 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
