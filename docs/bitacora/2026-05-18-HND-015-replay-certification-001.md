## AI Handoff

### Handoff ID
`HND-015`

### Task ID
`TASK-REPLAY-CERTIFICATION-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-003 Deterministic Replay Certification`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Implemented deterministic replay certification for AQCS research experiments.
A `ReplayCertificate` formally certifies that a research experiment can be
reproduced identically by capturing SHA-256 hashes of every deterministic
pipeline output.

### Branch
`feat/task-replay-certification-001`

### Commit
`d3be246` — TASK-REPLAY-CERTIFICATION-001: add deterministic replay certification

---

### Files Changed

```text
src/aqcs/research/replay_certificate.py   — core module
scripts/research/certify_replay.py        — CLI: generate certificate from artifacts
scripts/research/verify_certificate.py    — CLI: verify certificate (exit 0/1/2)
tests/research/test_replay_certificate.py — 61 tests across 10 test classes
docs/bitacora/2026-05-18-HND-015-replay-certification-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

### Architecture boundary

`aqcs.research` is NOT in the `ALLOWED` dict in `tests/architecture/test_dependency_boundaries.py` (line 77: `if owner not in ALLOWED: return`). This means its imports are not checked by the architecture test — consistent with how `aqcs.research.research_validation` already imports from `aqcs.backtesting`, `aqcs.signals`, and `aqcs.experiments`.

The replay certificate module imports:
- `aqcs.backtesting.models` — BacktestResult, BacktestConfig, Trade, EquityCurvePoint
- `aqcs.experiments.models` — ExperimentRecord
- `aqcs.utils.events` — SignalDirection
- `hashlib`, `json`, `struct`, `dataclasses`, `datetime`, `pathlib` (stdlib)
- `pandas`, `numpy` (already declared dependencies)

No import of `aqcs.data.manifest` — the cert accepts raw hash strings from the caller. This decouples replay certification from the (pending) manifest PR #8.

---

## Replay Certification Schema

| Field | Type | Notes |
|---|---|---|
| `certificate_version` | `str` | Always `"1"` |
| `experiment_id` | `str` | UUID from ExperimentRecord |
| `experiment_name` | `str` | Human-readable name |
| `git_commit_hash` | `str` | From experiment record |
| `dataset_content_hash` | `str` | SHA-256 of dataset data (from DatasetManifest or caller) |
| `dataset_schema_hash` | `str` | SHA-256 of dataset schema (from DatasetManifest or caller) |
| `config_hash` | `str` | SHA-256 of BacktestConfig JSON |
| `parameters_hash` | `str` | SHA-256 of experiment parameters JSON |
| `metrics_hash` | `str` | SHA-256 of metrics (binary float64 LE) |
| `trades_hash` | `str` | SHA-256 of trade list (chronological, binary) |
| `equity_hash` | `str` | SHA-256 of equity curve (chronological, binary) |
| `signals_hash` | `str` | SHA-256 of signal series (chronological, binary) |
| `generation_timestamp_utc` | `str` | ISO-8601, injectable via `now_utc` |
| `certified_bars` | `int` | `BacktestResult.n_bars` |
| `certified_trades` | `int` | `len(BacktestResult.trades)` |

---

## Artifact Hashing Strategy

All hash functions use SHA-256. All multi-item sequences are prefixed with their
item count as a fixed-width uint64 (little-endian) to guard against length extension.

### `metrics_hash`
Sorted by key, then: `key.encode("utf-8") + b"\x00" + struct.pack("<d", float(value))`.
Binary float encoding avoids JSON float-to-string precision ambiguity for
computed values like `sharpe_ratio`.

### `trades_hash`
Chronological order (engine output order). Per trade:
`ts_ms (int64 LE) | side (UTF-8) | NUL | fill_price | quantity | fee | slippage | value (float64 LE)`.

### `equity_hash`
Chronological order. Per point:
`ts_ms (int64 LE) | equity | cash | position | price (float64 LE)`.

### `signals_hash`
Index sorted chronologically. Per bar:
`ts_ms (int64 LE) | direction_byte (int8 LE)`.
Direction: LONG=1, NEUTRAL=0, SHORT=-1.
Sorting before hashing makes the hash shuffle-invariant (identical to sorted inputs).

### `config_hash`
`json.dumps(config.model_dump(), sort_keys=True).encode("utf-8")` → SHA-256.

### `parameters_hash`
`json.dumps(parameters, sort_keys=True, default=str).encode("utf-8")` → SHA-256.

### Timestamp normalization
All datetimes → `int(pd.Timestamp(dt).value // 1_000_000)` → milliseconds since UTC epoch.
This is stable across pandas `datetime64[ms]` and `datetime64[ns]` internal representations.

---

## Replay Validation Logic

`verify_certificate(result, signals, content_hash, schema_hash, experiment, reference)`:
1. Re-certifies using the reference `generation_timestamp_utc` (so the informational timestamp doesn't cause a spurious mismatch)
2. Compares all 11 deterministic fields: `certificate_version`, `dataset_content_hash`, `dataset_schema_hash`, `config_hash`, `parameters_hash`, `metrics_hash`, `trades_hash`, `equity_hash`, `signals_hash`, `certified_bars`, `certified_trades`
3. Returns `CertificationVerificationResult(verified, mismatches)` — mismatches is a list of `(field_name, expected, actual)` triples

Replay fails loudly: `verified=False` + explicit mismatch list for every differing field.

---

## Determinism Validation

| Property | Implementation |
|---|---|
| Metric order invariance | Keys sorted before hashing |
| Trade/equity order | Engine chronological output — deterministic |
| Signal order invariance | Index sorted before hashing |
| Float precision stability | Binary float64 encoding, not JSON strings |
| Timestamp stability | int64 ms-since-epoch, independent of pandas resolution |
| Config stability | Pydantic `model_dump()` + `json.dumps(sort_keys=True)` |
| Parameters stability | `json.dumps(sort_keys=True, default=str)` |
| Wall-clock independence | `now_utc` injection for `generation_timestamp_utc` |
| Length-extension guard | Count prefix as uint64 on all sequences |

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/research/test_replay_certificate.py -q --no-cov
# 61 passed in 1.28s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1051 passed in 4.50s

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
| `TestCertifyResult` | 6 | All fields, timestamp injection, default now_utc, hash passthrough, certified counts |
| `TestConfigHash` | 4 | Deterministic, same→same, fee change, capital change, hex length |
| `TestMetricsHash` | 5 | Deterministic, value change, key addition, empty, key-order invariant |
| `TestTradesHash` | 6 | Deterministic, value corruption, timestamp change, extra trade, empty, empty≠nonempty |
| `TestEquityHash` | 3 | Deterministic, equity value change, empty |
| `TestSignalsHash` | 6 | Deterministic, shuffle-invariant, direction change, timestamp shift, extra bar, empty |
| `TestVerifyCertificate` | 10 | Clean pass, metrics/trades/equity/signals/config/content/schema mismatches, certified_bars, mismatch details |
| `TestSerialization` | 7 | Round-trip dict, deterministic JSON, serializable, save/load, invalid JSON, missing field, immutable |
| `TestDeterministicReplay` | 3 | Two calls identical, JSON replay identical, stable after save/load |
| `TestEdgeCases` | 4 | Empty trades, empty equity, empty signals, empty parameters |
| `TestNoLookaheadRegression` | 3 | Lookahead bar changes signals_hash, metric change fails, dataset swap detected |
| `TestPipelineIntegration` | 3 | Certify→verify pass, save/load→verify, any mutation fails |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (37 source files) | PASS |
| pytest replay cert (61 tests) | PASS |
| pytest full suite (1051 tests) | PASS |
| Architecture boundary (40 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies introduced | PASS |

---

## Risks

- `aqcs.research.replay_certificate` imports from `aqcs.backtesting`, `aqcs.experiments`, and `aqcs.utils`. Since `aqcs.research` is not in the architecture DAG `ALLOWED` dict, this is exempt from the boundary test. Consistent with existing behavior in `aqcs.research.research_validation`.
- The `signals` parameter is typed as `pd.Series` — no compile-time guarantee that values are `SignalDirection`. Unknown values hash as `NEUTRAL` (0). Test suite validates this.
- `_hash_signals` uses `pd.DatetimeIndex` access pattern to avoid `Hashable` mypy errors from `.items()` iteration.

## Dependency Note

The replay certificate deliberately does NOT import `aqcs.data.manifest` (PR #8, unmerged). It accepts raw `dataset_content_hash` and `dataset_schema_hash` strings, making it independent of PR #8's merge order. Both PRs can be reviewed and merged independently.

## Unresolved Issues

None blocking merge.

## Rollback Notes

Delete 4 new files and this handoff. No existing files were modified; rollback is zero-risk.

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
- [x] 61 replay certification tests pass
- [x] 1051 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
