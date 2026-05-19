## AI Handoff

### Handoff ID
`HND-023`

### Task ID
`TASK-WALKFORWARD-VALIDATION-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-009 Deterministic Walk-Forward Validation`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-19

### Status
complete — PR open, pending human review

---

### What was changed

Implemented deterministic walk-forward validation infrastructure in
`src/aqcs/research/walkforward.py`. Walk-forward validation divides a
historical series into sequential temporal windows, runs the AQCS signal
pipeline on each window's test period, and produces a reproducible,
leakage-safe report.

### Branch
`feat/task-walkforward-validation-001`

### Commit
`3c4e5b3` — TASK-WALKFORWARD-VALIDATION-001: add deterministic walk-forward validation

---

### Files Changed

```text
src/aqcs/research/walkforward.py        — core module
scripts/research/run_walkforward.py     — CLI: run walk-forward on parquet
scripts/research/validate_walkforward.py — CLI: validate existing report
tests/research/test_walkforward.py      — 52 tests
docs/bitacora/2026-05-19-HND-023-walkforward-validation-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

---

## Walk-Forward Schema

**Window layout (example: train=500, test=100, step=100):**

```
Window 0: train [0, 500)   test [500, 600)
Window 1: train [100, 600) test [600, 700)
Window 2: train [200, 700) test [700, 800)
...
```

**`WalkForwardWindow`** (frozen dataclass):
- `window_index, train_start_bar, train_end_bar, test_start_bar, test_end_bar, train_bars, test_bars`

**`WalkForwardResult`** (frozen dataclass — per window):
- Same bar index fields + `metrics: dict[str, float]`, `n_trades`, `n_bars_evaluated`
- `failed: bool`, `failure_reason: str` for graceful error handling

**`WalkForwardSummary`** (frozen dataclass):
- `n_windows_total/evaluated/failed/profitable`
- `mean/std/min/max_total_return`, `mean_sharpe_ratio`, `mean_max_drawdown`
- `mean_trade_count`, `test_overlap: bool`

**`WalkForwardReport`** (frozen dataclass):
- 14 fields: `report_version`, `generation_timestamp_utc`, `dataset_path`, `total_bars`
- Window parameters: `train_bars, test_bars, step_bars, n_windows`
- `windows, results, summary` (all tuples, immutable)
- `leakage_validated, validation_issues, report_hash`

---

## Determinism Strategy

| Property | Implementation |
|---|---|
| Window generation | Deterministic loop: `train_start += step_bars`; sorted ascending |
| Report hash | SHA-256 of `json.dumps(report_dict, sort_keys=True)` (hash excluded from dict) |
| NaN equality | `float("nan") != float("nan")` — comparisons use JSON round-trip (null == null) |
| Signal computation | Per window: `signal_fn(prices[:test_end_bar])` — no future data |
| Backtest date range | `start_date`/`end_date` set to test period timestamps per window |
| `generation_timestamp_utc` | Wall-clock only; injected via `now_utc` in tests |

---

## Leakage Prevention Logic

**Within each window:** `train_end_bar == test_start_bar` (enforced by construction). The signal is computed on `ohlcv[:test_end_bar]` — no data from the future is visible. The backtest is filtered to `[test_start_bar, test_end_bar)` via config `start_date`/`end_date`.

**Validation checks in `validate_windows`:**
1. `window_index` matches loop index
2. `train_end_bar == test_start_bar` (no gap, no overlap within window)
3. Training period not empty (`train_start < train_end`)
4. Test period not empty (`test_start < test_end`)
5. Training does not exceed test end (`train_end <= test_end`)
6. Windows in ascending order by `train_start_bar`
7. Test frontier always advances (`curr.test_start_bar > prev.test_start_bar`)

**Test overlap across windows:** If `step_bars < test_bars`, consecutive test windows overlap in calendar time. This is flagged in `summary.test_overlap` but not rejected — the user may intentionally use fine-grained steps.

---

## Validation Logic

`validate_report(report)`:
1. Re-derives `report_hash` from report content (excluding hash field)
2. Checks `report_version == REPORT_VERSION`
3. Calls `validate_windows(report.windows)` for temporal consistency
4. Checks `n_windows == len(windows)`

Returns `(is_valid: bool, errors: list[str])`.

---

## CLI Behavior

**`run_walkforward.py`**
```bash
PYTHONPATH=src python scripts/research/run_walkforward.py \
  --dataset data/burn_in/BTC_USDT_1h.parquet \
  --train-bars 500 --test-bars 100 --step-bars 100 \
  --output-json reports/walkforward_report.json
```
- Exit 0: clean completion
- Exit 1: issues (failed windows or leakage)
- Exit 2: config/load errors

**`validate_walkforward.py`**
```bash
PYTHONPATH=src python scripts/research/validate_walkforward.py \
  --walkforward-json reports/walkforward_report.json
```
- Exit 0: valid; 1: invalid; 2: load error

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/research/test_walkforward.py -q --no-cov
# 52 passed in 1.84s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1179 passed in 6.60s

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
| `TestGenerateWindows` | 12 | Count, bar indices, step advance, ordering, exactly-fits, zero windows when sum>total (raises), invalid params, field correctness |
| `TestValidateWindows` | 7 | Generated windows pass, empty pass, train/test gap detected, wrong index, wrong order, empty test period, train overlaps test |
| `TestRunWalkforward` | 9 | Deterministic JSON, hash deterministic, window count, bar indices, leakage validated, test_overlap flag, step≥test no overlap, empty dataset raises, invalid params |
| `TestNoLookahead` | 2 | Signal receives exactly test_end_bar rows, later windows receive more data |
| `TestSummaryMetrics` | 3 | Evaluated excludes failures, profitable counted, empty case |
| `TestValidateReport` | 4 | Valid passes, hash tampered, wrong version, n_windows mismatch |
| `TestSerialization` | 8 | Round-trip dict (via JSON), JSON deterministic, NaN→null, save/load, invalid JSON, missing field, immutable, parent dirs |
| `TestStableOrdering` | 2 | Windows ascending by train_start, results ascending by index |
| `TestCLIValidate` | 4 | Exit 0/1/2, required fields |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (39 source files) | PASS |
| pytest walk-forward (52 tests) | PASS |
| pytest full suite (1179 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies | PASS |
| No optimization/ML/RL | PASS |
| No execution logic | PASS |

---

## Risks

- `float("nan") != float("nan")` prevents direct `WalkForwardReport` equality when metrics contain NaN (e.g. `win_rate` when no trades). Tests use JSON-based comparison to handle this. Production code is not affected — reports are compared by hash or by JSON serialization.
- `test_overlap=True` is informational only. If `step_bars < test_bars`, test windows overlap but the implementation does not reject this. The caller is responsible for interpreting overlapping test results.
- The default signal (`combined_momentum_trend_signal(prices, 20, 10, 50)`) requires at least 50 bars of warmup. Windows with `train_bars < 50` will produce mostly NEUTRAL signals but will not error.

## Unresolved Issues

PRs #10–16 still open. No dependency on them.

## Rollback Notes

Delete 4 new files. No existing files modified.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master
- [x] PRs #10-16 noted as open; no dependency on them
- [x] No forbidden files modified
- [x] No optimization, ML/RL, or execution logic
- [x] No-lookahead preservation verified by tests
- [x] black / ruff / mypy pass
- [x] 52 tests pass
- [x] 1179 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
