# AQCS Minimal Research Core — Phase 1

**Version:** 1.0.0  
**Date:** 2026-05-17  
**Status:** Active  
**Implementation:** `src/aqcs/features/`, `src/aqcs/signals/`

---

## Purpose

The Minimal Research Core provides the deterministic, pure functions needed to compute features and generate signals before any backtesting engine exists. It establishes the correct abstraction boundaries — feature functions and signal functions are separated from portfolio construction, risk management, and execution — so that these boundaries are enforced structurally from the first line of research code.

---

## What this is NOT

This is not a strategy engine. It does not:
- Size positions
- Compute portfolio weights
- Apply risk limits
- Submit orders
- Simulate execution
- Use ML/RL
- Call external APIs

Signal functions output a direction (`LONG`, `SHORT`, `NEUTRAL`). What to do with that direction is the responsibility of higher layers (portfolio, risk, execution) that are implemented in later phases.

---

## Feature layer (`src/aqcs/features/`)

### Responsibilities

- Compute derived quantities from raw OHLCV data
- Accept `pd.Series` inputs and return `pd.Series` outputs
- Be pure: no side effects, no file IO, no network calls, no event bus
- Be deterministic: same input always produces same output
- Respect timestamp alignment: output index matches input index
- Use only current and past data: no lookahead

### Available functions

| Function | Module | Description |
|----------|--------|-------------|
| `simple_return` | `returns` | Period-over-period arithmetic return |
| `log_return` | `returns` | Period-over-period log return |
| `rolling_return` | `returns` | N-period rolling arithmetic return |
| `rolling_volatility` | `volatility` | Rolling std of returns, optionally annualised |
| `simple_moving_average` | `trend` | Trailing equal-weight average of prices |
| `exponential_moving_average` | `trend` | Causal EMA using adjust=False |
| `distance_from_moving_average` | `trend` | (price - SMA) / SMA |

### Lookahead prevention

Every feature function satisfies: `f(data[0..T]) == f(data[0..T+K])[T]` for any K > 0. This is verified in `tests/unit/test_features.py` using the "partial application" test: applying a function to data through T gives the same result as applying it to the full series and reading index T.

Rolling windows use `min_periods=window` to produce NaN for the warm-up period rather than computing on incomplete windows.

EMA uses `adjust=False` (causal/recursive form) to avoid any implicit use of future data in the weighting scheme.

### Input validation

All feature functions validate:
- Input is a `pd.Series`
- Input is non-empty
- Input has a numeric dtype
- Window parameters are positive integers

---

## Signal layer (`src/aqcs/signals/`)

### Responsibilities

- Translate feature values into directional signals (`LONG`, `SHORT`, `NEUTRAL`)
- Accept feature Series as inputs, return `pd.Series[SignalDirection]`
- Be deterministic: same input always produces same signal
- Use only current and past data: no future returns, no forward-looking logic
- Have no portfolio, sizing, or execution logic

### Available functions

| Function | Module | Description |
|----------|--------|-------------|
| `momentum_rank_signal` | `momentum` | Time-series momentum via expanding percentile rank |
| `trend_filter_signal` | `trend` | MA crossover: short MA vs long MA |
| `combined_momentum_trend_signal` | `combined` | LONG/SHORT only when both momentum and trend agree |

### SignalDirection

Signal functions return `pd.Series` containing `SignalDirection` values from `aqcs.utils.events`. The enum is re-exported from `aqcs.signals.types` for convenience:

```python
class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"
```

Using the canonical enum from the Event Schema ensures consistency between signal values in research code and in emitted events.

### Lookahead prevention

Signal functions are tested with the same partial-application method as features. No signal at time T may use data from T+1 or later.

`momentum_rank_signal` uses `expanding().rank(pct=True)` — the percentile rank of the current rolling return within the expanding history from 0 to T. This is causal by construction.

`trend_filter_signal` uses two SMAs, both of which are causal.

`combined_momentum_trend_signal` is LONG only when both component signals are independently LONG, and SHORT only when both are SHORT. Disagreement produces NEUTRAL.

---

## Strict separation from portfolio/risk/execution

The feature and signal layers do not import from:
- `aqcs.portfolio`
- `aqcs.risk`
- `aqcs.execution`
- `aqcs.backtesting`
- `aqcs.monitoring`
- `aqcs.llm_oversight`

This boundary is enforced by `tests/architecture/test_dependency_boundaries.py`, which runs on every CI push.

`aqcs.signals` may import from `aqcs.features` and `aqcs.utils`.  
`aqcs.features` may import from `aqcs.utils` only (currently uses only stdlib + numpy/pandas).

---

## Limitations (Phase 1)

- No cross-sectional ranking: all signals operate on a single price/return series at a time
- No factor models, no ML-based signals, no statistical arbitrage
- No portfolio weight generation
- No position sizing
- No risk-adjusted signals
- EMA warm-up period: `min_periods=span` — NaN for the first `span` bars
- Momentum signal warm-up: `min_periods=momentum_window` for the expanding rank

---

## Future integration with backtesting

When the backtesting engine (`aqcs.backtesting.engine`) is implemented, it will consume:
1. Raw OHLCV DataFrames (from `aqcs.data`)
2. Feature Series (computed by `aqcs.features` functions)
3. Signal Series (computed by `aqcs.signals` functions)

The backtesting engine will apply the execution timing rules from `docs/architecture/backtesting-standards.md §E`: signals at bar-T close trigger executions at bar-(T+1) open.

The research core functions do not need to change when the backtesting engine is added — they are consumed as pure inputs.
