## AI Handoff

### Handoff ID
`HND-014`

### Task ID
`TASK-DATASET-MANIFEST-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-002 Canonical Dataset Manifest System`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Implemented a deterministic canonical dataset identity manifest system for
OHLCV Parquet datasets. Manifests certify dataset identity, enable corruption
detection, detect schema drift, and support future replay certification.

### Branch
`feat/task-dataset-manifest-001`

### Commit
`42bf11b` — TASK-DATASET-MANIFEST-001: add deterministic OHLCV dataset identity manifests

---

### Files Changed

```text
src/aqcs/data/manifest.py          — core module (DatasetManifest, generate_manifest,
                                     verify_manifest, manifest_to_dict/from_dict,
                                     save_manifest/load_manifest)
scripts/data/generate_manifest.py  — click CLI: generate manifest JSON (exit 0/1)
scripts/data/verify_manifest.py    — click CLI: verify parquet vs manifest (exit 0/1/2)
tests/data/test_manifest.py        — 60 tests across 11 test classes
docs/bitacora/2026-05-18-HND-014-dataset-manifest-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, backtesting, research, features, signals, llm_oversight,
execution, risk, portfolio, governance tests, architecture tests, CI config,
dependency files — untouched.

---

## Manifest Schema

All required fields per spec:

| Field | Type | Notes |
|---|---|---|
| `manifest_version` | `str` | Always `"1"` |
| `exchange` | `str` | From first row of data |
| `symbol` | `str` | Caller-supplied |
| `timeframe` | `str` | Caller-supplied |
| `timezone` | `str` | Always `"UTC"` |
| `row_count` | `int` | Total rows |
| `start_timestamp_utc` | `str` | ISO-8601 |
| `end_timestamp_utc` | `str` | ISO-8601 |
| `schema_hash` | `str` | SHA-256 hex (64 chars) |
| `content_hash` | `str` | SHA-256 hex (64 chars) |
| `duplicate_count` | `int` | Duplicate timestamp count |
| `missing_interval_summary` | `dict` | `{"count": N}` or `{"count": N, "first_gap_utc": ..., "last_gap_utc": ...}` |
| `generation_timestamp_utc` | `str` | ISO-8601, injectable via `now_utc` |

---

## Hashing Strategy

### content_hash
SHA-256 over a canonical byte sequence built from the sorted (by timestamp) dataset:

1. `row_count` as little-endian uint64 — length-extension guard
2. `timestamp` column as int64 milliseconds since UTC epoch, little-endian  
   (normalized via `numpy.asarray(series, dtype="datetime64[ms]").view(int64)` —
   independent of pandas internal datetime resolution: `ms` or `ns`)
3. `open`, `high`, `low`, `close`, `volume` columns each as float64 little-endian

Metadata columns (`symbol`, `timeframe`, `exchange`) are excluded — they are
already captured in the manifest fields.

### schema_hash
SHA-256 of a JSON-serialized list of `(column_name, arrow_type_string)` pairs,
sorted lexicographically by column name. Reads only the Parquet file footer
(no row-data I/O). Arrow type strings (e.g. `"timestamp[ms, tz=UTC]"`, `"double"`,
`"string"`) are stable across Arrow versions.

---

## Determinism Validation

| Property | Implementation |
|---|---|
| Row order invariance | DataFrame sorted by timestamp before hashing |
| Byte stability | All numeric data normalized to `<i8` / `<f8` little-endian |
| Length extension protection | Row count prefixed as fixed 8-byte uint64 |
| Timestamp precision independence | Normalized to `datetime64[ms]` via numpy, then `view(int64)` |
| Schema drift sensitivity | Any added/removed/retyped column changes `schema_hash` |
| Corruption sensitivity | Any changed OHLCV value changes `content_hash` |
| Timezone safety | Naive or non-UTC timestamps raise `ValueError` before hashing |
| JSON output stability | `json.dumps(..., sort_keys=True)` enforced |
| `generation_timestamp_utc` | Wall-clock time; testable via `now_utc` injection |

---

## Architecture Boundary

`aqcs.data.manifest` is in `aqcs.data` which is allowed to import from
`aqcs.utils` and stdlib only. The manifest module imports:
- `aqcs.data.validator.REQUIRED_COLUMNS` (within same package — allowed)
- `hashlib`, `json`, `dataclasses`, `datetime`, `pathlib`, `typing` (stdlib)
- `numpy`, `pandas`, `pyarrow.parquet` (already declared dependencies)

Architecture boundary tests pass (40 tests in `tests/architecture/`).

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/data/test_manifest.py -q --no-cov
# 60 passed in 1.12s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1050 passed in 4.53s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 90 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 37 source files
```

## Test Coverage Summary

| Class | Tests | What is verified |
|---|---|---|
| `TestGenerateManifest` | 5 | All required fields, start<end, row_count, UTC, default now_utc |
| `TestContentHash` | 8 | Deterministic, shuffle-invariant, 3 value corruptions, extra row, timestamp shift, hex format |
| `TestSchemaHash` | 3 | Deterministic, added column, removed column |
| `TestSerialization` | 7 | Round-trip dict, deterministic JSON, JSON serializable, save/load, bad JSON, missing field, immutable |
| `TestVerifyManifest` | 4 | Clean pass, content corruption, schema drift, row count change, expected/actual in mismatch |
| `TestUTCEnforcement` | 2 | Naive rejected, UTC accepted |
| `TestEdgeCases` | 7 | Missing file, empty dataset, missing column, invalid parquet, dup count 0, dup count nonzero, 1-row |
| `TestMissingIntervals` | 5 | No gaps, single gap, multiple gaps, unsupported timeframe → 0, hourly gap |
| `TestDeterministicReplay` | 3 | Two independent calls identical, JSON replay identical, stable after save/load |
| `TestCLIGenerate` | 5 | Exit 0 + valid JSON, exit 1 naive timestamps, exit 1 missing cols, writes to file, rejects bad timeframe |
| `TestCLIVerify` | 4 | Exit 0 clean, exit 1 corruption, exit 2 bad manifest, output includes paths |
| `TestIntegration` | 5 | Real BTC/USDT 1d: generates, is deterministic, verifies self, stable JSON, UTC ISO-8601 bounds |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (37 source files) | PASS |
| pytest manifest (60 tests) | PASS |
| pytest full suite (1050 tests) | PASS |
| Architecture boundary (40 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies introduced | PASS |

---

## Risks

- `pq.read_schema` is untyped in pyarrow's stubs → suppressed with
  `# type: ignore[no-untyped-call]`. No runtime impact.
- `_TIMEFRAME_TO_FREQ["1d"]` uses `"1D"` which emits a pandas 3.x
  FutureWarning. Does not affect correctness or test results. Same issue
  exists in `aqcs.monitoring.data_quality` and `aqcs.data.validator`.
  Follow-up chore: update all three to `"D"` (pandas 2.2+ recommended alias).
- `generation_timestamp_utc` is wall-clock time in the CLI; not injectable
  without `--now-utc` flag (not implemented). Advisory only — the
  deterministic fields are `content_hash` and `schema_hash`.

## Unresolved Issues

None blocking merge.

## Rollback Notes

Delete `src/aqcs/data/manifest.py`, `scripts/data/generate_manifest.py`,
`scripts/data/verify_manifest.py`, `tests/data/test_manifest.py`, and
this handoff file. No database, config, or phase guard changes. No
existing files were modified.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master (`05d8f9e`)
- [x] No forbidden files modified
- [x] No existing files modified
- [x] Architecture boundary preserved
- [x] No new dependencies introduced
- [x] black / ruff / mypy pass
- [x] 60 manifest tests pass
- [x] 1050 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
