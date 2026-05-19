## AI Handoff

### Handoff ID
`HND-022`

### Task ID
`TASK-BASELINE-RESEARCH-REPORT-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-008 Deterministic Baseline Research Reporting`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-19

### Status
complete — PR open, pending human review

---

### What was changed

Implemented deterministic baseline research reporting in `src/aqcs/research/baseline_report.py`.
Reports are immutable, self-certifying, and include extended cost/turnover/benchmark
metrics alongside reproducibility references (dataset hashes, replay certificate hash).

### Branch
`feat/task-baseline-research-report-001`

### Commit
`f004ae3` — TASK-BASELINE-RESEARCH-REPORT-001: add deterministic baseline research reports

---

### Files Changed

```text
src/aqcs/research/baseline_report.py        — core module
scripts/research/build_baseline_report.py   — CLI: generate report from artifacts
scripts/research/validate_baseline_report.py — CLI: validate existing report
tests/research/test_baseline_report.py      — 41 tests
docs/bitacora/2026-05-19-HND-022-baseline-research-report-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

---

## Report Schema

**`BaselineReport`** (frozen dataclass — 37 fields):

**Identity:**
- `report_version`, `experiment_id`, `experiment_name`, `git_commit_hash`
- `generation_timestamp_utc` (ISO-8601, wall-clock only field)
- `report_hash` (SHA-256 of report content excluding itself)
- `disclaimer` (safety statement, non-empty)

**Dataset references:**
- `dataset_content_hash`, `dataset_schema_hash` (from DatasetManifest)
- `dataset_symbol`, `dataset_timeframe`, `dataset_exchange`
- `dataset_start_utc`, `dataset_end_utc`, `dataset_row_count`

**Replay reference:**
- `replay_certificate_hash`, `replay_certified`

**Configuration:**
- `initial_capital`, `fee_bps`, `slippage_bps`, `start_date`, `end_date`
- `periods_per_year`, `n_bars`

**Core metrics (from `compute_metrics`):**
- `total_return`, `cagr`, `max_drawdown`, `sharpe_ratio`
- `annualised_volatility`, `trade_count`, `win_rate`, `exposure`

**Extended cost metrics:**
- `total_fees_paid` — sum of all trade fees
- `total_slippage_cost` — sum of all slippage amounts
- `avg_trade_value` — average buy trade notional value
- `turnover_per_bar` — total_bought / initial_capital / n_bars

**Holding period:**
- `avg_holding_period_bars` — bars_long / trade_count
- `max_consecutive_losses` — max streak of losing round trips (net of fees)

**Benchmark comparison:**
- `benchmark_total_return` — buy-and-hold return (price[-1] / price[0] - 1)
- `excess_return` — total_return - benchmark_total_return

**Artifact hash:**
- `metrics_hash` — SHA-256 over sorted (key, float64 LE) metric pairs

---

## Determinism Strategy

| Property | Implementation |
|---|---|
| `report_hash` | SHA-256 of `json.dumps(report_dict, sort_keys=True)` with `report_hash` excluded |
| `metrics_hash` | SHA-256 over sorted key+float64-LE pairs (same approach as ReplayCertificate) |
| NaN serialization | `float("nan")` → `null` in JSON (JSON-spec compliant); `null` → `float("nan")` on load |
| Benchmark return | Derived from equity curve price field (close price); deterministic from BacktestResult |
| `excess_return` | `result.metrics["total_return"] - benchmark_total_return` (uses authoritative metrics value) |
| Float precision | All metric floats at float64 precision from `compute_metrics` |
| `generation_timestamp_utc` | Wall-clock only; injected via `now_utc` in tests |

---

## Validation Logic

`validate_report(report)`:
1. Re-derive `report_hash` from the report's own fields (excluding the stored hash)
2. Compare with stored `report.report_hash` → mismatch = tampered
3. Check `report_version == REPORT_VERSION`
4. Check `n_bars > 0`

Returns `(is_valid: bool, errors: list[str])`. Callers can surface all errors.

---

## CLI Behavior

**`build_baseline_report.py`**
```bash
PYTHONPATH=src python scripts/research/build_baseline_report.py \
  --experiment-dir experiments/sample_experiment/ \
  --output-json reports/baseline_report.json
```
- Finds `experiment_*.json` in `experiment_dir`
- Loads equity/trades parquets from `artifacts_dir/{experiment_id}/`
- Builds and validates report
- Exit 0: valid; 1: validation fail; 2: load error

**`validate_baseline_report.py`**
```bash
PYTHONPATH=src python scripts/research/validate_baseline_report.py \
  --report-json reports/baseline_report.json
```
- Loads report JSON
- Re-derives hash, checks version and n_bars
- Exit 0: valid; 1: validation fail; 2: load error

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/research/test_baseline_report.py -q --no-cov
# 41 passed in 0.90s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1168 passed in 6.59s

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
| `TestReportGeneration` | 6 | All fields, timestamp injection, experiment record, dataset/replay passthrough, config |
| `TestReportHash` | 3 | Deterministic, changes on metric change, metrics_hash format |
| `TestBenchmarkMetrics` | 3 | Buy-and-hold calculation, excess_return = total - benchmark, empty equity NaN |
| `TestCostMetrics` | 4 | Fees, slippage, avg_trade_value (buys only), no-trades NaN |
| `TestTurnoverMetrics` | 2 | Formula correctness, zero n_bars NaN |
| `TestHoldingPeriod` | 2 | Positive when trades exist, NaN when no trades |
| `TestMaxConsecutiveLosses` | 4 | All wins = 0, all losses = n, mixed, no trades |
| `TestValidation` | 4 | Valid passes, tampered hash detected, wrong version detected, zero n_bars |
| `TestSerialization` | 9 | Round-trip dict, NaN→null, null→NaN, JSON deterministic, save/load, invalid JSON, missing field, immutable, disclaimer non-empty |
| `TestCLIValidate` | 4 | Exit 0 valid, exit 1 tampered, exit 2 malformed, required fields |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (39 source files) | PASS |
| pytest baseline report (41 tests) | PASS |
| pytest full suite (1168 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies introduced | PASS |
| No execution logic | PASS |
| No optimization/ML/RL | PASS |
| Safety disclaimer present | PASS |

---

## Risks

- `excess_return` uses `result.metrics["total_return"]` (authoritative) vs `benchmark_total_return` (equity-curve-derived). If `metrics["total_return"]` is not computed from the same equity curve, the excess return would be inconsistent. When using the AQCS backtesting engine (`run_backtest`), these are always consistent.
- NaN values in `result.metrics` are serialized as `null` in JSON. Loading a report and re-serializing preserves this. Arithmetic on NaN propagates correctly.

## Unresolved Issues

PRs #10–15 still open. This PR has no dependency on them.

## Rollback Notes

Delete 4 new files. No existing files modified.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master
- [x] PRs #10-15 noted as open; no dependency on them
- [x] No forbidden files modified
- [x] No execution logic introduced
- [x] Safety disclaimer included in every report
- [x] No optimization, ML/RL, or parameter search
- [x] black / ruff / mypy pass
- [x] 41 tests pass
- [x] 1168 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
