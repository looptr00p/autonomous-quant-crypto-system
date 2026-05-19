# TASK-INTEGRATION-PIPELINE-001 — Deterministic E2E Integration Suite Plan

**Status:** Planned (not started)  
**Phase:** Phase-1B  
**Related ADRs:** ADR-008, ADR-009  
**Prerequisite:** AUD-007 Phase-1B conditions met (ADR-008 and ADR-009 filed)

---

> **This is a planning document only.** No code, tests, or scripts are created here.
> Implementation begins only when this plan is reviewed and approved by the Human Founder.
> Nothing in this document authorizes live trading, paper trading, execution, ML, RL,
> optimization, or any Phase-2+ capability.

---

## Objective

Add an end-to-end integration test suite that exercises the full Phase-1 research
pipeline from raw data through final audit artifacts. This closes the gap identified
in AUD-007 (R-003): the `tests/integration/` directory currently collects 0 tests.

A passing integration suite provides confidence that all cross-module seams work
correctly, that artifact hashes remain stable across a full pipeline run, and that
no change to one module silently breaks another.

---

## Scope

The integration suite is **read-only and deterministic**. It uses synthetic or cached
fixture data (no live network calls, no live exchange connections). It produces
research artifacts in a temporary directory and validates them.

**In scope:**
- Synthetic OHLCV fixture data generation (deterministic, no network)
- Manifest generation and verification
- Dataset registry construction
- Fleet snapshot generation
- Replay certificate generation and verification
- Baseline report generation and validation
- Walk-forward report generation and validation
- Campaign artifact generation and validation
- Benchmark suite generation and validation
- Regression guard comparison (baseline vs identical candidate → 0 findings)
- Sensitivity audit on a generated campaign artifact
- Artifact lineage: verify that campaign references correct manifest and certificate hashes
- Canonical hash consistency: verify all new-format artifacts hash to the same value on re-run

**Out of scope (remains deferred):**
- Live data download (network calls)
- Parameter sensitivity via backtesting re-runs (Phase-1B Tier 2)
- Multi-asset portfolio (Phase 2+)
- Statistical significance testing (Phase-1B Tier 3)
- Any execution-layer operation

---

## Intended Test Structure

```
tests/integration/
├── __init__.py
├── conftest.py                    # shared fixtures: synthetic OHLCV, tmp dirs
├── test_pipeline_e2e.py           # single end-to-end pipeline test
└── test_artifact_lineage.py       # cross-artifact hash consistency
```

### `test_pipeline_e2e.py`

One test class: `TestFullPipelineE2E`.

Tests:
1. `test_manifest_generated_and_valid` — given synthetic OHLCV parquet, generate a manifest; `validate_manifest` returns `is_valid=True`
2. `test_registry_includes_new_dataset` — build registry after manifest; dataset appears with `is_verified=True`
3. `test_fleet_snapshot_captures_registry` — fleet snapshot includes the registered dataset; hash is stable
4. `test_replay_cert_generated_and_valid` — given backtest result fixture, generate cert; 5 hash fields populated
5. `test_baseline_report_generated_and_valid` — generate baseline report; `validate_baseline_report` passes
6. `test_walkforward_report_valid` — generate walk-forward report with ≥4 windows; `leakage_validated=True`
7. `test_campaign_assembles_all_artifacts` — build campaign from above artifacts; `validate_campaign` passes
8. `test_benchmark_suite_from_campaign` — build benchmark suite from campaign; `validate_benchmark` passes; score ∈ [0, 1]
9. `test_regression_guard_identical_dirs_clean` — regression guard on same dir twice → 0 findings
10. `test_sensitivity_audit_stable_artifact` — run sensitivity audit on campaign; all LOW findings → `has_instability=False`

### `test_artifact_lineage.py`

Tests:
1. `test_campaign_references_correct_manifest_hash` — campaign's manifest reference matches manifest's `content_hash`
2. `test_campaign_references_correct_cert_hash` — campaign's cert reference matches cert's hash fields
3. `test_canonical_hash_stable_across_runs` — generate campaign twice from same inputs; `campaign_hash` identical
4. `test_regression_report_hash_deterministic` — run regression guard twice on same dir pair; `regression_hash` identical

---

## Fixture Strategy

All fixtures must be:
- **Deterministic**: same synthetic data → same outputs → same hashes
- **Local**: no network, no external APIs, no live exchange
- **Self-contained**: no reliance on `data/raw/` files (those are gitignored)
- **Minimal**: smallest possible OHLCV data that exercises all pipeline stages (e.g., 300 synthetic bars of BTC/USDT 1d)

The synthetic OHLCV fixture will use a deterministic generator: fixed seed, fixed parameters, producing a `pd.DataFrame` that passes all 13 `validate_ohlcv` checks.

---

## Implementation Constraints

When implementation begins:

- Tests must use `tmp_path` (pytest fixture) for all file I/O
- Tests must not write to `data/`, `reports/`, or any production directory
- Tests must pass `PYTHONPATH=src pytest tests/integration/ -q --override-ini="addopts="`
- Tests must be added to the main test run: `PYTHONPATH=src pytest tests/ -q --override-ini="addopts="`
- Tests must not require network access (`@pytest.mark.skipif` for network is prohibited — tests must be fully offline)
- No new test dependencies may be added without ADR and human approval

---

## Acceptance Criteria (for implementation task)

- [ ] `tests/integration/` collects ≥ 10 tests
- [ ] All integration tests pass on clean repository with synthetic data only
- [ ] `test_canonical_hash_stable_across_runs` confirms hash stability
- [ ] `test_regression_guard_identical_dirs_clean` confirms 0 findings on identical directories
- [ ] Full suite still passes: `PYTHONPATH=src pytest tests/ -q --override-ini="addopts="`
- [ ] ruff / black / mypy: clean
- [ ] No new dependencies introduced
- [ ] No forbidden modules (execution, portfolio, risk, signals, llm_oversight) imported

---

## Relationship to ADRs

- **ADR-008** — The integration tests will verify that all governed thresholds behave
  as documented (e.g., regression guard generates no critical findings on identical
  artifacts, benchmark scores are in [0, 1])
- **ADR-009** — The tests will verify canonical hash stability across runs (Rule 7:
  self-verifiable artifacts) and that `validate_*` functions confirm self-certification

---

## Deferred Capabilities (explicitly not in scope)

The following are not part of TASK-INTEGRATION-PIPELINE-001 and must not be introduced
during its implementation:

- Live data download
- Exchange authentication
- Live or paper trading
- Order execution of any kind
- ML/RL model training or inference
- Parameter optimization or adaptive tuning
- Multi-asset portfolio simulation
- Schedulers, daemons, or background workers
- Statistical significance testing (p-values, bootstrap)
