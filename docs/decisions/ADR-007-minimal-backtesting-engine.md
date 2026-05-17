# ADR-007: Minimal deterministic backtesting engine before optimisation

**Status:** Accepted  
**Date:** 2026-05-17  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-006

---

## Context

AQCS has defined backtesting standards (ADR-005) and implemented a research core of feature and signal functions (ADR-006). The next step is a simulation engine that validates strategies against historical data.

The question requiring a formal decision is: what should the first backtesting engine implementation look like, and what must it explicitly NOT do?

## Decision

**AQCS implements a minimal, deterministic backtesting engine that prioritises correctness over features.**

The engine is constrained to: daily bars, long-only, single asset, next-bar execution at open, fixed position sizing, mandatory fees and slippage, no leverage, no shorting, no intrabar simulation.

These are not temporary limitations to be removed "when there's time." They are the correct starting point for institutional research:

1. **Next-bar execution is mandatory.** Signal at bar T → execution at bar T+1 open. This is enforced by `signals.shift(1)` before the simulation loop. No exception, no configuration flag to bypass it.

2. **Fees and slippage are mandatory.** `fee_bps` and `slippage_bps` are required fields in `BacktestConfig`. They can be set to zero explicitly (for testing) but there is no implicit zero-cost default.

3. **No optimisation.** The engine runs exactly one set of parameters. Hyperparameter search, walk-forward, or Monte Carlo are Phase 3+ decisions documented in the backtesting standards (§J).

4. **Experiment tracking is integrated.** Every backtest that provides an `ExperimentTracker` creates a reproducibility record. This is not optional for production research.

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Allow same-bar execution as a config option | Any configuration that allows lookahead is a bug waiting to happen. There is no valid research use case for same-bar fills at daily resolution. |
| Optional fees/slippage | "Optional" means researchers will disable them to make results look better. Mandatory defaults prevent this. |
| Build a flexible event-driven engine immediately | Event-driven simulation is significantly more complex and harder to audit. The vectorised approach is sufficient for Phase 1 daily research. |
| Include multi-asset portfolio from the start | Requires portfolio construction (`aqcs.portfolio`) which is a separate layer with its own ADR. Sequential development reduces coupling. |
| Include intrabar simulation | Would require tick data (not available in Phase 1) and microstructure models. Scope creep that adds complexity without improving Phase 1 research quality. |

## Consequences

**Positive:**
- Every backtest is reproducible by construction (deterministic shift + explicit config)
- Lookahead bias is architecturally impossible (not just documented policy)
- Fees and slippage are always present in results (no "best case" by accident)
- The engine is small enough to be fully understood and audited
- Tests verify all critical invariants (timing, determinism, no pyramiding)

**Negative:**
- Cannot backtest short strategies in Phase 1
- Cannot backtest cross-sectional portfolios until `aqcs.portfolio` is implemented
- Slippage model is linear (no market impact) — overly optimistic for large orders
- No intrabar stop-loss simulation

**Neutral:**
- The engine's modular design (execution.py as pure functions, metrics.py separate) allows Phase 2 extensions without redesigning the core loop

## Related documents

- `docs/architecture/minimal-backtesting-engine.md`
- `docs/architecture/backtesting-standards.md` — the policy this engine implements
- ADR-005: Backtesting standards before engine
- ADR-006: Minimal research core (features and signals consumed by the engine)
- `src/aqcs/backtesting/` — implementation
