# AQCS Minimal Backtesting Engine — Phase 1

**Version:** 1.0.0  
**Date:** 2026-05-17  
**Status:** Active  
**Implementation:** `src/aqcs/backtesting/`  
**Related standards:** `docs/architecture/backtesting-standards.md`

---

## Purpose

The minimal backtesting engine provides a deterministic, auditable simulation of a strategy over historical OHLCV data. Its goal is **correctness and reproducibility, not performance**.

One valid backtest with explicit assumptions is worth more than a thousand optimistic simulations.

---

## Phase 1 assumptions (intentional constraints)

These are not temporary limitations — they are the correct starting point for institutional research. Each constraint is documented with its rationale.

| Assumption | Value | Rationale |
|-----------|-------|-----------|
| Bar frequency | Daily only | Intrabar simulation requires tick data and microstructure models not in scope |
| Direction | Long-only | Short selling requires margin, borrow cost, forced-close risk — not modelled in Phase 1 |
| Asset count | Single asset | Multi-asset requires portfolio construction, which is a separate layer |
| Position sizing | Fixed fraction of equity | Simple, deterministic, auditable |
| Max positions | 1 (no pyramiding) | Simplest valid model; avoids average-cost complexity |
| Execution | Next-bar open | Canonical safe default; avoids bar-close omniscience |
| Leverage | None | Phase Guard enforces this; Phase 3+ decision |
| Partial fills | None | Not modelled in daily bar simulation |
| Intrabar simulation | None | Only bar-level OHLCV available |

---

## Timing semantics (anti-lookahead guarantee)

```
Bar T close: signal[T] generated from data[0..T]
            ↓
Bar T+1 open: execution[T+1] = f(signal[T])
```

This is enforced structurally by `signals.shift(1)` before the simulation loop. `shifted[T] = signals[T-1]`. At bar T, the engine reads `shifted[T]` — which is the signal generated at bar T-1. **A signal at bar T can never influence bar T's execution.**

Tests verify this invariant in `tests/unit/test_backtesting_engine.py`:
- `test_signal_at_T_executes_at_T_plus_1`
- `test_no_same_bar_execution`
- `test_first_bar_signal_cannot_execute_same_bar`

---

## Execution model

### Buy order

```
fill_price = open[T] × (1 + slippage_factor)
quantity   = (cash × position_size_fraction) / (fill_price × (1 + fee_factor))
fee        = quantity × fill_price × fee_factor
cost       = quantity × fill_price + fee
cash      -= cost
position  += quantity
```

### Sell order

```
fill_price = open[T] × (1 - slippage_factor)
value      = position × fill_price
fee        = value × fee_factor
proceeds   = value - fee
cash      += proceeds
position   = 0
```

---

## Fee and slippage modelling

Both are mandatory. `fee_bps=0` and `slippage_bps=0` are explicitly allowed (for testing purposes) but must be set deliberately in `BacktestConfig`. There is no implicit zero-cost default.

**Slippage convention:**
- Buy: slippage increases the fill price (costs more)
- Sell: slippage decreases the fill price (receive less)
- Both are conservative (worst-case for the strategy)

**Fee convention:**
- Charged on the gross transaction value (fill_price × quantity)
- Applied at fill time, not deferred
- Taker fee only (no maker rebate modelled in Phase 1)

---

## Required metrics

All metrics are computed from the equity curve and trade log. See `src/aqcs/backtesting/metrics.py` for formulas.

| Metric | Formula | Annualisation |
|--------|---------|--------------|
| `total_return` | (final - initial) / initial | None |
| `cagr` | (final/initial)^(1/n_years) - 1 | 365.25 calendar days/year |
| `max_drawdown` | max(peak - trough) / peak | None |
| `sharpe_ratio` | (mean_period_ret / std_period_ret) × sqrt(periods_per_year) | periods_per_year from config |
| `annualised_volatility` | std(period_returns) × sqrt(periods_per_year) | periods_per_year from config |
| `trade_count` | count of buy orders | None |
| `win_rate` | profitable trades / completed trades | None |
| `exposure` | bars_long / total_bars | None |

**Sharpe assumption:** zero risk-free rate. This is conservative and standard for crypto research.

---

## Experiment Tracking integration

Every backtest that provides an `ExperimentTracker` creates an `ExperimentRecord` with:
- `experiment_type = "backtest"`
- `parameters`: full `BacktestConfig` snapshot
- `metrics`: computed metrics after completion
- `dataset_paths`: for fingerprinting (if provided)
- `git_commit_hash`: captured at run time

If the backtest fails, the record transitions to `FAILED` with the error reason.

---

## Limitations (Phase 1)

- No cross-asset correlation or portfolio allocation
- No transaction cost optimisation
- No slippage as a function of order size (linear slippage only)
- No market impact modelling
- No bid-ask spread book-building
- No tick-level price path within a bar
- Win rate calculated from fill price only (ignores fees)
- No survivorship bias correction (user is responsible for universe selection)
- No walk-forward or out-of-sample validation (Phase 3+)

---

## Future expansion

The engine is designed for clean extension:
- `execution.py` is a set of pure functions — a new execution model can replace them without changing `engine.py`
- `metrics.py` can be extended with additional metrics
- Multi-asset support requires a portfolio construction layer (`aqcs.portfolio`) that is not yet implemented
- The `BacktestResult` model can gain additional fields without breaking existing code
