# Adversarial Validation Runbook

**Task:** TASK-ADVERSARIAL-VALIDATION-001  
**Phase:** 1B  
**Status:** Implemented

---

## Purpose

This runbook documents the AQCS adversarial validation framework — a suite of
deterministic tests that intentionally injects corruption, contamination, and
mutation into the research pipeline to verify that failures are **loud**,
**auditable**, and **traceable**.

The goal is **falsification**, not proof of correctness.

---

## Running the Adversarial Suite

```bash
# All adversarial tests
PYTHONPATH=src pytest tests/adversarial/ -vv --no-cov

# Individual modules
PYTHONPATH=src pytest tests/adversarial/test_temporal_leakage.py -vv --no-cov
PYTHONPATH=src pytest tests/adversarial/test_timestamp_corruption.py -vv --no-cov
PYTHONPATH=src pytest tests/adversarial/test_manifest_corruption.py -vv --no-cov
PYTHONPATH=src pytest tests/adversarial/test_replay_corruption.py -vv --no-cov
PYTHONPATH=src pytest tests/adversarial/test_canonicalization_drift.py -vv --no-cov
PYTHONPATH=src pytest tests/adversarial/test_walkforward_contamination.py -vv --no-cov
```

---

## Corruption Classes Covered

### 1. Temporal Leakage (`test_temporal_leakage.py`)

| Scenario | How injected | Detection mechanism |
|---|---|---|
| Same-bar execution | Oracle signal using `close[T+1]` at bar T | Metric divergence from clean signal |
| Future close leakage | Signal computed with `close[T+1]` | `_hash_signals` digest changes |
| Rolling-window lookahead | `center=True` rolling mean | Series differs from `center=False`; hash diverges |
| Pre-shifted signal (off-by-one) | Caller shifts timestamps +1 day | Engine double-shifts; metrics change |
| Walk-forward contamination | `center=True` signal_fn in walk-forward | `report_hash` changes |

**Key invariant tested:** The engine's `shift(1)` is the only runtime barrier
against same-bar execution. Contaminated signals leave a detectable footprint
in metric values and signal hashes.

**Known limitation:** AQCS does not reject pre-contaminated signal series at
runtime (it cannot distinguish clean from contaminated without an oracle).
Detection relies on hash comparison between clean and contaminated runs.

---

### 2. Timestamp and Structural Corruption (`test_timestamp_corruption.py`)

| Scenario | Detection mechanism |
|---|---|
| Empty dataset | `validate_ohlcv` rejects with errors |
| Missing columns | `validate_ohlcv` rejects |
| NaN in OHLCV columns | `validate_ohlcv` rejects |
| Naive timestamps | `validate_ohlcv` + `generate_manifest` raise `ValueError` |
| Non-UTC timezone | `validate_ohlcv` + `generate_manifest` raise `ValueError` |
| Duplicate timestamps | `validate_ohlcv` rejects |
| Non-monotonic timestamps | `validate_ohlcv` rejects |
| Zero/negative prices | `validate_ohlcv` rejects |
| `high < low` | `validate_ohlcv` rejects |
| `open` outside `[low, high]` | `validate_ohlcv` rejects |
| Negative volume | `validate_ohlcv` rejects |
| Symbol/timeframe mismatch | `validate_ohlcv` rejects |

---

### 3. Manifest Corruption (`test_manifest_corruption.py`)

| Scenario | Detection mechanism |
|---|---|
| `content_hash` mutation | `verify_manifest` → mismatch with recomputed hash |
| `schema_hash` mutation | `verify_manifest` → mismatch |
| Orphan manifest (no parquet) | `scan_directory` → `orphan_manifests` list |
| Missing manifest (parquet only) | `scan_directory` → `issues` list |
| Wrong `row_count` | `verify_manifest` → mismatch |
| Wrong `start_timestamp_utc` | `verify_manifest` → mismatch |
| Multiple fields corrupted | All mismatches enumerated (not just first) |
| Post-write data mutation | Fresh `generate_manifest` → different `content_hash` |

**Failure semantics:** `verify_manifest` returns a `ManifestVerificationResult`
with `verified=False` and a `mismatches` list of `(field, expected, actual)` triples.
Never raises; always returns a structured result.

---

### 4. Replay Corruption (`test_replay_corruption.py`)

| Scenario | Detection mechanism |
|---|---|
| Any hash field mutation | `verify_certificate` → field in `mismatches` |
| `certified_bars` mismatch | `verify_certificate` → mismatch |
| `certified_trades` mismatch | `verify_certificate` → mismatch |
| Signal direction mutation | `_hash_signals` digest changes |
| Signal timestamp shift | `_hash_signals` digest changes |
| Reversed trade order | `_hash_trades` digest changes |
| Wrong `dataset_content_hash` | `verify_certificate` → mismatch |
| Wrong `dataset_schema_hash` | `verify_certificate` → mismatch |

**Checked fields in `verify_certificate`:**
`certificate_version`, `dataset_content_hash`, `dataset_schema_hash`,
`config_hash`, `parameters_hash`, `metrics_hash`, `trades_hash`,
`equity_hash`, `signals_hash`, `certified_bars`, `certified_trades`.

**Not checked:** `generation_timestamp_utc`, `experiment_name`, `experiment_id`,
`git_commit_hash` (informational only).

**Important:** `_hash_signals` sorts the signal series by index before hashing.
Index reordering with the same timestamps does NOT change the hash. To detect
signal tampering, mutation must change values or timestamps.

---

### 5. Canonicalization Drift (`test_canonicalization_drift.py`)

| Scenario | Detection mechanism |
|---|---|
| Different key insertion order | Same `canonical_hash` (sort_keys=True) |
| Value mutation | Different `canonical_hash` |
| Key mutation | Different `canonical_hash` |
| NaN at any nesting depth | Normalized to `null`; hash is stable |
| `float('nan')` vs `None` | Identical canonical hash (both → null) |
| `canonical_hash` vs `legacy_hash` | Always different (different separators) |
| Repeated calls | Bit-for-bit identical hash |

**Format distinction:**
- `canonical_hash`: compact separators `(",", ":")` — for NEW artifacts (post-2026-05-19)
- `legacy_hash`: default separators `(", ", ": ")` — for backward compat with existing artifacts

---

### 6. Walk-Forward Contamination (`test_walkforward_contamination.py`)

| Scenario | Detection mechanism |
|---|---|
| `train_end > test_start` (overlap) | `validate_windows` → `valid=False` |
| `train_end < test_start` (gap) | `validate_windows` → `valid=False` |
| Reversed window order | `validate_windows` → `valid=False` |
| Wrong `window_index` | `validate_windows` → `valid=False` |
| Empty training period | `validate_windows` → `valid=False` |
| Contaminated `signal_fn` | `report_hash` changes vs clean signal_fn |
| Tampered `report_hash` | `validate_report` → `valid=False` |
| Mutated `n_windows` | `_compute_report_hash` produces different hash |

**Leakage in signal_fn:** Walk-forward does not prevent a `signal_fn` from
using `center=True` rolling features internally. Such contamination is
detectable only by comparing `report_hash` against a known-clean baseline.
`validate_report` checks internal consistency, NOT signal_fn purity.

---

## Deterministic Failure Semantics

All corruption must fail **loudly** with structured diagnostics:

| Component | Failure format |
|---|---|
| `validate_ohlcv` | `result.is_valid=False`, `result.errors=[...]` |
| `generate_manifest` | `raises ValueError` with message |
| `verify_manifest` | `result.verified=False`, `result.mismatches=[(field, expected, actual), ...]` |
| `verify_certificate` | `result.verified=False`, `result.mismatches=[...]` |
| `validate_windows` | `(False, [issue_str, ...])` |
| `validate_report` | `(False, [error_str, ...])` |
| `scan_directory` | `registry.issues=[...]`, `registry.orphan_manifests=[...]` |

**Silent normalization is prohibited.** No component silently recovers from
corruption; every failure path is explicit.

---

## Known Limitations

1. **Signal contamination is not detectable at runtime** — AQCS cannot tell
   if a caller passed a pre-contaminated signal series. Detection requires
   comparing the `signals_hash` in the replay certificate against a known-clean run.

2. **`_hash_signals` sorts by index** — index reordering does not change the
   hash. Only value or timestamp changes are detectable.

3. **`validate_report` checks internal consistency, not leakage purity** — a
   walk-forward run with a contaminated `signal_fn` passes `validate_report`
   as long as the report was generated consistently.

4. **Manifest `verify` requires UTC timestamps** — data with naive timestamps
   is rejected at both the validator and manifest layer.

---

## Rollback Procedure

All adversarial tests are in `tests/adversarial/` only. No production source
files were modified. To remove the adversarial suite:

```bash
git rm -r tests/adversarial/test_temporal_leakage.py \
           tests/adversarial/test_manifest_corruption.py \
           tests/adversarial/test_replay_corruption.py \
           tests/adversarial/test_canonicalization_drift.py \
           tests/adversarial/test_walkforward_contamination.py
```

`tests/adversarial/test_timestamp_corruption.py` and
`tests/adversarial/conftest.py` were pre-existing on this branch.

---

## Related Documents

- `docs/research/adversarial_validation_research.md` — design rationale
- `tests/adversarial/conftest.py` — shared fixtures (`FIXED_NOW`)
- `src/aqcs/utils/canonicalization.py` — canonical format specification
- `src/aqcs/data/manifest.py` — manifest integrity model
- `src/aqcs/research/replay_certificate.py` — replay certification model
- `src/aqcs/research/walkforward.py` — walk-forward segmentation and validation
