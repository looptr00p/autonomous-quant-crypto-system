# AQCS Canonical Project Context

**Version:** 1.0.0  
**Date:** 2026-05-17  
**Maintained by:** Human Founder  
**Read by:** All AI agents before making changes

---

## Project purpose

AQCS is a modular, reproducible quantitative research laboratory for crypto spot markets. It provides the infrastructure for systematic research — not a trading bot, not an autonomous system, not a black-box ML platform.

Every design decision optimises for:
1. **Reproducibility** — same code + data = same result on any machine
2. **Auditability** — every action leaves a typed, timestamped record
3. **Safety** — no order execution pathway exists in Phase 1
4. **Modularity** — components communicate through typed events and function signatures

---

## Current phase

**Phase 1 — Foundation Layer** (active)

Scope: infrastructure, data acquisition, validation, event schema, configuration, logging, architecture enforcement, governance.

Not in scope for Phase 1: backtesting, ML, live data, paper trading, strategies, live execution, autonomous agents.

---

## Architecture summary

```
┌──────────────────────────────────────────────────────────┐
│                     Quant Core                            │
│  data → features → signals → portfolio → risk → execution│
│  backtesting ← monitoring ← utils                        │
└─────────────────────────┬────────────────────────────────┘
                          │ OversightEvent (read-only)
                          ▼
┌──────────────────────────────────────────────────────────┐
│               LLM Oversight (passive)                     │
│  Observes events. Writes bitácora. Never trades.         │
└──────────────────────────────────────────────────────────┘
```

**Python package root:** `src/aqcs/`  
**Import namespace:** `aqcs.*` (not `src.*`)

---

## Quant Core responsibilities

| Component | Responsibility |
|-----------|---------------|
| `aqcs.data` | Market data acquisition (OHLCV from Binance Spot via ccxt), validation, Parquet persistence |
| `aqcs.features` | Deterministic feature engineering on local data (Phase 2+) |
| `aqcs.signals` | Rules-based signal generation (Phase 2+) |
| `aqcs.portfolio` | Portfolio weight construction (Phase 3+) |
| `aqcs.risk` | Position sizing and risk constraints (Phase 3+) |
| `aqcs.execution` | Order management (read-only in Phase 1; Phase 4 for live) |
| `aqcs.backtesting` | Historical simulation (Phase 2+) |
| `aqcs.monitoring` | Data quality and system health checks |
| `aqcs.utils` | Config, logging, events, phase guard — shared infrastructure |

---

## LLM Oversight responsibilities

`aqcs.llm_oversight` contains `OversightObserver`, which:
- Subscribes to 9 core event categories (DATA, VALIDATION, CONFIG, EXPERIMENT, PHASE_GUARD, SIGNAL, RISK, BACKTESTING, SYSTEM)
- Does NOT subscribe to OVERSIGHT events (prevents feedback loops)
- Logs every observed event via structlog
- May generate `OversightReviewEvent` records
- Never modifies Quant Core state
- Never calls exchange APIs
- Imports only from `aqcs.utils`

---

## Phase 1 constraints (enforced)

The following capabilities are blocked by `src/aqcs/utils/phase_guard.py`:

| Blocked feature | Unblocks in phase |
|-----------------|------------------|
| `futures` | 4+ (requires ADR) |
| `leverage` | 4+ (requires ADR) |
| `live_trading` | 4 |
| `websocket_streaming` | 2 |
| `machine_learning` | 2 (requires ADR) |
| `reinforcement_learning` | Never (requires ADR) |
| `autonomous_agents` | Never (requires ADR) |
| `short_selling` | 3+ |
| `order_execution` | 3 |
| `paper_trading` | 3 |

Attempting to use a blocked feature raises `PhaseConstraintError` immediately.

---

## Implemented layers (Phase 1, complete)

### Package structure
- `src/aqcs/` — Python package root (not `src.*`)
- All imports use `aqcs.*` namespace
- Installed via `pip install -e ".[dev]"`

### Architecture enforcement
- `tests/architecture/test_dependency_boundaries.py` — enforces DAG via AST
- `tests/architecture/test_forbidden_imports.py` — bans ML/RL libs and ccxt outside `aqcs.data`
- `tests/architecture/test_repo_structure.py` — verifies critical files exist
- `tests/architecture/test_no_src_imports.py` — bans legacy `src.*` imports
- CI: `.github/workflows/ci.yml` runs lint, typecheck, and pytest on every push

### Phase Guard
- `src/aqcs/utils/phase_guard.py` — blocks prohibited capabilities
- Fails closed for unknown phases (PhaseConstraintError)
- Wired into `_build_exchange()` in `ohlcv.py`

### Event Schema
- `src/aqcs/utils/events.py` — typed, immutable, UTC-enforced event records
- `src/aqcs/utils/event_bus.py` — synchronous DI EventBus, no global singleton
- `src/aqcs/llm_oversight/observer.py` — OversightObserver with single-bus API
- 20 typed EventName values across 12 EventCategory types

### Data Validation Layer
- `src/aqcs/data/validator.py` — 13-step OHLCV validation before Parquet write
- Blocks: schema, nulls, naive timestamps, non-UTC timestamps, duplicates, non-monotonic, price consistency, metadata mismatch
- Warns: gap detection for known timeframes
- Emits typed events to optional EventBus

### Data acquisition
- `src/aqcs/data/ohlcv.py` — OHLCV downloader (ccxt, Binance Spot, paginated CLI)
- Validation is mandatory before save; invalid data aborts with SystemExit(1)

---

## Next planned layers

| Layer | Objective | Phase |
|-------|-----------|-------|
| Experiment Tracking | OBJ-003 | 1 (next) |
| Feature Engineering | OBJ-004 | 2 |
| Backtesting Engine | OBJ-005 | 2 |
| Signal Generation | OBJ-006 | 2 |

---

## Critical design principle

> **AQCS is event-logged, not distributed event-driven.**

Events are in-memory, synchronous, immutable data records dispatched via `EventBus`. There is no Kafka, no Redis, no Celery, no message broker, no event replay, no async processing, no schema registry, and no distributed delivery.

Event storage in Phase 1 is via structlog JSON logs only. A JSONL writer handler is optional and caller-configured.
