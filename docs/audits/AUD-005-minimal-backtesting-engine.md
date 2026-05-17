# AUD-005: Minimal Backtesting Engine — Acceptance Audit

**Audit ID:** AUD-005  
**Date:** 2026-05-17  
**Auditor:** Claude Code (acting as Strategic Auditor)  
**Scope:** OBJ-006 — Minimal Backtesting Engine  
**Objective:** OBJ-006  
**Related handoff:** HND-005

---

## Scope

- `src/aqcs/backtesting/` — 5 modules + `__init__.py`
- `tests/unit/test_backtesting_engine.py` — 39 tests
- `docs/architecture/minimal-backtesting-engine.md`
- `docs/decisions/ADR-007-minimal-backtesting-engine.md`

---

## Critical blockers

None.

---

## Must fix before continuing

None identified.

---

## Should fix soon

1. **Win rate uses gross fill prices, not net P&L.** A trade with `sell.fill_price > buy.fill_price` is counted as a win, but if fees exceed the gross price gain, the trade is actually a net loss. This is documented but could mislead researchers. Consider adding `net_win_rate` (after fees) as an additional metric in Phase 2.

2. **`run_backtest()` accepts `tracker: object | None`.** To avoid circular import issues, the type annotation is `object | None` rather than `ExperimentTracker | None`. This bypasses mypy type checking on the tracker calls. Use `TYPE_CHECKING` guard or a Protocol in Phase 2.

3. **No validation that OHLCV passed the data validator.** `validate_backtest_inputs` checks structure (columns, timestamps, overlap) but does not verify OHLCV consistency (prices > 0, high ≥ low, etc.). The data validator (`src/aqcs/data/validator.py`) must be run before passing data to the engine. This is documented but not enforced by the engine itself.

---

## Nice to have

- `profit_factor` metric (total gross profit / total gross loss)
- `calmar_ratio` (CAGR / max_drawdown) as a standard risk-adjusted metric
- Date-range validation that checks start_date < end_date
- Integration test that runs a complete pipeline: download → validate → feature → signal → backtest

---

## Findings summary

| Area | Status | Notes |
|------|--------|-------|
| Next-bar execution enforcement | ✓ Accepted | `shift(1)` is structural, not configurable |
| No same-bar execution | ✓ Verified | `test_no_same_bar_execution` passes |
| Lookahead prevention | ✓ Verified | Timing tests cover all edge cases including first bar |
| Fee model | ✓ Accepted | Mandatory, on gross value, taker-only |
| Slippage model | ✓ Accepted | Mandatory, linear, conservative direction |
| Long-only enforcement | ✓ Verified | SHORT signals produce no action (tested) |
| No pyramiding | ✓ Verified | Second LONG while long produces no second buy |
| Determinism | ✓ Verified | Identical inputs → identical outputs (tested) |
| 8 required metrics | ✓ Accepted | All from backtesting-standards.md §I present |
| Experiment tracking | ✓ Accepted | Optional, correct lifecycle (create/complete/fail) |
| Architecture boundary | ✓ Accepted | backtesting → {experiments, utils} imports only |
| No live trading | ✓ Confirmed | No exchange calls, no order submission |

---

## Risks / concerns

**Low risk:**
- The engine stores equity_curve and trades as tuples in `BacktestResult`. For very long backtests (10+ years of daily data = 3,650+ bars), the tuple is still small. No memory concern for Phase 1.
- The metrics use `statistics.stdev` from stdlib, which uses Bessel's correction (n-1 denominator). This is the standard sample standard deviation. Some systems use population std (n). Document this explicitly if comparing with other tools.

---

## Recommendations

1. **Mark OBJ-006 as complete.**
2. **Conduct a formal Phase 1 closure audit.** All six Phase 1 objectives are now complete.
3. **In Phase 2**, add `profit_factor` and `calmar_ratio` to the standard metrics.
4. **Before any live research,** always run OHLCV through `validate_ohlcv()` before passing to `run_backtest()`. Consider adding this check to the engine in Phase 2.

---

## Go / No-Go verdict

**GO** — OBJ-006 Minimal Backtesting Engine is accepted as complete.

39 tests pass, covering all critical invariants. The engine correctly enforces next-bar execution, mandatory fees/slippage, long-only, no pyramiding, and determinism.

---

## Final technical verdict

The Minimal Backtesting Engine is accepted.

**AQCS Phase 1 is now complete across all six objectives:**

| Objective | Status |
|-----------|--------|
| OBJ-001: Foundation Layer | ✓ Complete |
| OBJ-002: Data Validation Layer | ✓ Complete |
| OBJ-003: Experiment Tracking Layer | ✓ Complete |
| OBJ-004: Backtesting Standards Layer | ✓ Complete |
| OBJ-005: Minimal Research Core | ✓ Complete |
| OBJ-006: Minimal Backtesting Engine | ✓ Complete |

**751+ tests passing. Formal Phase 1 closure audit is the recommended next step before advancing to Phase 2.**

---

## Related documents

- OBJ-006: `docs/objectives/OBJ-006-minimal-backtesting-engine.md`
- HND-005: `docs/handoffs/HND-005-minimal-backtesting-engine.md`
- ADR-007: `docs/decisions/ADR-007-minimal-backtesting-engine.md`
- `docs/architecture/minimal-backtesting-engine.md`
- `docs/architecture/backtesting-standards.md`
