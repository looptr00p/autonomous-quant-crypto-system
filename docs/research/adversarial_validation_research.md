# Adversarial Validation Research — Phase 1B

**Task:** TASK-ADVERSARIAL-VALIDATION-001  
**Date:** 2026-05-19  
**Status:** Implemented

---

## Motivation

Phase-1B requires institutional hardening of the AQCS research pipeline before
any capital is deployed. The deterministic integration suite proves the pipeline
is internally consistent. But consistency alone is insufficient — a pipeline
can be consistently wrong.

Adversarial validation asks: **What happens when the inputs are wrong?**

The framework implements deliberate corruption, contamination, and mutation to
verify that AQCS either:
- **Rejects** the corrupted input loudly, OR
- **Detects** the corruption via a traceable hash change

## Design Principles

### 1. Falsification Over Verification

Every test in `tests/adversarial/` is designed to FAIL under corruption, not
to pass under normal conditions. The adversarial suite complements (not
replaces) the integration suite.

### 2. Deterministic Corruption

All test fixtures use fixed seeds (`np.random.default_rng(42)`) or static data.
No runtime randomness. No network calls. Every failure is reproducible.

### 3. Explicit Diagnostics

Failures must name the corruption source:
- Which field was mutated
- What the expected (correct) value was
- What the actual (corrupted) value is
- Where in the lineage the corruption occurred

### 4. Hash-Based Auditability

AQCS uses cryptographic hashes at every artifact boundary:
- `DatasetManifest.content_hash` — content integrity
- `DatasetManifest.schema_hash` — schema integrity
- `ReplayCertificate.*_hash` — all pipeline outputs
- `WalkForwardReport.report_hash` — report integrity

Adversarial tests verify that mutations change these hashes deterministically.

## Corruption Model

### Temporal Leakage

**Definition:** Signal at time T uses data that would not be available until
time T+k (k > 0).

**AQCS barrier:** The backtesting engine applies `signals.shift(1)`, enforcing
that signal at T executes at T+1. This prevents same-bar execution but does
NOT prevent a caller from pre-contaminating the signal series.

**Adversarial finding:** A "contaminated oracle" signal (using `close[T+1]`)
is detectable by:
1. Comparing `_hash_signals` between clean and contaminated series → different
2. Comparing `total_return` between runs → different (direction depends on price pattern)
3. Comparing `WalkForwardReport.report_hash` between clean and contaminated `signal_fn` → different

**Implication:** Leakage detection in AQCS is hash-based, not runtime-based.
All research runs should be certified via `certify_result` and the resulting
`signals_hash` compared against known-clean baselines.

### Manifest Integrity

**Definition:** A manifest describes a dataset's identity at a point in time.
If the dataset changes after the manifest is generated, the manifest is stale.

**AQCS barrier:** `verify_manifest` recomputes all hashes and compares field-by-field.

**Adversarial finding:** Even a `0.0001` change to a single price value changes
`content_hash` (confirmed in `TestManifestDrift`). The hash function includes
all OHLCV value columns in canonical byte format.

**Known gap:** `verify_manifest` must be called explicitly. The registry
(`scan_directory`) only verifies manifests when `verify_manifests=True` is
passed — it defaults to `False` for performance.

### Replay Integrity

**Definition:** A replay certificate binds a set of inputs to a set of outputs.
Any change to inputs or outputs must invalidate the certificate.

**AQCS barrier:** `verify_certificate` checks 11 fields. Non-hash informational
fields (`experiment_name`, `generation_timestamp_utc`) are not checked.

**Adversarial finding:** `_hash_signals` sorts by index before hashing. This
means reordering signal values at the SAME timestamps produces the same hash.
Direction mutations or timestamp shifts are required to change the hash. This
is documented as a known limitation.

### Canonicalization Stability

**Definition:** The same logical data structure must always produce the same
hash, regardless of key insertion order, floating-point representation of NaN,
or platform.

**AQCS implementation:** `canonical_hash` uses:
- `sort_keys=True` (key-order independence)
- compact separators `(",", ":")` (no whitespace)
- `allow_nan=False` with `normalize_nan` (NaN → null)
- UTF-8 encoding
- SHA-256

**Adversarial finding:** `float('nan')` and `None` produce identical hashes
after normalization. `canonical_hash` and `legacy_hash` always produce
different digests for the same data due to separator format differences.

### Walk-Forward Segmentation

**Definition:** Walk-forward windows must be strictly chronological with no
train/test overlap within or across windows.

**AQCS barrier:** `validate_windows` checks:
1. Windows in ascending order by `train_start_bar`
2. `train_end_bar == test_start_bar` (no gap, no overlap)
3. Empty train or test periods
4. Wrong `window_index`
5. Regressing `test_start_bar` across windows

**Adversarial finding:** `validate_report` checks internal hash consistency
but does NOT check signal_fn purity. A contaminated `signal_fn` (using future
data) produces a valid `report_hash` — it just changes what the hash commits
to. Detection requires comparison against a known-clean baseline.

## Fragility Discovered

The following latent fragilities were identified through adversarial testing:

1. **Double-shift trap:** A caller who manually pre-shifts signal timestamps
   by +1 day causes the engine to double-shift. The execution timing is 2 bars
   late instead of 1. This is detectable by metric change but NOT by the
   validator (it accepts any UTC-indexed signal).

2. **Signal hash sort assumption:** `_hash_signals` sorts by index. A caller
   who reverses the signal series produces the same hash. This is by design
   (hash should be order-independent given that signals are keyed by timestamp)
   but callers must mutate VALUES or TIMESTAMPS (not just order) to see a hash
   change.

3. **Registry non-verification by default:** `scan_directory` defaults to
   `verify_manifests=False`. Orphan manifests and missing manifests are always
   detected, but hash mismatches require explicit opt-in.

## Guarantees Strengthened by This Task

| Guarantee | Tested by |
|---|---|
| Naive timestamp rejection at all entry points | `test_timestamp_corruption`, `test_manifest_corruption` |
| Content hash changes on any data mutation | `test_manifest_corruption::TestManifestDrift` |
| All hash fields checked by verify_certificate | `test_replay_corruption::TestReplayTampering` |
| Window segmentation enforces strict chronology | `test_walkforward_contamination` |
| Contaminated signal_fn produces different report_hash | `test_temporal_leakage::TestBenchmarkContamination` |
| canonical_hash is key-order-independent | `test_canonicalization_drift::TestSerializationOrderingStability` |
| NaN normalizes deterministically | `test_canonicalization_drift::TestNaNInstability` |

## Coverage Summary

```
tests/adversarial/
  conftest.py                       — shared fixtures (FIXED_NOW)
  test_timestamp_corruption.py      — 22 tests: structural, timestamp, price, metadata, manifest
  test_temporal_leakage.py          — 12 tests: oracle, future close, rolling, pre-shift, benchmark
  test_manifest_corruption.py       — 14 tests: content hash, schema hash, orphan, lineage, drift
  test_replay_corruption.py         — 21 tests: hash fields, ordering, metadata, lineage, counts
  test_canonicalization_drift.py    — 23 tests: ordering, mutation, NaN, format, stability
  test_walkforward_contamination.py — 15 tests: overlap, boundary, order, segmentation, hash
```

Total: **109 adversarial tests**
