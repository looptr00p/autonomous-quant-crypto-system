# AQCS Architecture — Phase 1: Foundation Layer

> **DEPRECATED** — This document has been superseded by
> [`system-architecture-v1.md`](system-architecture-v1.md) and
> [`event-schema.md`](event-schema.md), which are the canonical references.
> This file is retained for historical context only. Do not use it as a source of truth.
>
> Known conflicts with current implementation:
> - §8 dependency rule for `src/portfolio/` conflicts with `system-architecture-v1.md §5`.
> - §5 event schema (DataEvent, OversightEvent, quant_component field) is replaced by
>   the schema in `event-schema.md` and `src/aqcs/utils/events.py`.
> - All references to `src.*` namespaces are replaced by `aqcs.*`.
> - The canonical source takes precedence unconditionally.

**Version:** 0.1.0  
**Date:** 2026-05-16  
**Status:** Deprecated

---

## 1. Goals

The Foundation Layer establishes the infrastructure on which all future quantitative research will run. Every design decision optimises for:

1. **Reproducibility** — the same code + data must produce the same result on any machine.
2. **Observability** — everything that happens is logged as a structured JSON event.
3. **Safety** — no order execution pathway exists in this phase.
4. **Modularity** — components talk through typed events and function signatures, not shared mutable state.

---

## 2. High-level component map

```
┌─────────────────────────────────────────────────────────────────┐
│                          AQCS System                            │
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐  │
│  │   Data   │──▶│ Features │──▶│ Signals  │──▶│ Portfolio │  │
│  └──────────┘   └──────────┘   └──────────┘   └───────────┘  │
│       │                                              │         │
│       ▼                                              ▼         │
│  ┌──────────┐                               ┌───────────────┐ │
│  │  Storage │                               │  Risk Manager │ │
│  │ (Parquet)│                               └───────────────┘ │
│  └──────────┘                                      │          │
│                                                     ▼          │
│                                            ┌─────────────┐    │
│                                            │  Execution  │    │
│                                            │ (read-only) │    │
│                                            └─────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │            LLM Oversight (observer only)                 │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component responsibilities

### 3.1 Data (`src/data/`)

Responsible for acquiring, validating, and persisting market data.

- **ohlcv.py** — Downloads OHLCV candlesticks from Binance Spot via ccxt. Paginates automatically. Saves to Parquet with a fixed schema.
- All writes are append-safe; no data is overwritten without explicit intent.
- No transformation logic lives here — raw data goes to `data/raw/`.

### 3.2 Features (`src/features/`)

Deterministic transformations applied to raw OHLCV frames.

- All feature functions are pure: `(DataFrame, params) → DataFrame`.
- No random state. Seeded operations must receive the seed explicitly.
- Output goes to `data/processed/`.

### 3.3 Signals (`src/signals/`)

Rules-based and statistical signal generators.

- A signal is a scalar or series in `{-1, 0, +1}` or a probability.
- No signal generator calls an LLM or a neural network in Phase 1.
- Signals are deterministic given the same input data.

### 3.4 Portfolio (`src/portfolio/`)

Combines signals into target weights.

- Receives signal vectors and risk constraints.
- Outputs a weight vector that sums to ≤1 (long-only in Phase 1).

### 3.5 Risk (`src/risk/`)

Position sizing, drawdown limits, concentration limits.

- All limits are defined in `configs/base.yaml`.
- No dynamic limit modification at runtime.

### 3.6 Execution (`src/execution/`)

Phase 1: read-only. Contains order-builder helpers and ccxt wrappers.

- **No live order submission in Phase 1.**
- Dry-run mode logs what would be submitted.

### 3.7 Backtesting (`src/backtesting/`)

Historical simulation engine.

- Vectorised by default; event-driven mode in Phase 2.
- No look-ahead bias: data is sliced at each bar boundary.

### 3.8 Monitoring (`src/monitoring/`)

Data quality checks, system health probes.

- Runs as a separate process or inline.
- Emits `SystemEvent` records to the structured log.

### 3.9 Utils (`src/utils/`)

Cross-cutting concerns:

| Module | Purpose |
|--------|---------|
| `config.py` | YAML + env var config loading |
| `logging.py` | structlog JSON logging setup |
| `events.py` | Typed Pydantic event schema |

### 3.10 LLM Oversight (`src/llm_oversight/`)

Read-only observation and documentation layer.

- Receives `OversightEvent` objects.
- Writes human-readable narrative logs to `docs/bitacora/`.
- **Never modifies system state.**
- **Never issues orders.**
- **Never calls external APIs.**

---

## 4. Data flow

```
Binance API (ccxt)
      │
      ▼
 fetch_ohlcv()
      │
      ▼
 pd.DataFrame (typed)
      │
      ▼
 save_parquet()
      │
      ▼
 data/raw/<symbol>_<timeframe>.parquet
      │
      ▼
 feature_pipeline()   [Phase 2]
      │
      ▼
 data/processed/      [Phase 2]
```

---

## 5. Event schema

All inter-component communication is expressed as immutable Pydantic events (see `src/utils/events.py`).

```
BaseEvent
├── event_id      UUID   — unique per event
├── timestamp     datetime (UTC)
├── category      Enum   — DATA | FEATURE | SIGNAL | PORTFOLIO | RISK | SYSTEM | OVERSIGHT
├── severity      Enum   — info | warning | error | critical
├── source        str    — emitting module
├── message       str    — human-readable summary
└── payload       dict   — structured data

DataEvent (extends BaseEvent)
├── symbol        str
├── timeframe     str
└── candles_fetched int

OversightEvent (extends BaseEvent)
└── quant_component str  — which quant module is being observed
```

---

## 6. Storage layout

```
data/
├── raw/
│   └── <SYMBOL>_<TIMEFRAME>.parquet     — verbatim from exchange
├── processed/
│   └── <SYMBOL>_<TIMEFRAME>_<features>.parquet
└── external/
    └── <source>_<dataset>.parquet       — macro, on-chain, etc.
```

All Parquet files use Snappy compression and are written with PyArrow using a declared schema. This ensures type safety across writer versions.

---

## 7. Configuration hierarchy

```
configs/base.yaml          — project-wide defaults
configs/<env>.yaml         — environment override (development, staging, production)
.env                       — secrets (never committed)
```

Loaded at startup by `src/utils/config.load_config()`. Accessed via `Settings` (Pydantic-Settings) for typed env var access.

---

## 8. Dependency rules

- `src/data` may import from `src/utils` only.
- `src/features` may import from `src/data` and `src/utils`.
- `src/signals` may import from `src/features` and `src/utils`.
- `src/portfolio` may import from `src/signals`, `src/risk`, and `src/utils`.
- `src/llm_oversight` may import from `src/utils` only.
- No circular imports.

---

## 9. Non-goals (Phase 1)

- Live order execution
- ML model training or inference
- Real-time streaming
- Multi-exchange routing
- Autonomous agent decision-making
- Dashboard or UI
