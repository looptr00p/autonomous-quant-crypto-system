# AQCS Phase-1 Deterministic Research Workflow Runbook

**Document version:** 1.0  
**Date:** 2026-05-19  
**Status:** Active — Phase 1 (Foundation / Research Layer)  
**Audience:** Research engineers, Technical Auditors, Code Reviewers  
**Source of truth:** `docs/architecture/system-architecture-v1.md`

---

> **Critical governance statement.** AQCS is a **deterministic offline research platform**. It is **not** a live-trading system, a paper-trading system, an autonomous execution platform, or a portfolio automation system. No code path in Phase 1 submits orders to any exchange. This constraint is architectural, not configurational. It is enforced by `src/aqcs/utils/phase_guard.py` and verified by CI on every push.

---

## Table of Contents

1. [AQCS Research Philosophy](#1-aqcs-research-philosophy)
2. [Governance Principles](#2-governance-principles)
3. [Deterministic Guarantees](#3-deterministic-guarantees)
4. [Approved Operational Workflow](#4-approved-operational-workflow)
5. [Dataset Lifecycle](#5-dataset-lifecycle)
6. [Manifest Lifecycle](#6-manifest-lifecycle)
7. [Replay Certification Workflow](#7-replay-certification-workflow)
8. [Baseline Reporting Workflow](#8-baseline-reporting-workflow)
9. [Walk-Forward Validation Workflow](#9-walk-forward-validation-workflow)
10. [Research Campaign Workflow](#10-research-campaign-workflow)
11. [Benchmark Suite Workflow](#11-benchmark-suite-workflow)
12. [Artifact Lineage](#12-artifact-lineage)
13. [Canonical Hashing Rules](#13-canonical-hashing-rules)
14. [Operational Validation Checklist](#14-operational-validation-checklist)
15. [Human Review Requirements](#15-human-review-requirements)
16. [Forbidden Activities](#16-forbidden-activities)
17. [Incident and Drift Investigation Guidance](#17-incident-and-drift-investigation-guidance)
18. [Merge and Review Discipline](#18-merge-and-review-discipline)
19. [Future Work Explicitly Deferred](#19-future-work-explicitly-deferred)
20. [Phase-1 Boundaries](#20-phase-1-boundaries)

---

## 1. AQCS Research Philosophy

AQCS is built on three foundational commitments:

**Determinism first.** Every computation that produces a research artifact must be reproducible from the same inputs on any conforming machine, at any future date. A result that cannot be identically reproduced is not a result — it is noise. All artifact systems use deterministic hashing, stable ordering, and UTC-only timestamps specifically to enforce this commitment.

**Auditability always.** Every research decision — from data selection through signal generation to reporting — must be traceable to an explicit, versioned artifact. Implicit state, cached results, or wall-clock-dependent outputs are prohibited. All artifacts are immutable once generated and self-certifying via SHA-256 hashes.

**Human judgment owns deployment.** AQCS produces evidence for human review. It never makes deployment decisions, never selects strategies for live use, and never submits orders. The platform ends at the benchmark suite. What happens after a human reviews that benchmark is outside the scope of AQCS Phase 1.

These commitments translate directly into the operational constraints documented throughout this runbook.

---

## 2. Governance Principles

### 2.1 Architecture Enforcement

The AQCS dependency DAG is enforced by CI on every push via `tests/architecture/test_dependency_boundaries.py`. Every package's allowed imports are explicitly listed in the `ALLOWED` dict. Any import that violates the DAG is a CI failure that blocks merge.

The Research Layer (`aqcs.research`) may import from: `aqcs.backtesting`, `aqcs.data`, `aqcs.experiments`, `aqcs.features`, `aqcs.monitoring`, `aqcs.signals`, `aqcs.utils`. It must never import from `aqcs.execution`, `aqcs.risk`, `aqcs.portfolio`, or `aqcs.llm_oversight`.

### 2.2 Phase Guard

`src/aqcs/utils/phase_guard.py` implements a runtime guard that blocks phase-restricted features. `CURRENT_PHASE = 1` blocks: `ORDER_EXECUTION`, `MACHINE_LEARNING`, `LIVE_TRADING`, `PAPER_TRADING`, `WEBSOCKET_STREAMING`, and all other Phase 2+ features.

Modifying `CURRENT_PHASE` requires:
- An approved ADR in `docs/decisions/`
- Explicit human approval from the Technical Auditor
- A dedicated code review pass

No agent session or automated workflow may modify `CURRENT_PHASE`.

### 2.3 Immutability of Research Artifacts

All research artifacts (manifests, registry snapshots, fleet snapshots, replay certificates, baseline reports, walk-forward reports, campaigns, benchmark suites) are **immutable once generated**. They are identified by their self-certifying SHA-256 hash. A regenerated artifact with different content has a different hash and must be treated as a distinct artifact.

### 2.4 The LLM Oversight Boundary

The LLM oversight layer (`aqcs.llm_oversight`) is a **read-only observer**. It reads event records from the core pipeline and writes human-readable narrative summaries to `docs/bitacora/`. It has no write access to `data/`, `src/`, `configs/`, or any exchange. It does not generate trading signals and does not influence pipeline outputs.

### 2.5 No Silent Defaults

Every BacktestConfig requires explicit `fee_bps` and `slippage_bps`. No value silently defaults to zero. This prevents research artifacts that understate transaction costs and protects against inadvertent performance inflation.

---

## 3. Deterministic Guarantees

AQCS makes the following deterministic guarantees that the runbook enforces:

| Guarantee | Mechanism |
|---|---|
| Same data → same result | All signal and backtest functions are pure; randomness is prohibited |
| No future leakage | Signal at bar T executes at bar T+1 open (shift-1 enforced by engine) |
| UTC-only timestamps | `validate_ohlcv` rejects timezone-naive or non-UTC timestamps |
| Ordered artifact output | All collections use `sorted()` before serialization |
| Stable JSON serialization | `sort_keys=True`; NaN serialized as `null`; UTF-8 encoded |
| Reproducible hashes | SHA-256 of canonical JSON bytes; same input → same hash always |
| Immutable artifacts | Frozen dataclasses; no post-construction mutation |
| Wall-clock isolation | `now_utc` is injectable in all artifact builders |

Any artifact that violates these guarantees is considered malformed and must be regenerated from scratch after identifying the root cause.

---

## 4. Approved Operational Workflow

The complete approved Phase-1 research workflow is:

```
Step 1:  Public OHLCV Burn-In
         ↓
Step 2:  Data Quality Validation
         ↓
Step 3:  Manifest Generation and Verification
         ↓
Step 4:  Dataset Registry Update
         ↓
Step 5:  Fleet Monitoring Snapshot
         ↓
Step 6:  Research Pipeline Run + Experiment Persistence
         ↓
Step 7:  Replay Certification
         ↓
Step 8:  Baseline Report Generation
         ↓
Step 9:  Walk-Forward Validation
         ↓
Step 10: Research Campaign Assembly
         ↓
Step 11: Benchmark Suite Generation
         ↓
         ── HUMAN REVIEW GATE ──
```

**Human review is required before any operational decision downstream of Step 11.** The benchmark suite is advisory only. It does not select strategies, does not authorize deployment, and does not constitute a trading recommendation.

Each step must complete successfully before the next step begins. Do not proceed past a validation failure without understanding and documenting its cause.

---

## 5. Dataset Lifecycle

### 5.1 Purpose

The dataset lifecycle establishes the authoritative local OHLCV dataset from which all downstream research artifacts are derived. Dataset integrity is the foundation of reproducibility.

### 5.2 Step 1 — API Smoke Test (connectivity check)

Before running a full burn-in, verify API connectivity with a small bounded fetch.

**Purpose:** Confirm the public Binance Spot OHLCV endpoint is reachable and returns schema-valid data. This is a connectivity check, not a data acquisition step.

**Command:**
```bash
PYTHONPATH=src python scripts/data/smoke_test_public_ohlcv.py \
  --exchange binance \
  --symbol BTCUSDT \
  --timeframe 1h \
  --limit 48 \
  --output-dir data/smoke/
```

**Deterministic guarantees:** Parquet output uses OHLCV_SCHEMA with `timestamp[ms, tz=UTC]`. Manifest is generated and verified in the same run. JSON summary printed to stdout.

**Exit codes:**
- `0` — all steps passed
- `1` — data validation or manifest verification failed
- `2` — invalid CLI arguments

**Validation expectation:** Exit code 0. JSON `"status": "passed"`.

**Governance boundary:** Uses only public Binance Spot read-only endpoints. No API key. No order placement. No private account access.

**Artifact outputs:** `data/smoke/BTC_USDT_1h.parquet` (ephemeral; for connectivity verification only).

**Human review checkpoint:** None required for smoke test. If exit code 1 or 2, investigate before proceeding.

---

### 5.3 Step 2 — Public OHLCV Burn-In (data acquisition)

**Purpose:** Acquire a deterministic multi-symbol OHLCV dataset from the Binance Spot public API for use as the research input dataset.

**Command:**
```bash
PYTHONPATH=src python scripts/data/run_public_ohlcv_burn_in.py \
  --exchange binance \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --timeframe 1h \
  --limit 200 \
  --output-dir data/burn_in/
```

**Deterministic guarantees:** Each symbol produces one Parquet file. Timestamps are UTC-aware. Rows are sorted by timestamp ascending. Schema is enforced via `OHLCV_SCHEMA`. A manifest is generated and verified per symbol in the same run.

**Exit codes:**
- `0` — all symbols passed
- `1` — at least one symbol failed
- `2` — configuration error

**Artifact outputs:**
```
data/burn_in/
  BTC_USDT_1h.parquet
  ETH_USDT_1h.parquet
  SOL_USDT_1h.parquet
  BTC_USDT_1h_manifest.json
  ETH_USDT_1h_manifest.json
  SOL_USDT_1h_manifest.json
```

**Validation expectation:** Exit code 0. JSON `"status": "passed"` for all symbols. Each parquet is readable with valid UTC timestamps and no duplicate rows.

**Governance boundary:** Public endpoints only. No API key. No orders. No private endpoints. `CURRENT_PHASE = 1` enforced.

**Human review checkpoint:** If any symbol fails, investigate before proceeding to registry or research steps.

---

### 5.4 Data Quality Validation

**Purpose:** Run the monitoring layer's data-quality check on each persisted Parquet file to confirm structural integrity before downstream use.

**Command (per file):**
```bash
PYTHONPATH=src python scripts/monitoring/check_data_quality.py \
  --parquet data/burn_in/BTC_USDT_1h.parquet \
  --timeframe 1h
```

**Checks performed (9):**
1. File is readable as Parquet
2. Required OHLCV columns present
3. Dataset is non-empty
4. UTC-aware timestamps
5. Monotonically increasing timestamps
6. Duplicate timestamp count
7. Missing interval count
8. NaN counts per value column
9. Freshness lag calculation

**Artifact outputs:** JSON report to stdout. No files written.

**Validation expectation:** Exit code 0. `"passed": true`. Zero errors. Warnings (gaps, staleness) are advisory and must be documented before proceeding.

**Human review checkpoint:** Any error stops the workflow. Any warning requires explicit human acknowledgment before research steps.

---

## 6. Manifest Lifecycle

### 6.1 Purpose

Dataset manifests are the content-addressable identity certificates for local OHLCV Parquet files. They bind a dataset's schema, content hash, row count, and temporal span to a single SHA-256 fingerprint.

### 6.2 Manifest Schema

Each manifest contains:
- `manifest_version` — always `"1"`
- `exchange`, `symbol`, `timeframe`, `timezone`
- `row_count`, `start_timestamp_utc`, `end_timestamp_utc`
- `content_hash` — SHA-256 of sorted OHLCV byte values (timestamp ms int64 + OHLCV float64 little-endian)
- `schema_hash` — SHA-256 of Arrow column schema (field names + type strings, JSON-sorted)
- `duplicate_count`, `missing_interval_summary`
- `generation_timestamp_utc`

The `content_hash` is the canonical dataset identity. Two datasets with the same `content_hash` are identical regardless of filename or storage path.

### 6.3 Manifest Generation

The burn-in script generates manifests automatically. For standalone generation:

```bash
PYTHONPATH=src python scripts/data/generate_manifest.py \
  --parquet data/burn_in/BTC_USDT_1h.parquet \
  --symbol BTC/USDT \
  --timeframe 1h \
  --output data/burn_in/BTC_USDT_1h_manifest.json
```

### 6.4 Manifest Verification

```bash
PYTHONPATH=src python scripts/data/verify_manifest.py \
  --parquet data/burn_in/BTC_USDT_1h.parquet \
  --manifest data/burn_in/BTC_USDT_1h_manifest.json
```

**Validation expectation:** Exit code 0. `"verified": true`. Any mismatch indicates the Parquet file was modified after manifest generation — this is a stop condition requiring investigation.

### 6.5 Deterministic Guarantees

- `content_hash` is deterministic for the same row data regardless of insertion order (rows are sorted by timestamp before hashing).
- `schema_hash` reads only the Parquet file footer (no row-data I/O).
- Both hashes use SHA-256 of canonical UTF-8 JSON bytes with `sort_keys=True`.
- `generation_timestamp_utc` is the only wall-clock field and is not included in hash computation.

---

## 7. Replay Certification Workflow

### 7.1 Purpose

Replay certification formally certifies that a completed research experiment can be reproduced identically. A `ReplayCertificate` captures SHA-256 hashes of every deterministic output: dataset identity, configuration, metrics, trades, equity curve, and signal series.

### 7.2 Prerequisites

- Research pipeline run completed (experiment JSON and artifact Parquets persisted)
- Dataset manifest available for the input dataset

### 7.3 Certification Command

```bash
PYTHONPATH=src python scripts/research/certify_replay.py \
  --experiment-json experiments/YYYY-MM-DD/experiment_<uuid>.json \
  --artifacts-dir experiments/ \
  --manifest-json data/burn_in/BTC_USDT_1h_manifest.json \
  --output reports/replay_cert_<uuid>.json
```

### 7.4 Verification Command

```bash
PYTHONPATH=src python scripts/research/verify_certificate.py \
  --certificate reports/replay_cert_<uuid>.json \
  --experiment-json experiments/YYYY-MM-DD/experiment_<uuid>.json \
  --artifacts-dir experiments/
```

**Validation expectation:** Exit code 0. `"verified": true`. All hash fields match between re-run and stored certificate.

### 7.5 Certificate Schema

Each `ReplayCertificate` contains (all fields are SHA-256 hex strings unless noted):
- `certificate_version`
- `experiment_id`, `experiment_name`, `git_commit_hash`
- `dataset_content_hash`, `dataset_schema_hash` — links to manifest
- `config_hash` — hash of BacktestConfig
- `parameters_hash` — hash of experiment parameters
- `metrics_hash` — hash of backtest metrics (binary float64 LE encoding)
- `trades_hash`, `equity_hash`, `signals_hash` — binary hash of raw artifact bytes
- `generation_timestamp_utc`
- `certified_bars`, `certified_trades`

### 7.6 Deterministic Guarantees

- All hash fields use SHA-256 with little-endian binary encoding for numeric data (no JSON float precision ambiguity).
- Timestamps are normalized to int64 milliseconds since UTC epoch.
- Trade and equity curve hashes use chronological order (enforced by engine output order).
- Signal hash uses index-sorted timestamp order.
- `generation_timestamp_utc` is excluded from all hash computations.

### 7.7 Human Review Checkpoint

A replay certificate must be generated and verified before assembling a research campaign. Any verification failure is a stop condition. Do not proceed until the root cause is identified and documented.

---

## 8. Baseline Reporting Workflow

### 8.1 Purpose

A baseline report is an immutable, self-certifying performance summary for a completed backtest experiment. It extends core backtesting metrics with cost analysis, turnover, benchmark comparison, and reproducibility references. Reports are advisory only and must not be interpreted as profitability proofs.

### 8.2 Command

```bash
PYTHONPATH=src python scripts/research/build_baseline_report.py \
  --experiment-dir experiments/ \
  --artifacts-dir experiments/ \
  --dataset-content-hash <hash_from_manifest> \
  --dataset-schema-hash <hash_from_manifest> \
  --dataset-symbol "BTC/USDT" \
  --dataset-timeframe 1h \
  --dataset-exchange binance \
  --output-json reports/baseline_report_<uuid>.json
```

### 8.3 Validation Command

```bash
PYTHONPATH=src python scripts/research/validate_baseline_report.py \
  --report-json reports/baseline_report_<uuid>.json
```

**Validation expectation:** Exit code 0. `"valid": true`.

### 8.4 Report Schema (key fields)

- `report_version`, `experiment_id`, `report_hash` (self-certifying SHA-256)
- `disclaimer` — mandatory safety statement (non-empty)
- Dataset references: `dataset_content_hash`, `dataset_schema_hash`, `dataset_symbol`, `dataset_timeframe`
- Replay reference: `replay_certificate_hash`, `replay_certified`
- Core metrics: `total_return`, `cagr`, `max_drawdown`, `sharpe_ratio`, `annualised_volatility`, `trade_count`, `win_rate`, `exposure`
- Extended metrics: `total_fees_paid`, `total_slippage_cost`, `avg_trade_value`, `turnover_per_bar`, `avg_holding_period_bars`, `max_consecutive_losses`
- Benchmark: `benchmark_total_return` (buy-and-hold), `excess_return`
- `metrics_hash` — binary float64 LE hash matching replay certificate format

### 8.5 Deterministic Guarantees

- `report_hash` = SHA-256 of `json.dumps(report_dict, sort_keys=True)` (legacy default separators, backward-compatible with all stored reports).
- `excess_return = result.metrics["total_return"] - benchmark_total_return` — uses the engine-authoritative total_return value.
- NaN values serialize as `null` in JSON and round-trip correctly via `report_from_dict`.
- `generation_timestamp_utc` is excluded from `report_hash` computation.

### 8.6 Safety Disclaimer

Every baseline report contains a mandatory disclaimer:

> "This report documents deterministic backtest results for research purposes only. It does not constitute alpha validation, profitability proof, paper trading readiness, or live trading authorisation."

This disclaimer is verified by `validate_report`. A report without a non-empty disclaimer is considered malformed.

### 8.7 Human Review Checkpoint

A baseline report must pass self-validation before inclusion in a campaign. The `replay_certified` field should be `true` where a certificate exists.

---

## 9. Walk-Forward Validation Workflow

### 9.1 Purpose

Walk-forward validation provides leakage-safe temporal evaluation of a strategy over sequential non-overlapping test windows. It is the primary tool for assessing whether backtest results are robust to temporal out-of-sample evaluation — not for optimising parameters or selecting strategies.

### 9.2 Window Layout

```
Window 0: train [0, train_bars)         test [train_bars, train_bars+test_bars)
Window 1: train [step, step+train_bars) test [step+train_bars, step+train_bars+test_bars)
...
```

No future data enters the signal computation: the signal for each window is generated on `ohlcv[:test_end_bar]` only.

### 9.3 Command

```bash
PYTHONPATH=src python scripts/research/run_walkforward.py \
  --dataset data/burn_in/BTC_USDT_1h.parquet \
  --train-bars 500 \
  --test-bars 100 \
  --step-bars 100 \
  --initial-capital 10000.0 \
  --fee-bps 10.0 \
  --slippage-bps 2.0 \
  --output-json reports/walkforward_report.json
```

### 9.4 Validation Command

```bash
PYTHONPATH=src python scripts/research/validate_walkforward.py \
  --walkforward-json reports/walkforward_report.json
```

**Validation expectation:** Exit code 0. `"valid": true`. `"leakage_validated": true`.

### 9.5 Report Schema (key fields)

- `report_version`, `report_hash` (self-certifying)
- `train_bars`, `test_bars`, `step_bars`, `n_windows`
- `leakage_validated` — True when all temporal checks pass
- `summary.n_windows_total/evaluated/failed/profitable`
- `summary.mean_total_return`, `summary.std_total_return`, `summary.min/max_total_return`
- `summary.mean_sharpe_ratio`, `summary.mean_max_drawdown`
- `summary.test_overlap` — True when `step_bars < test_bars`

### 9.6 Leakage Prevention Validation

The validation layer checks:
1. Within each window: `train_end_bar == test_start_bar` (no gap, no overlap)
2. Windows in ascending order by `train_start_bar`
3. Test frontier advances monotonically across windows
4. Signal computation uses only data up to `test_end_bar`

Any leakage check failure is a stop condition.

### 9.7 Deterministic Guarantees

- `report_hash` uses `json.dumps(sort_keys=True)` (default separators, legacy format).
- NaN values in failed window metrics serialize as `null`.
- Two independent runs on the same dataset with the same parameters produce identical JSON (verified via hash comparison).
- `generation_timestamp_utc` excluded from hash computation.

### 9.8 Human Review Checkpoint

Review `summary.test_overlap` (informational, not blocking) and `summary.n_windows_failed` before campaign assembly. A high failure rate indicates dataset issues or parameter misconfiguration.

---

## 10. Research Campaign Workflow

### 10.1 Purpose

A research campaign is the orchestration artifact that links together dataset manifests, replay certificates, walk-forward reports, and baseline reports into a single immutable, self-certifying lineage record. Campaigns support audit traceability and benchmark comparison.

### 10.2 Artifacts Directory Structure

Before building a campaign, ensure the artifacts directory contains the relevant JSON files from previous workflow stages:

```
experiments/campaign_inputs/
  BTC_USDT_1h_manifest.json          ← from Step 3
  ETH_USDT_1h_manifest.json
  SOL_USDT_1h_manifest.json
  replay_cert_<uuid>.json            ← from Step 7
  baseline_report_<uuid>.json        ← from Step 8
  walkforward_report.json            ← from Step 9
```

### 10.3 Command

```bash
PYTHONPATH=src python scripts/research/build_campaign.py \
  --artifacts-dir experiments/campaign_inputs/ \
  --campaign-name baseline_campaign_2026_05 \
  --output-json reports/campaign_report.json
```

### 10.4 Validation Command

```bash
PYTHONPATH=src python scripts/research/validate_campaign.py \
  --campaign-json reports/campaign_report.json
```

**Validation expectation:** Exit code 0. `"valid": true`. `"issues_count": 0`.

### 10.5 Campaign Schema (key fields)

- `campaign_version`, `campaign_id` (UUID5 of `campaign_hash`), `campaign_name`
- `campaign_hash` — `canonical_hash(content_dict)` excluding `campaign_hash`, `campaign_id`, `generation_timestamp_utc` — **content-addressable**
- `dataset_manifest_hashes`, `replay_certificate_hashes`, `walkforward_report_hashes`, `baseline_report_hashes`
- `total_experiments`, `total_walkforward_windows`
- `symbols`, `timeframes`
- Aggregate metrics: `aggregate_metrics`, `aggregate_drawdown`, `aggregate_turnover`, `aggregate_exposure`
- `artifact_hashes` — SHA-256 of raw file bytes per artifact file (Merkle-leaf structure)
- `issues`, `warnings`

### 10.6 Artifact Type Detection

The campaign scanner classifies JSON files by discriminating field presence:

| Type | Discriminating fields |
|---|---|
| DatasetManifest | `manifest_version`, `content_hash`, `schema_hash`, `exchange` |
| ReplayCertificate | `certificate_version`, `certified_bars`, `config_hash` |
| WalkForwardReport | `train_bars`, `step_bars`, `leakage_validated`, `n_windows` |
| BaselineReport | `benchmark_total_return`, `disclaimer`, `initial_capital` |

Unrecognised files are recorded as warnings.

### 10.7 Deterministic Guarantees

- `campaign_hash` uses compact separators `(",", ":")` and `ensure_ascii=False` (canonical format).
- `campaign_id` = `uuid5(fixed_namespace, campaign_hash)` — deterministic UUID.
- Artifacts are sorted before aggregation (manifests by `content_hash`, baselines by `report_hash`, etc.).
- Same artifact directory → same campaign hash regardless of filesystem traversal order.

### 10.8 Human Review Checkpoint

A campaign with any recorded `issues` must be investigated before benchmark assembly. Warnings are advisory and must be documented.

---

## 11. Benchmark Suite Workflow

### 11.1 Purpose

A benchmark suite provides deterministic, advisory-only comparison of one or more research campaigns. Rankings are for governance review only. The benchmark suite does not select strategies for deployment, does not authorize trading, and does not constitute a performance claim.

### 11.2 Command

```bash
PYTHONPATH=src python scripts/research/build_benchmark_suite.py \
  --campaigns-dir reports/campaigns/ \
  --benchmark-name baseline_benchmark_suite_2026_05 \
  --output-json reports/benchmark_suite.json
```

### 11.3 Validation Command

```bash
PYTHONPATH=src python scripts/research/validate_benchmark_suite.py \
  --benchmark-json reports/benchmark_suite.json
```

**Validation expectation:** Exit code 0. `"valid": true`.

### 11.4 Scoring Rules — Explicit and Documented

All scoring weights are **public constants** in `src/aqcs/research/benchmark_suite.py`. No weights are learned, adaptive, or derived from optimisation.

| Component | Weight | Formula |
|---|---|---|
| Return | 0.30 | `clamp(mean_total_return / 1.0, 0, 1)` |
| Drawdown penalty | 0.25 | `1 − clamp(mean_max_drawdown / 1.0, 0, 1)` |
| Sharpe | 0.25 | `clamp(mean_sharpe_ratio / 3.0, 0, 1)` |
| Walk-forward coverage | 0.10 | `clamp(wf_windows / 100, 0, 1)` |
| Issue penalty | 0.10 | `1 − clamp(issue_count / 5, 0, 1)` |

**Sum of weights = 1.0** (verified by CI test).

Scores are in `[0, 1]`. Any change to these constants requires a documented ADR and human approval.

### 11.5 Regression Thresholds — Explicit and Documented

| Threshold | Constant | Flag condition |
|---|---|---|
| `REGRESSION_RETURN_FLOOR = -0.10` | `mean_total_return < −0.10` |
| `REGRESSION_DRAWDOWN_CEIL = 0.30` | `mean_max_drawdown > 0.30` |
| `REGRESSION_SHARPE_FLOOR = 0.0` | `mean_sharpe_ratio ≤ 0.0` |
| `REGRESSION_ISSUE_CEIL = 5` | `issue_count > 5` |

### 11.6 Benchmark Schema (key fields)

- `benchmark_version`, `benchmark_id` (UUID5 of `benchmark_hash`), `benchmark_name`
- `benchmark_hash` — `canonical_hash(content_dict)` excluding hash/id/timestamp
- `campaign_hashes`, `campaign_ids`, `campaign_names`, `total_campaigns`
- `comparison_entries` — sorted by `(−score, campaign_hash)`
- `regression_flags` — union of all entry flags (sorted)
- `score_weights`, `regression_thresholds` — embedded constants for auditability
- Advisory disclaimer embedded in `ranking_metrics`

### 11.7 Advisory Disclaimer

Every benchmark suite report embeds the following advisory disclaimer:

> "Rankings are for governance review ONLY. They do not constitute deployment recommendations."

This disclaimer is verified by `validate_benchmark`. Human reviewers must acknowledge this before drawing operational conclusions.

### 11.8 Human Review Checkpoint — MANDATORY

**This is the final workflow gate.** A human Technical Auditor must review the benchmark suite before any downstream operational decision. The review must confirm:

1. `"valid": true` from `validate_benchmark_suite.py`
2. `regression_flags` reviewed and documented
3. Advisory disclaimer acknowledged
4. No strategy is selected for live deployment based solely on benchmark ranking

---

## 12. Artifact Lineage

The following diagram shows how artifacts are linked across the workflow:

```
OHLCV Parquet ─── content_hash ──────────────────┐
      │                                            │
      └── schema_hash ─── DatasetManifest ─────────┼──► campaign.dataset_manifest_hashes
                               │                   │
                               └── content_hash ───┤
                                                    │
BacktestResult ──────────────────────────────────── ReplayCertificate ──► campaign.replay_certificate_hashes
      │                 (metrics/trades/equity/signals hash)
      │
      ├── BaselineReport ─── report_hash ─────────────────────────────► campaign.baseline_report_hashes
      │         │
      │         └── dataset_content_hash ────────────────────────────► links to manifest
      │         └── replay_certificate_hash ──────────────────────────► links to certificate
      │
      └── WalkForwardReport ─── report_hash ───────────────────────────► campaign.walkforward_report_hashes
                │
                └── dataset_path ──────────────────────────────────────► source Parquet reference

ResearchCampaign ─── campaign_hash ────────────────────────────────────► BenchmarkSuite.campaign_hashes
      │           (content-addressable UUID5)
      └── artifact_hashes ──────────────────────────────────────────────► SHA-256 of each artifact file
```

**Lineage invariant:** Every research artifact carries explicit hash references to its upstream artifacts. A downstream artifact that cannot be linked to a valid upstream chain is malformed and must be discarded.

---

## 13. Canonical Hashing Rules

### 13.1 Why Canonical Hashing Exists

Deterministic hashing is the foundation of replay compatibility. If two independently generated artifacts produce the same hash, they are guaranteed to have the same content. If a stored artifact's hash no longer matches its content, it has been tampered with or corrupted.

Without canonical hashing, slight differences in JSON serialization (key ordering, float formatting, whitespace) could produce different hashes for semantically identical data. AQCS eliminates this risk by enforcing one canonical serialization format for all new artifacts.

### 13.2 Canonical Format (New Artifacts — post 2026-05-19)

```python
json.dumps(
    data,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
)
```

- `sort_keys=True` — eliminates key insertion-order dependence
- `separators=(",", ":")` — compact, no whitespace
- `ensure_ascii=False` — preserves UTF-8 faithfully
- `allow_nan=False` — NaN must be pre-normalized to `None` (use `normalize_nan()`)
- UTF-8 encoded bytes before SHA-256

**Canonical hash function:** `aqcs.utils.canonicalization.canonical_hash(data)`

### 13.3 Legacy Format (Existing Artifacts — pre 2026-05-19)

Existing artifact modules (manifest, registry, fleet monitoring, baseline report, walk-forward report, replay certificate) use:

```python
json.dumps(data, sort_keys=True)  # default separators: ", " and ": "
```

These formats produce **different byte sequences** and therefore **different SHA-256 hashes** from the same data. Do not attempt to cross-verify artifact hashes between the two formats.

**Legacy hash function:** `aqcs.utils.canonicalization.legacy_hash(data)`

### 13.4 Which Format Each Module Uses

| Module | Hash format | Field |
|---|---|---|
| `aqcs.data.manifest` | Legacy | `schema_hash`, content hashing |
| `aqcs.data.dataset_registry` | Legacy | `registry_hash`, `entries_hash` |
| `aqcs.monitoring.fleet_monitoring` | Legacy | `registry_hash`, `registry_entries_hash` |
| `aqcs.research.baseline_report` | Legacy | `report_hash` |
| `aqcs.research.walkforward` | Legacy | `report_hash` |
| `aqcs.research.replay_certificate` | Legacy (JSON) + binary (struct.pack) | config/params hash; numeric hashes |
| `aqcs.research.campaign` | **Canonical** | `campaign_hash` |
| `aqcs.research.benchmark_suite` | **Canonical** | `benchmark_hash` |

### 13.5 Migration Policy

Existing artifact schemas must NOT be changed to use the canonical format without:
- A formal ADR documenting the migration
- Explicit version field increment in the affected artifact
- Human approval from the Technical Auditor
- A documented migration guide for existing stored artifacts

Changing hash formats without versioning breaks replay compatibility and invalidates existing stored artifacts.

### 13.6 Excluded Fields

All self-certifying hashes exclude:
- The hash field itself (avoids circularity)
- `generation_timestamp_utc` (wall-clock; excluded for content-addressability)
- `campaign_id`, `benchmark_id` (derived from hash; excluded to avoid circularity)

---

## 14. Operational Validation Checklist

Run these commands in sequence after any code change before merging:

```bash
# 1. Formatting
black --check src tests scripts

# 2. Linting
ruff check src tests scripts

# 3. Type checking
mypy src

# 4. Full test suite
PYTHONPATH=src pytest tests/ -q --no-cov
```

**All four commands must pass cleanly before any PR can be merged.**

### Targeted Suites

```bash
# Architecture boundary enforcement (run after any import change)
PYTHONPATH=src pytest tests/architecture/ -q --no-cov

# Research artifact tests
PYTHONPATH=src pytest tests/research/ -q --no-cov

# Monitoring tests
PYTHONPATH=src pytest tests/monitoring/ -q --no-cov

# Data layer tests
PYTHONPATH=src pytest tests/data/ -q --no-cov
```

### Architecture Boundary Check

If any `src/aqcs/` import is modified, run the architecture boundary test explicitly:

```bash
PYTHONPATH=src pytest tests/architecture/test_dependency_boundaries.py -v --no-cov
```

A failing boundary test is a blocking CI failure. It must not be skipped or worked around.

---

## 15. Human Review Requirements

The following decisions **require explicit human review** and may not be automated:

| Decision | Review gate |
|---|---|
| Modifying `CURRENT_PHASE` in `phase_guard.py` | Technical Auditor + ADR |
| Enabling any blocked feature flag | Technical Auditor + ADR |
| Adding a new third-party dependency | Technical Auditor |
| Creating or modifying an ADR (`docs/decisions/`) | Technical Auditor |
| Merging to `master` | Technical Auditor (human approval) |
| Changing hash computation format | Technical Auditor + ADR + migration plan |
| Changing scoring weights in benchmark suite | Technical Auditor + ADR |
| Acting on benchmark suite rankings | Technical Auditor (advisory-only acknowledgment) |
| Proceeding after any validation failure | Human investigation and sign-off |

**No automated system may perform these actions without explicit human approval.**

### Review Sequence for Research Results

Before any operational decision downstream of a benchmark suite:

1. **Verify** the benchmark suite hash: `validate_benchmark_suite.py` → exit 0
2. **Review** all `regression_flags` in the benchmark suite
3. **Trace** each top-ranked campaign back to its source dataset manifests
4. **Confirm** replay certificates are valid for all experiments in the campaign
5. **Document** the review decision in `docs/bitacora/` with the benchmark suite hash
6. **Acknowledge** the advisory disclaimer explicitly

---

## 16. Forbidden Activities

The following activities are **prohibited in Phase 1** and will not be supported by AQCS infrastructure:

### 16.1 Trading and Execution

- **Live trading** — No code path submits orders to any exchange. `phase_guard.py` blocks `ORDER_EXECUTION`.
- **Paper trading** — No sandbox exchange accounts are used. `phase_guard.py` blocks `PAPER_TRADING`.
- **Execution automation** — No automated order generation, position management, or trade execution.
- **Portfolio automation** — No automated rebalancing, weight execution, or position sizing.
- **Exchange account access** — No private API keys are read, stored, or used in research workflows.

### 16.2 Autonomous Systems

- **Autonomous strategy mutation** — No system selects, modifies, or generates strategies without human approval.
- **ML/RL strategy generation** — No machine learning or reinforcement learning is used. `phase_guard.py` blocks `MACHINE_LEARNING`.
- **Hidden optimization loops** — All scoring is explicit, documented, and based on constant weights.
- **Adaptive scoring** — Benchmark scoring weights are fixed constants, not learned from data.
- **Schedulers and daemons** — No background workers, schedulers, cron jobs, or filesystem watchers.
- **Autonomous deployment decisions** — Rankings are advisory only; no system automates deployment.

### 16.3 Streaming and Real-Time Systems

- **WebSocket streaming** — `phase_guard.py` blocks `WEBSOCKET_STREAMING`.
- **Real-time data feeds** — All data is fetched on-demand via public REST endpoints only.
- **Background workers** — All processing is synchronous and invoked manually.

### 16.4 Data Manipulation

- **Implicit gap filling** — Gaps in OHLCV data are detected and reported; never silently filled.
- **Silent schema coercion** — Schema validation rejects non-conforming data; no implicit coercion.
- **Timezone conversion** — Non-UTC timestamps are rejected; no implicit timezone conversion.
- **Dataset mutation** — Research tools are read-only with respect to source Parquet files.
- **Manifest mutation** — Manifests are immutable. A new manifest for modified data has a different hash.

---

## 17. Incident and Drift Investigation Guidance

### 17.1 Hash Mismatch

**Symptom:** `verify_manifest`, `verify_certificate`, `validate_baseline_report`, `validate_campaign`, or `validate_benchmark_suite` reports a hash mismatch.

**Investigation procedure:**
1. Do not proceed with the workflow.
2. Identify which artifact failed verification.
3. Compare the stored hash to the recomputed hash.
4. Determine whether the artifact file was modified after generation (check file mtime, git history).
5. If the file was modified: determine what changed and why.
6. If the file was not modified: reproduce the hash computation step-by-step to identify serialization divergence.
7. Document findings in `docs/bitacora/`.
8. Regenerate the artifact from scratch if the original cannot be recovered.
9. Obtain human sign-off before resuming.

### 17.2 Replay Drift

**Symptom:** Re-running the same pipeline on the same dataset produces different metrics.

**Investigation procedure:**
1. Verify the dataset manifest hash matches the input Parquet file.
2. Verify the BacktestConfig (fee_bps, slippage_bps, dates) matches the original experiment record.
3. Verify the git commit hash matches the one recorded in the experiment record.
4. Check for any non-deterministic imports (randomness, wall-clock, global state).
5. Check for pandas/numpy version changes between runs.
6. Document the divergence in `docs/bitacora/` with full reproduction steps.
7. Do not proceed until the root cause is identified and documented.

### 17.3 Validation Failures

**Symptom:** Any validation script exits with code 1 or 2.

**Investigation procedure:**
1. Read the JSON output for the specific error messages.
2. For exit code 2 (configuration errors): verify CLI arguments, file paths, and directory structure.
3. For exit code 1 (validation failures): follow the specific error message to the failing check.
4. Do not suppress validation failures by altering threshold values without ADR approval.
5. Document the failure and resolution in `docs/bitacora/`.

### 17.4 Benchmark Regressions

**Symptom:** Benchmark suite reports regression flags for metrics that were previously within bounds.

**Investigation procedure:**
1. Identify which campaigns triggered regression flags and which thresholds were violated.
2. Trace the campaign back to its source dataset — verify the manifest hash is unchanged.
3. Check if the backtest configuration changed (fees, slippage, capital, date range).
4. Check if the dataset has additional rows or gaps since the previous benchmark run.
5. Run a fleet comparison between the current and previous fleet snapshots:
   ```bash
   PYTHONPATH=src python scripts/monitoring/compare_fleet_snapshots.py \
     --baseline data/fleet/fleet_snapshot_v_prev.json \
     --candidate data/fleet/fleet_snapshot_current.json
   ```
6. Document findings and any remediation steps.
7. Do not adjust regression thresholds without an ADR and human approval.

### 17.5 Dataset Inconsistencies

**Symptom:** Registry or fleet snapshot reports orphan manifests, missing manifests, or duplicate identities.

**Investigation procedure:**
1. Run `validate_dataset_registry.py` to get a structured report.
2. For orphan manifests: identify which Parquet file was removed or renamed.
3. For missing manifests: regenerate the manifest using `generate_manifest.py` and verify it.
4. For duplicate identities: identify which datasets share the same `content_hash` — this indicates identical data under different filenames, which may be intentional or an error.
5. Document all findings before modifying the dataset directory.

---

## 18. Merge and Review Discipline

### 18.1 Branch Conventions

- All changes must originate from a task-scoped branch, never directly from `master`.
- Branch naming: `feat/`, `fix/`, `docs/`, `test/`, `chore/`, `data/`, `exp/` prefixes + task identifier.
- Examples: `feat/task-monitoring-001`, `fix/task-arch-enforce-001`, `docs/task-research-runbook-001`.

### 18.2 Commit Format

**Task commits:** `<TASK-ID>: <imperative present-tense summary>`
Example: `TASK-006: add momentum signal`

**Non-task commits:** `fix:`, `docs:`, `feat:`, `test:`, `chore:` prefixes.

### 18.3 Pre-Merge Checklist

Before opening a PR, verify all four validation commands pass:

```bash
black --check src tests scripts
ruff check src tests scripts
mypy src
PYTHONPATH=src pytest tests/ -q --no-cov
```

### 18.4 Required PR Contents

Every PR must include:
1. A concise description of what changed and why.
2. Evidence that all four validation commands pass.
3. A handoff record in `docs/bitacora/` for agent-authored sessions.
4. For architecture changes: evidence that `tests/architecture/` passes.

### 18.5 Merge Sequence Discipline

When multiple PRs are open, merge in dependency order:
1. Infrastructure PRs before feature PRs that depend on them.
2. Architecture/governance PRs before feature PRs.
3. Never merge a PR that causes another open PR to conflict without coordinating the rebase.

When a PR adds a file that another open PR also adds (e.g., a prerequisite module copied to another branch): rebase the dependent branch after the prerequisite merges, confirm the duplicate file is removed, and re-push with `--force-with-lease`.

### 18.6 Handoff Documentation Discipline

Every agent session that modifies the repository must complete a handoff record in `docs/bitacora/` before stopping. The handoff must include:
- Branch, commit hash, PR link
- Files changed
- Validation results (all four commands)
- Risks and unresolved issues
- Rollback notes

---

## 19. Future Work Explicitly Deferred

The following capabilities are **explicitly deferred** to future AQCS phases. They are not on a committed roadmap and require separate ADR approval before implementation begins.

| Deferred capability | Reason for deferral |
|---|---|
| Live trading | Phase 4+; requires regulatory/legal review, exchange agreement, risk management |
| Paper trading / sandbox | Phase 3; requires exchange sandbox API access and execution logic |
| Execution engine (order submission) | Phase 3+; blocked by `phase_guard.PAPER_TRADING` and `ORDER_EXECUTION` |
| Portfolio automation | Phase 3+; blocked by `phase_guard.PAPER_TRADING` |
| WebSocket / real-time streaming | Phase 2+; blocked by `phase_guard.WEBSOCKET_STREAMING` |
| Machine learning signal generation | Phase 2+; blocked by `phase_guard.MACHINE_LEARNING` |
| Reinforcement learning | Phase 2+; blocked by `phase_guard.MACHINE_LEARNING` |
| Hyperparameter optimisation | Phase 2+; requires separate optimization framework ADR |
| Autonomous strategy mutation | Prohibited; requires human approval at all phases |
| Adaptive benchmark scoring | Prohibited; scoring weights are fixed constants by design |
| Automated deployment decisions | Prohibited; human review required at all phases |
| Distributed / multi-node execution | Phase 3+; requires architecture ADR |
| External database persistence | Phase 3+; requires architecture ADR |
| Scheduled / cron-triggered research | Phase 2+; requires scheduling framework ADR |

**This list does not constitute a roadmap commitment.** Each item requires a separate approved ADR, human authorization, and a dedicated implementation phase before work begins.

---

## 20. Phase-1 Boundaries

Phase 1 (Foundation / Research Layer) defines the current operational scope. The following constraints are **architectural** — enforced by `phase_guard.py`, verified by CI, and not configurable at runtime.

### 20.1 What Phase 1 Supports

- Read-only public OHLCV data acquisition (Binance Spot public REST API)
- Local Parquet persistence
- Deterministic data quality validation
- Dataset manifests and registry
- Fleet monitoring snapshots
- Deterministic backtesting (long-only, single-asset, daily bars)
- Experiment persistence (JSON, local filesystem)
- Replay certification
- Baseline research reporting
- Walk-forward temporal validation
- Research campaign orchestration
- Benchmark suite generation (advisory only)
- Canonical artifact hashing
- LLM oversight (read-only observation, no trading decisions)

### 20.2 What Phase 1 Does Not Support

All of the following are blocked by `phase_guard.py` in Phase 1:

- `ORDER_EXECUTION` — no orders submitted to any exchange
- `PAPER_TRADING` — no sandbox exchange accounts
- `LIVE_TRADING` — no live trading
- `MACHINE_LEARNING` — no ML/RL models
- `WEBSOCKET_STREAMING` — no real-time data feeds
- Portfolio automation
- Strategy mutation
- Autonomous deployment

### 20.3 Enforced Architecture Boundaries

The dependency DAG is checked on every CI push. Key constraints:
- `aqcs.research` may not import from `aqcs.execution`, `aqcs.risk`, `aqcs.portfolio`, or `aqcs.llm_oversight`
- `aqcs.llm_oversight` may import only from `aqcs.utils`
- Events flow from Quant Core → LLM Oversight only (never in reverse)
- The research layer is offline, deterministic, and read-only with respect to raw data

### 20.4 The Safety Guarantee

No code path in Phase 1 produces output that, if acted upon mechanically, would result in a real financial transaction. Every output is a document, report, or JSON artifact. Every ranking is advisory. Every metric is historical. Every result requires human interpretation and human action to have any operational consequence.

This guarantee is maintained by:
- `phase_guard.py` (runtime enforcement)
- `tests/architecture/test_dependency_boundaries.py` (import enforcement, CI)
- `tests/governance/test_anti_live_trading.py` (pattern enforcement, CI)
- `tests/governance/test_anti_llm_execution.py` (pattern enforcement, CI)
- Human review requirements on all merges and operational decisions

---

*Document maintained by: AQCS Technical Team*  
*Review cadence: On every Phase change or major infrastructure addition*  
*For discrepancies between this runbook and the enforced architecture, the enforced architecture takes precedence.*
