# OBJ-005: Minimal Research Core

**Objective ID:** OBJ-005  
**Status:** Complete  
**Phase:** 1  
**Date completed:** 2026-05-17  
**Parent:** OBJ-001

---

## Purpose

Implement the minimal deterministic research components needed before any backtesting engine. This phase establishes the correct abstraction boundaries: feature functions are pure transformations of raw data; signal functions translate features into directional views; neither touches portfolio construction, risk management, or execution.

---

## Scope

- Feature functions: simple_return, log_return, rolling_return, rolling_volatility, simple_moving_average, exponential_moving_average, distance_from_moving_average
- Signal functions: momentum_rank_signal, trend_filter_signal, combined_momentum_trend_signal
- SignalDirection type (re-exported from aqcs.utils.events)
- Input validation for all functions
- Lookahead safety tests for all functions
- Architecture documentation

Not in scope: portfolio construction, risk engine, execution simulation, backtesting engine, ML/RL signals, cross-sectional ranking, position sizing.

---

## Completed deliverables

| Deliverable | Files | Tests |
|-------------|-------|-------|
| Return features | `src/aqcs/features/returns.py` | `test_features.py::TestSimpleReturn, TestLogReturn, TestRollingReturn` |
| Volatility features | `src/aqcs/features/volatility.py` | `test_features.py::TestRollingVolatility` |
| Trend features | `src/aqcs/features/trend.py` | `test_features.py::TestSimpleMovingAverage, TestExponentialMovingAverage, TestDistanceFromMovingAverage` |
| Feature package init | `src/aqcs/features/__init__.py` | — |
| Signal types | `src/aqcs/signals/types.py` | `test_signals.py::TestSignalDirection` |
| Momentum signal | `src/aqcs/signals/momentum.py` | `test_signals.py::TestMomentumRankSignal` |
| Trend signal | `src/aqcs/signals/trend.py` | `test_signals.py::TestTrendFilterSignal` |
| Combined signal | `src/aqcs/signals/combined.py` | `test_signals.py::TestCombinedMomentumTrendSignal` |
| Signal package init | `src/aqcs/signals/__init__.py` | — |
| Architecture documentation | `docs/architecture/research-core.md` | — |
| ADR-006 | `docs/decisions/ADR-006-minimal-research-core.md` | — |

---

## Pending deliverables

| Deliverable | Phase | Notes |
|-------------|-------|-------|
| Cross-sectional signal ranking | 2 | Rank returns across multiple assets at each timestamp |
| RSI, Bollinger Bands, ATR | 2 | Additional technical features |
| Vectorised backtesting integration | 2 | Feature/signal functions consumed by backtesting engine |
| Factor exposure computation | 3+ | For portfolio construction |

---

## Acceptance criteria

- [x] All 7 feature functions implemented as pure functions
- [x] All 3 signal functions implemented as deterministic functions
- [x] No lookahead bias: partial-application tests verify causal correctness
- [x] Input validation: empty Series, non-numeric dtype, invalid windows rejected
- [x] Timestamp alignment preserved in all outputs
- [x] No portfolio, risk, or execution logic in features or signals
- [x] No EventBus dependency in features or signals
- [x] Architecture boundary enforced: signals → features → utils only
- [x] SignalDirection reused from aqcs.utils.events (no duplication)
- [x] 74 tests passing (42 feature tests + 32 signal tests)

---

## Related ADRs

- ADR-006: Minimal research core before backtesting engine
- ADR-005: Backtesting standards before engine
- ADR-002: Quant Core determinism (features/signals are part of Quant Core)
