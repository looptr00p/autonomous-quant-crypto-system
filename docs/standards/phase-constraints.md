# AQCS Phase Constraints

**Version:** 1.0.0  
**Date:** 2026-05-16  
**Status:** Active  
**Enforcement:** `src/utils/phase_guard.py`

---

## Purpose

This document defines which capabilities are permitted and which are prohibited in each development phase of AQCS. It is the human-readable counterpart to the machine-enforced constraints in `src/utils/phase_guard.py`.

Every prohibited capability has an explicit rationale. The rationale is not bureaucratic friction — it is the recorded justification for why a boundary exists, so that future teams can evaluate whether a proposed exception is sound or expedient.

---

## Phase 1 — Foundation Layer (current)

### Permitted

| Capability | Notes |
|-----------|-------|
| REST API market data (read-only) | Public endpoints only. Credentials optional. |
| OHLCV download (daily, hourly) | Via ccxt, Binance Spot. Paginated, rate-limited. |
| Parquet storage | PyArrow schema, Snappy compression. |
| Deterministic feature engineering | Pure functions on local data. No random state without explicit seed. |
| Rules-based signal generation | Threshold, crossover, and ratio signals. No probabilistic models. |
| Long-only portfolio construction | Weights ≥ 0, sum ≤ 1. No leverage. |
| Vectorised backtesting | Historical simulation on local Parquet files. No live data. |
| Data quality monitoring | Gap detection, schema drift, stale price detection. Advisory only. |
| Structured JSON logging | `structlog`. Read-only event emission. |
| LLM Oversight (observation only) | Reads `OversightEvent` records. Writes to `docs/bitacora/`. No other output. |

### Prohibited

The following capabilities are blocked by `phase_guard.assert_allowed()` and must not be introduced through any other pathway (config flags, environment variables, monkey-patching in production).

---

#### `futures`
**Prohibited in:** Phase 1, 2, 3  
**Rationale:** Futures introduce funding rates, contract rollover, and mark price dynamics that require a dedicated data pipeline, risk model, and margin management system. None of these exist in AQCS V1. Adding futures to a spot-only system without the supporting infrastructure creates silent P&L attribution errors that are difficult to detect.

---

#### `leverage`
**Prohibited in:** Phase 1, 2, 3  
**Rationale:** Leverage amplifies both returns and drawdowns non-linearly. A system without a validated, tested risk engine has no business applying leverage. The order of operations is: validate the strategy unlevered → validate the risk engine → consider leverage. Skipping steps one and two is the most common cause of systematic fund failure.

---

#### `live_trading`
**Prohibited in:** Phase 1, 2, 3  
**Rationale:** Live order submission has irreversible consequences. A bug in a live system costs real capital. The preconditions for live trading — validated signal pipeline, tested risk engine, audited execution layer, real-time monitoring, circuit breakers — none of these exist in Phase 1 or 2. Phase 3 introduces paper trading as the transition step. Live trading requires a separate architecture review and is a Phase 4 decision.

---

#### `websocket_streaming`
**Prohibited in:** Phase 1  
**Rationale:** Real-time streaming introduces asynchronous state management, connection resilience, and data consistency problems that are orthogonal to the research objectives of Phase 1. Phase 1 works exclusively on historical, batch-downloaded data. Streaming adds complexity without adding research value at this stage. It becomes relevant in Phase 2 when real-time feature computation is needed.

---

#### `reinforcement_learning`
**Prohibited in:** Phase 1, 2, 3, 4  
**Rationale:** RL agents learn policies by interacting with an environment. In a trading context, that environment is the market. The practical consequence is that RL agents adapt to market regimes in ways that are difficult to audit, interpret, or attribute causally. The reward signal is noisy, non-stationary, and subject to overfitting. AQCS is a research laboratory, not an RL testbed. If RL is ever considered, it requires its own architectural track, separate validation methodology, and an explicit decision record. It is never enabled by default.

---

#### `machine_learning`
**Prohibited in:** Phase 1  
**Rationale:** ML models require a validated baseline to be evaluated against. That baseline does not exist in Phase 1. Introducing ML before a rigorous rules-based baseline is established makes it impossible to determine whether ML adds value or merely adds complexity. The sequencing is intentional: build the deterministic pipeline → establish a measurable baseline → then, and only then, evaluate whether ML improves on it. Phase 2 permits ML with an ADR.

---

#### `autonomous_agents`
**Prohibited in:** Phase 1, 2, 3, 4  
**Rationale:** An autonomous agent is a system that takes actions in the world without explicit human approval at each step. In a financial context, autonomous action means order submission, parameter modification, or risk override without a human in the loop. AQCS does not permit autonomous agents in any phase. The LLM Oversight layer is explicitly not an agent — it observes and documents, it does not act. Any proposal to introduce an autonomous agent requires a standalone architecture review that is outside the scope of the AQCS roadmap.

---

#### `short_selling`
**Prohibited in:** Phase 1, 2  
**Rationale:** Short positions require borrow availability, borrow cost modelling, margin requirements, and forced-close risk — none of which are modelled in the Phase 1 or 2 infrastructure. A long-only system with a validated performance record is the correct precondition for introducing short exposure.

---

#### `order_execution`
**Prohibited in:** Phase 1  
**Rationale:** No code path that submits an order to an exchange exists in Phase 1. The `src/execution/` module is present for architecture purposes (dry-run logging, order construction). The transition to paper execution is a Phase 3 decision conditioned on Phase 2 validation results.

---

#### `paper_trading`
**Prohibited in:** Phase 1  
**Rationale:** Paper trading requires a real-time data feed, order state management, and fill simulation against live order book data. These components do not exist in Phase 1. Paper trading is introduced in Phase 3 as the controlled transition step between backtesting and live execution.

---

## Phase 2 — Research Layer

Unlocks: `websocket_streaming`, `machine_learning`, `paper_trading` (read-only exploration only).

Remains prohibited: `futures`, `leverage`, `live_trading`, `short_selling`, `order_execution`, `reinforcement_learning`, `autonomous_agents`.

---

## Phase 3 — Signal and Execution Layer

Unlocks: `paper_trading` (full), `order_execution` (sandbox/paper only), `short_selling` (with risk engine validation).

Remains prohibited: `futures`, `leverage`, `live_trading`, `reinforcement_learning`, `autonomous_agents`.

---

## Phase 4 — Live Execution Layer

Unlocks: `live_trading`, `futures` (separate ADR required), `leverage` (separate ADR required).

Permanently prohibited in all phases: `reinforcement_learning`, `autonomous_agents`.

---

## Advancing a constraint

To propose unlocking a capability before its scheduled phase:

1. Open an Architecture Decision Record in `docs/decisions/` using the ADR template.
2. The ADR must answer:
   - What specific research or operational need cannot be met without this capability?
   - What is the minimum viable implementation that satisfies the need without the full capability?
   - What tests, monitors, and circuit breakers will be in place before activation?
   - What is the rollback procedure if the capability produces unexpected results?
3. The ADR must be reviewed and accepted before any implementation begins.
4. The `CURRENT_PHASE` constant in `src/utils/phase_guard.py` is updated only after the ADR is accepted and the preconditions in the ADR are verified.

There is no shortcut to this process. The value of the constraint system is that it requires explicit justification, not that it is convenient.

---

## Enforcement

`src/utils/phase_guard.assert_allowed(Feature.X)` is called at the entry point of any function that implements a gated capability. It raises `PhaseConstraintError` immediately with a message that names the feature, the current phase, and this document.

The enforcement is additive — calling `assert_allowed` is cheap, and the cost of not calling it is a capability that silently activates when `CURRENT_PHASE` advances.

```python
from src.utils.phase_guard import Feature, assert_allowed

def connect_websocket(symbol: str) -> None:
    assert_allowed(Feature.WEBSOCKET_STREAMING)
    # ... implementation
```
