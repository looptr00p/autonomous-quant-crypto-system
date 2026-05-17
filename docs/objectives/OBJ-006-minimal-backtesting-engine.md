# OBJ-006: Minimal Backtesting Engine

**Objective ID:** OBJ-006  
**Status:** Complete  
**Phase:** 1  
**Date completed:** 2026-05-17  
**Parent:** OBJ-001

---

## Purpose

Implement the first deterministic backtesting engine for AQCS, satisfying the standards defined in OBJ-004. Prioritises correctness, reproducibility, and auditability over feature completeness.

---

## Scope

- `BacktestConfig` (Pydantic model with validation)
- `run_backtest()` engine with next-bar execution enforcement
- Deterministic simulation loop (buy/sell/mark-to-market)
- Fee and slippage models (mandatory)
- 8 required metrics (total_return, CAGR, max_drawdown, Sharpe, volatility, trade_count, win_rate, exposure)
- ExperimentTracker integration (optional)
- Input validation (empty data, missing columns, timestamp ordering, no overlap)
- 39 tests verifying all critical invariants

Not in scope: portfolio construction, multi-asset, shorting, leverage, optimisation, intrabar simulation.

---

## Completed deliverables

| Deliverable | Files | Tests |
|-------------|-------|-------|
| BacktestConfig | `backtesting/models.py` | `TestBacktestConfig` |
| Input validation | `backtesting/validation.py` | `TestValidation` |
| Execution model | `backtesting/execution.py` | `TestFeeAndSlippage` |
| Metrics | `backtesting/metrics.py` | `TestMetrics` |
| Engine | `backtesting/engine.py` | `TestNextBarExecution`, `TestDeterminism` |
| Experiment tracking | `backtesting/engine.py` | `TestExperimentTracking` |
| Documentation | `docs/architecture/minimal-backtesting-engine.md` | — |
| ADR-007 | `docs/decisions/ADR-007-minimal-backtesting-engine.md` | — |

---

## Pending deliverables

| Deliverable | Phase | Notes |
|-------------|-------|-------|
| Multi-asset portfolio backtesting | 3 | Requires aqcs.portfolio |
| Walk-forward validation | 3 | From backtesting standards §J |
| Slippage as function of order size | 3 | Market impact modelling |
| Short selling support | 3 | Requires Phase Guard advancement |

---

## Acceptance criteria

- [x] Signal at T executes at T+1 open (enforced by shift(1))
- [x] No same-bar execution possible (tested)
- [x] No lookahead leakage (tested via timing invariants)
- [x] Fees always applied (mandatory config field)
- [x] Slippage always applied (mandatory config field)
- [x] Deterministic: same inputs → same outputs (tested)
- [x] Long-only: no short positions (tested)
- [x] No pyramiding: one position at a time (tested)
- [x] 8 required metrics computed
- [x] ExperimentRecord created when tracker provided
- [x] 39 tests passing
- [x] Architecture boundary enforced

---

## Related ADRs

- ADR-007: Minimal backtesting engine before optimisation
- ADR-005: Backtesting standards before engine
- ADR-006: Minimal research core (features/signals consumed by engine)
- ADR-002: Quant Core determinism
