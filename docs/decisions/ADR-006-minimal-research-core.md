# ADR-006: Implement minimal research core before backtesting engine

**Status:** Accepted  
**Date:** 2026-05-17  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-005

---

## Context

AQCS has defined backtesting standards (ADR-005) but has not yet implemented a backtesting engine. Before the engine is built, the system needs:
1. Feature functions that transform raw OHLCV data into derived quantities
2. Signal functions that translate features into directional views

The question requiring a formal decision is: what should these functions look like, and what should they explicitly NOT do?

## Decision

**AQCS implements a minimal research core — pure feature functions and deterministic signal functions — as the first quantitative layer, before any backtesting engine.**

Key constraints that are not negotiable:

1. **Pure functions only.** Feature and signal functions accept pandas Series and return pandas Series. They have no side effects, no file IO, no network calls, no event bus dependency.

2. **No portfolio, risk, or execution logic.** Signal functions output a direction (`LONG`/`SHORT`/`NEUTRAL`). They do not size positions, compute weights, or simulate execution. These responsibilities belong to higher layers implemented in later phases.

3. **Causal by construction.** Every function uses only data from 0 to T to compute output at T. This is enforced structurally (rolling windows, expanding ranks) and verified in tests.

4. **Architecture boundary enforced.** `aqcs.signals` may import from `aqcs.features` and `aqcs.utils`. `aqcs.features` may import from `aqcs.utils` only. No cross-imports with portfolio, risk, execution, or backtesting.

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Build the backtesting engine before features/signals | A backtesting engine needs inputs. Defining the input format (pure feature Series) before the engine ensures the engine is designed around the correct abstraction, not vice versa. |
| Include portfolio weighting in signal functions | Violates the separation of concerns. Signals answer "what direction?" — portfolio construction answers "how much?". Conflating them creates non-reusable signal code. |
| Include event bus dependencies in feature functions | Feature functions must be usable in interactive research (notebooks) without any event infrastructure. Emitting events from feature computation is an unnecessary coupling. |
| Use a class-based "Strategy" abstraction immediately | Premature abstraction. A strategy abstraction makes sense when the backtesting engine exists to execute it. For now, functions are sufficient. |

## Consequences

**Positive:**
- Feature and signal code is reusable: same function works in backtesting, notebooks, and live research
- Lookahead is prevented by construction, not convention
- Clear boundary means feature/signal code can evolve without affecting portfolio/risk/execution
- Tests can be written without any infrastructure (no event bus, no database, no exchange)

**Negative:**
- Cross-sectional signals (rank assets against each other) are deferred — the current API operates on single Series, not DataFrames with multiple assets. Phase 2 will add this.
- No position sizing means the research core output (a signal direction) cannot be directly used for live trading — this is a deliberate Phase 1 constraint.

**Neutral:**
- `SignalDirection` is re-exported from `aqcs.utils.events`, coupling the signals layer to the event schema. This is architecturally acceptable since `aqcs.signals → aqcs.utils` is an allowed dependency.

## Related documents

- `docs/architecture/research-core.md`
- `docs/architecture/backtesting-standards.md` — standards that constrain future use of these functions
- ADR-005: Backtesting standards before engine
- ADR-002: Quant Core determinism
- `tests/architecture/test_dependency_boundaries.py` — enforces boundaries
