## AI Handoff

### Handoff ID
`HND-010`

### Task ID
`TASK-003B-E2E-PIPELINE`

### Objective
`OBJ-001 — Foundation Layer`

### Agent
Claude Code (Opus 4.7)

### Date
2026-05-17

### Status
complete

---

### What was changed

Implemented the first minimal deterministic end-to-end research pipeline for AQCS.
On inspection, a prior agent (Codex) had already produced an untracked
`src/aqcs/research/` library and its unit tests. This session committed both
that implementation and a new CLI wrapper layer in `scripts/research/`.

**Two complementary layers were committed together:**

1. **`src/aqcs/research/` (Codex implementation, newly tracked)**
   - `research_validation.py` — importable library that wires
     `validate_ohlcv → combined_momentum_trend_signal → run_backtest`
     and persists 4 typed artifacts (equity_curve.parquet, trades.parquet,
     signals.parquet, metrics.json) per experiment run
   - `ResearchValidationConfig` — frozen dataclass with explicit parameters
     (fee_bps, slippage_bps, gap_policy, etc.)
   - `ResearchValidationResult` — typed result with `experiment`, `backtest`,
     and `artifacts` fields
   - `gap_policy="halt"` rejects OHLCV data that produces validation warnings

2. **`scripts/research/run_pipeline.py` (new click CLI wrapper)**
   - `run_research_pipeline()` — callable function for testing; returns dict
     with `experiment_id`, `metrics`, `n_bars`, `n_trades`,
     `signal_counts`, and `feature_summary`
   - CLI flags for all pipeline parameters (`--fee-bps`, `--slippage-bps`,
     `--momentum-window`, `--trend-short`, `--trend-long`, etc.)
   - Computes diagnostic features: `log_return`, `rolling_volatility`,
     `simple_moving_average`, `distance_from_moving_average` (reported
     in `feature_summary`, not passed to signal)
   - Rejects non-UTC, non-monotonic, and duplicate timestamps via
     `validate_ohlcv` before any backtest

3. **`scripts/run_research_validation.py` (Codex CLI, newly tracked)**
   - argparse CLI for `src/aqcs/research/`

4. **`CLAUDE.md` (new)**
   - Compact reference for future agents: commands, DAG, non-obvious API
     invariants (experiment_id field, timestamp column vs. index, mandatory
     fee_bps/slippage_bps, BacktestResult.metrics is a dict not attributes),
     what is implemented vs. stub, git and governance rules

### Files changed

```text
src/aqcs/research/__init__.py                       — research package (Codex)
src/aqcs/research/research_validation.py            — core library (Codex)
scripts/run_research_validation.py                  — argparse CLI (Codex)
scripts/research/__init__.py                        — new
scripts/research/run_pipeline.py                    — click CLI wrapper
tests/unit/test_research_validation.py              — 8 tests for aqcs.research (Codex)
tests/research/__init__.py                          — new
tests/research/conftest.py                          — sys.path for script import
tests/research/test_pipeline.py                     — 11 tests for CLI wrapper
CLAUDE.md                                           — agent context file
docs/bitacora/2026-05-17-HND-010-e2e-pipeline.md   — this handoff
```

### Tests run

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# Result: 866 passed in 4.61s

.venv/bin/ruff check src/ tests/ scripts/
# Result: All checks passed

.venv/bin/black --check src/ tests/ scripts/
# Result: All files unchanged

.venv/bin/mypy src/
# Result: Success: no issues found in 32 source files
```

### Verification result

- [x] pytest (866 passed, 0 failed, 0 errors)
- [x] ruff
- [x] black
- [x] mypy
- [x] Architecture boundary tests pass (aqcs.research is exempt from DAG check
      by design — `if owner not in ALLOWED: return`)
- [x] Phase guard not touched
- [x] No forbidden files edited

---

### Pipeline invariants confirmed by tests

| Invariant | Test |
|-----------|------|
| UTC-aware timestamps required | `test_rejects_naive_timestamps` |
| Non-monotonic timestamps rejected | `test_rejects_non_monotonic_timestamps` |
| Duplicate timestamps rejected | `test_rejects_duplicate_timestamps` |
| All 8 metric keys present in output | `test_metrics_contain_required_keys` |
| Experiment artifact persisted with completed status | `test_experiment_artifact_persisted` |
| Artifact metrics match function return value | `test_artifact_metrics_match_return_value` |
| Deterministic: same inputs → same outputs | `test_deterministic_across_runs` |
| Signal series spans full price history (not filtered range) | `test_signal_counts_cover_all_bars` |
| Feature summary populated | `test_feature_summary_populated` |

### Architecture note

`src/aqcs/research/` imports from `aqcs.backtesting`, `aqcs.data`, `aqcs.experiments`,
and `aqcs.signals`. The architecture boundary test does `return` early for packages
not in `ALLOWED`, so `aqcs.research` is unregulated by the DAG enforcement. This is
intentional — research acts as a top-level orchestration layer above all other packages.
If this should be added to `ALLOWED`, that requires editing `tests/architecture/`
(human approval needed).

### Decisions made

1. **Kept both implementations** — Codex's `src/aqcs/research/` (importable library
   with 4 artifact types) and the new `scripts/research/run_pipeline.py` (click CLI
   with feature_summary and signal_counts). They are complementary, not duplicates:
   one is a stable importable API, the other is an exploratory research CLI.

2. **Signals generated from full price history** — Features and signals are computed
   on the entire loaded Parquet (all rows), and `start_date`/`end_date` filtering is
   delegated to the engine. This ensures warmup bars fall before the backtest window.

3. **Experiment created before backtest** — The experiment record is written before
   `run_backtest()` is called. If the backtest fails, `fail_experiment()` is called.
   This ensures no experiment is silently lost on error.

### Risks / concerns

- `aqcs.research` is not in the ALLOWED DAG — if a future agent adds `aqcs.research`
  as a dependency of another package, the architecture test won't catch it.
- `test_research_validation.py` uses `gap_policy="halt"` exclusively; edge cases
  around gap-tolerant runs are untested.

### Deferred work

- Add `aqcs.research` to `ALLOWED` dict in the architecture test (requires human
  approval to edit `tests/architecture/`).
- Extend `ResearchValidationConfig` to support `gap_policy="warn"` (log but continue).
- Walk-forward validation and multi-asset pipeline (Phase 3 scope).

---

### Human approval needed

- [ ] No — this is a documentation and research tooling addition within OBJ-001 scope.
      No phase constraints, feature flags, ADRs, or execution pathways affected.
