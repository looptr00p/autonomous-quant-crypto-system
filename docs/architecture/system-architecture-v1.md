# AQCS System Architecture — Version 1

**Version:** 1.0.0  
**Date:** 2026-05-16  
**Status:** Active  
**Phase coverage:** Phase 1 (Foundation) and Phase 2 (Research)

---

## Table of contents

1. [Guiding principles](#1-guiding-principles)
2. [System overview](#2-system-overview)
3. [Data flow](#3-data-flow)
4. [Component specifications](#4-component-specifications)
   - 4.1 [Data Layer](#41-data-layer)
   - 4.2 [Feature Layer](#42-feature-layer)
   - 4.3 [Signal Engine](#43-signal-engine)
   - 4.4 [Portfolio Engine](#44-portfolio-engine)
   - 4.5 [Risk Engine](#45-risk-engine)
   - 4.6 [Execution Engine](#46-execution-engine)
   - 4.7 [Backtesting Engine](#47-backtesting-engine)
   - 4.8 [Monitoring](#48-monitoring)
   - 4.9 [LLM Oversight](#49-llm-oversight)
5. [Dependency rules](#5-dependency-rules)
6. [Critical constraint: LLM boundary](#6-critical-constraint-llm-boundary)
7. [Failure modes and mitigations](#7-failure-modes-and-mitigations)
8. [Version history](#8-version-history)

---

## 1. Guiding principles

Every architectural decision in V1 is evaluated against the following priorities, in order:

1. **Correctness** — Results must be verifiable and reproducible. A system that produces wrong results reliably is more dangerous than one that fails loudly.
2. **Auditability** — Any result produced by the system must be traceable to its inputs. Every transformation is logged; every parameter is versioned.
3. **Simplicity** — The simplest design that satisfies the requirement is preferred. Complexity requires justification; simplicity does not.
4. **Modularity** — Components are replaceable. Each component has a defined interface contract. Changing the internals of one component must not require changes to others.
5. **Safety** — No execution pathway to a live exchange exists in V1. This is an architectural constraint, not a configuration flag.

---

## 2. System overview

```
╔══════════════════════════════════════════════════════════════════════════╗
║                           AQCS V1 — Quant Core                          ║
║                                                                          ║
║  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 ║
║  │  Data Layer │───▶│Feature Layer│───▶│Signal Engine│                 ║
║  └─────────────┘    └─────────────┘    └─────────────┘                 ║
║         │                                      │                        ║
║    (Parquet)                                    ▼                        ║
║         │                           ┌──────────────────┐               ║
║         │                           │ Portfolio Engine  │               ║
║         │                           └──────────────────┘               ║
║         │                                      │                        ║
║         │                                      ▼                        ║
║         │                           ┌──────────────────┐               ║
║         │                           │   Risk Engine     │               ║
║         │                           └──────────────────┘               ║
║         │                                      │                        ║
║         │                                      ▼                        ║
║         │                           ┌──────────────────┐               ║
║         │                           │ Execution Engine  │               ║
║         │                           │  (dry-run only)   │               ║
║         │                           └──────────────────┘               ║
║         │                                      │                        ║
║         ▼                                      ▼                        ║
║  ┌─────────────┐              ┌────────────────────────┐               ║
║  │  Monitoring │              │   Backtesting Engine   │               ║
║  └─────────────┘              └────────────────────────┘               ║
║         │                                      │                        ║
╚═════════╪══════════════════════════════════════╪════════════════════════╝
          │               Event stream           │
          └──────────────────┬───────────────────┘
                             ▼
          ╔════════════════════════════════════╗
          ║        LLM Oversight Layer         ║
          ║   (read-only — no state changes)   ║
          ╚════════════════════════════════════╝
```

The Quant Core and the LLM Oversight layer are separated by a one-directional event bus. Events flow from the Core to Oversight. Nothing flows in the opposite direction.

---

## 3. Data flow

The following sequence describes the canonical path from raw market data to logged output. Each arrow represents a transformation with a defined schema contract.

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. Raw Market Data                                                   │
│    Source: Binance Spot REST API (ccxt)                              │
│    Format: JSON (exchange-native)                                    │
│    Location: in-memory only                                          │
└──────────────────────────────┬───────────────────────────────────────┘
                               │  schema validation + deduplication
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. Validated Data                                                    │
│    Format: Parquet (PyArrow schema, Snappy compression)              │
│    Location: data/raw/<SYMBOL>_<TIMEFRAME>.parquet                   │
│    Invariant: UTC timestamps, no nulls in OHLCV columns,             │
│               no duplicate timestamps                                │
└──────────────────────────────┬───────────────────────────────────────┘
                               │  deterministic feature functions
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. Features                                                          │
│    Format: Parquet, extended schema (raw columns + feature columns)  │
│    Location: data/processed/<SYMBOL>_<TIMEFRAME>_<feature_set>.parquet│
│    Invariant: same row count as input, no look-ahead,                │
│               NaN rows at head are permitted and documented          │
└──────────────────────────────┬───────────────────────────────────────┘
│                              │  signal functions (rules-based)
│                              ▼
│  ┌──────────────────────────────────────────────────────────────┐
│  │ 4. Signals                                                   │
│  │    Format: DataFrame — index=timestamp, columns=symbols      │
│  │    Values: float in [−1.0, +1.0] or {−1, 0, +1}            │
│  │    Invariant: no forward-looking data                        │
│  └──────────────────────────────┬─────────────────────────────-┘
│                                 │  weight optimisation / rules
│                                 ▼
│  ┌──────────────────────────────────────────────────────────────┐
│  │ 5. Portfolio Targets                                         │
│  │    Format: dict[str, float] — symbol → target weight        │
│  │    Invariant: weights sum ≤ 1.0, all weights ≥ 0 (Phase 1)  │
│  └──────────────────────────────┬─────────────────────────────-┘
│                                 │  constraint checking
│                                 ▼
│  ┌──────────────────────────────────────────────────────────────┐
│  │ 6. Risk-Checked Targets                                      │
│  │    Format: same as Portfolio Targets                         │
│  │    May be reduced or zeroed by risk engine                   │
│  │    Every modification is logged with reason                  │
│  └──────────────────────────────┬─────────────────────────────-┘
│                                 │  order construction (dry-run)
│                                 ▼
│  ┌──────────────────────────────────────────────────────────────┐
│  │ 7. Simulated Execution                                       │
│  │    Format: list[SimulatedOrder]                              │
│  │    Logged as structured events, never submitted to exchange  │
│  └──────────────────────────────┬─────────────────────────────-┘
│                                 │
└───────────────┬─────────────────┘
                │  all components emit events throughout
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 8. Logs / Events                                                     │
│    Format: JSON (structlog), one record per line                     │
│    Location: logs/<date>.jsonl                                       │
│    Schema: BaseEvent subclasses (src/utils/events.py)                │
└──────────────────────────────┬───────────────────────────────────────┘
                               │  OversightEvent subset only
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 9. LLM Oversight                                                     │
│    Reads: OversightEvent records                                     │
│    Writes: docs/bitacora/<date>-<slug>.md                            │
│    Invariant: no write access to data/, src/, configs/, or exchange  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Component specifications

---

### 4.1 Data Layer

**Location:** `src/data/`

#### Responsibility

Acquire raw market data from external sources, validate it against declared schemas, eliminate duplicates, and persist it to disk in a format that is stable and queryable. The Data Layer is the only component in the system that communicates with external APIs.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Exchange credentials | `.env` via `Settings` | API key + secret strings |
| Download parameters | CLI arguments or config | symbol, timeframe, date range |
| Exchange connection | ccxt library | `ccxt.Exchange` instance |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| OHLCV candles | `data/raw/<SYMBOL>_<TIMEFRAME>.parquet` | Parquet, declared PyArrow schema |
| `DataEvent` records | Structured log + event bus | JSON |

**Output schema (OHLCV):**

```
timestamp   : timestamp[ms, UTC]   — candle open time
open        : float64
high        : float64
low         : float64
close       : float64
volume      : float64
symbol      : string               — e.g. "BTC/USDT"
timeframe   : string               — e.g. "1d"
exchange    : string               — e.g. "binance"
```

#### What this component must NOT do

- Transform, normalise, or resample data. Raw means raw.
- Apply business logic to decide which symbols to download.
- Call any module other than `src/utils/`.
- Overwrite existing Parquet files without an explicit `--overwrite` flag.
- Cache exchange connections across process boundaries.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Exchange rate limit exceeded | Medium | ccxt `enableRateLimit=True`; configurable pagination sleep |
| Partial download leaves corrupted file | Medium | Write to a `.tmp` file, rename on success |
| Exchange API returns non-UTC timestamps | Low | Explicit UTC coercion before schema validation |
| Symbol delisted mid-download | Low | Catch `ccxt.BadSymbol`; log and continue with remaining symbols |
| Silent gap in historical data | Medium | Gap detection in Monitoring (§4.8); Data Layer logs candle count per page |

---

### 4.2 Feature Layer

**Location:** `src/features/`

#### Responsibility

Apply deterministic, stateless transformations to validated OHLCV data to produce derived quantities used downstream by the Signal Engine. Every function in this layer is a pure function: same inputs always produce same outputs with no side effects.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Validated OHLCV data | `data/raw/*.parquet` | Parquet |
| Feature parameters | `configs/base.yaml` | lookback windows, normalisation bounds |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Feature DataFrame | `data/processed/<SYMBOL>_<TIMEFRAME>_<feature_set>.parquet` | Parquet |

**Conventions for feature columns:**
- Naming: `<feature_name>_<parameter>` — e.g., `sma_20`, `rsi_14`, `vol_30d`
- NaN at the head of the series (warm-up period) is permitted and documented
- No column may depend on data after its timestamp (no look-ahead)

#### What this component must NOT do

- Fetch data from external sources.
- Modify files in `data/raw/`.
- Introduce randomness without an explicit seed parameter.
- Use global mutable state.
- Call signal, portfolio, or risk modules.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Look-ahead bias introduced by pandas shift errors | Medium | Explicit tests using synthetic data with known correct outputs |
| NaN propagation corrupts downstream signals | High | Assert no NaN in output beyond the documented warm-up period |
| Feature parameters silently changed between runs | Low | Parameters are logged as part of the feature pipeline run event |
| Floating-point non-determinism across platforms | Low | Document platform (Python version, NumPy version) in experiment records |

---

### 4.3 Signal Engine

**Location:** `src/signals/`

#### Responsibility

Translate feature vectors into directional signals for each instrument in the universe. A signal represents a view on an instrument at a given time: positive (long bias), negative (short bias in future phases), or neutral. The Signal Engine has no knowledge of portfolio weights or risk limits.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Feature DataFrame | `data/processed/*.parquet` | Parquet |
| Signal parameters | `configs/base.yaml` | thresholds, lookback windows, signal type |
| Asset universe | `configs/base.yaml` | list of symbols |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Signal DataFrame | In-memory; optionally serialised to `data/processed/` | `pd.DataFrame` — index=timestamp, columns=symbols, values in [−1, +1] |
| `SignalEvent` records | Structured log | JSON |

#### What this component must NOT do

- Call any external API.
- Access portfolio weights or risk state.
- Issue orders or set position sizes.
- Use ML models or probabilistic inference in Phase 1.
- Produce signals based on future data (any form of look-ahead).

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Signal computed on insufficiently warm feature series | High | Assert feature warmup period is complete before signal computation |
| Threshold values tuned on the full sample (in-sample overfitting) | High | Enforce train/test splits in backtesting; never tune on test data |
| Signal magnitude overflow | Low | Clip output to [−1, +1] with explicit log when clipping occurs |
| Universe mismatch between features and signals | Medium | Validate that feature columns match configured symbol universe at startup |

---

### 4.4 Portfolio Engine

**Location:** `src/portfolio/`

#### Responsibility

Combine signals from multiple instruments into a coherent set of target portfolio weights, subject to structural constraints. The Portfolio Engine transforms views (signals) into positions (weights). It does not enforce risk limits — that is the Risk Engine's responsibility.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Signal DataFrame | Signal Engine | `pd.DataFrame` |
| Portfolio parameters | `configs/base.yaml` | weighting scheme, universe, rebalancing frequency |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Target weights | In-memory | `dict[str, float]` — symbol → weight in [0, 1] |
| `PortfolioEvent` records | Structured log | JSON |

**Structural constraints enforced by Portfolio Engine (not Risk Engine):**

- Phase 1: long-only. All weights ≥ 0.
- Phase 1: fully invested or underinvested. Sum of weights ≤ 1.0.
- Cash weight is implicit: `cash = 1.0 − sum(weights)`.

#### What this component must NOT do

- Fetch market data.
- Apply position-level risk limits (that is Risk Engine's role).
- Short instruments in Phase 1.
- Use leverage in Phase 1.
- Access execution state or order history.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Weight normalisation error causes sum > 1.0 | Low | Assert `sum(weights) <= 1.0 + epsilon` before returning |
| Rebalancing logic uses stale prices | Medium | Weights are computed on the close price of the most recent complete bar; never on intrabar data |
| Degenerate signal (all zeros) produces undefined weights | Medium | Define explicit fallback: zero signals → 100% cash |
| Concentration in a single asset | Medium | Handled by Risk Engine; Portfolio Engine logs the raw (unconstrained) weights |

---

### 4.5 Risk Engine

**Location:** `src/risk/`

#### Responsibility

Apply risk constraints to portfolio targets and return modified (potentially reduced) target weights. The Risk Engine is the last gate before execution. Every modification it makes is logged with an explicit reason. It does not construct portfolios — it constrains them.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Target weights (unconstrained) | Portfolio Engine | `dict[str, float]` |
| Risk parameters | `configs/base.yaml` | position limits, drawdown stops, concentration limits |
| Current portfolio state (Phase 3+) | Portfolio state store | Not applicable in Phase 1 |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Risk-checked weights | In-memory | `dict[str, float]` |
| `RiskEvent` records | Structured log | JSON — includes original weight, adjusted weight, reason |

**Risk constraints in Phase 1:**

| Constraint | Default value | Config key |
|-----------|--------------|------------|
| Maximum single-asset weight | 30% | `risk.max_position_weight` |
| Maximum portfolio gross exposure | 100% | `risk.max_gross_exposure` |
| Cash floor | 0% | `risk.min_cash_weight` |

#### What this component must NOT do

- Construct portfolios or combine signals.
- Fetch market data.
- Override a risk constraint based on signal strength (signals do not bypass risk).
- Silently pass through unconstrained weights when a constraint is violated — it must log every modification.
- Be bypassed. No code path in the system reaches the Execution Engine without passing through Risk Engine.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Constraint parameters incorrectly loaded | Low | Validation at startup; tests for boundary values |
| Risk modification not logged | Low | Structured log emission is part of the constraint function, not an afterthought |
| Constraint too tight, producing all-cash portfolio permanently | Low | Log a warning when portfolio is >90% cash for more than N consecutive bars |
| Risk Engine bypassed in test code | Medium | Integration tests that trace the full pipeline must pass through Risk Engine |

---

### 4.6 Execution Engine

**Location:** `src/execution/`

#### Responsibility

In Phase 1: translate risk-checked target weights into hypothetical orders, log them as dry-run events, and return a simulated fill record. No order is submitted to an exchange. The Execution Engine's Phase 1 purpose is to exercise the order construction logic in a testable way and to produce the execution cost model used by the Backtesting Engine.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Risk-checked target weights | Risk Engine | `dict[str, float]` |
| Current (simulated) holdings | Backtesting state or dry-run state | `dict[str, float]` |
| Execution parameters | `configs/base.yaml` | slippage model, fee rate, order type |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Simulated order log | Structured log | JSON — symbol, side, notional, fee, slippage, timestamp |
| `ExecutionEvent` records | Event bus | Dry-run only |

**Phase 1 execution modes:**

| Mode | Behaviour |
|------|-----------|
| `dry_run` (default) | Orders are constructed and logged; never submitted |
| `paper` (Phase 3) | Orders submitted to exchange sandbox; real API round-trip, no real funds |
| `live` (Phase 4) | Requires explicit architecture approval |

#### What this component must NOT do

- Submit orders to a live exchange in Phase 1. This is an absolute constraint.
- Call `exchange.create_order()`, `exchange.place_order()`, or any equivalent method in Phase 1.
- Receive signals directly. It operates on risk-checked weights only.
- Modify portfolio weights.
- Be called outside of a backtesting context or an explicit dry-run pipeline invocation.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `live` execution path accidentally activated | Low | Config flag `features.order_execution: false` checked at startup; code path does not exist in Phase 1 |
| Slippage model underestimates cost in backtests | Medium | Document model assumptions explicitly; allow overriding via config |
| Fee model becomes stale (exchange changes fees) | Low | Fee rate is configuration-driven, not hardcoded |
| Order construction produces invalid order (negative size) | Low | Assert all order quantities > 0 before logging |

---

### 4.7 Backtesting Engine

**Location:** `src/backtesting/`

#### Responsibility

Simulate the execution of a strategy over a historical period and compute performance metrics. The Backtesting Engine is the primary research tool. It orchestrates the pipeline (Features → Signals → Portfolio → Risk → Execution) across a sequence of historical bars and accumulates a simulated equity curve, trade log, and performance report.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| Historical OHLCV data | `data/raw/*.parquet` | Parquet |
| Strategy configuration | `configs/base.yaml` or experiment config | YAML |
| Start/end dates | CLI or experiment config | ISO 8601 strings |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Equity curve | `experiments/<slug>/equity_curve.parquet` | Parquet |
| Trade log | `experiments/<slug>/trades.parquet` | Parquet |
| Performance report | `experiments/<slug>/metrics.json` | JSON |
| `BacktestEvent` records | Structured log | JSON |

**Mandatory anti-look-ahead checks:**

1. At each bar `t`, only data with `timestamp ≤ t` is visible to the pipeline.
2. Execution is simulated at the `open` price of bar `t+1` (decision on close of `t`, execution on open of `t+1`).
3. The feature computation is windowed: only the trailing window ending at `t` is used.
4. No global state carries information forward beyond what the strategy explicitly tracks.

#### What this component must NOT do

- Use future data in any transformation, even indirectly.
- Use the same data for parameter selection and performance evaluation.
- Produce performance metrics without logging the full configuration used to generate them.
- Submit orders or connect to live exchange APIs.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Look-ahead bias through pandas `.shift()` errors | High | Dedicated test suite with synthetic data where correct output is analytically known |
| Survivorship bias from universe selection | High | Universe is defined at the start of the backtest period; additions after that date are excluded |
| Transaction cost model too optimistic | High | Default to conservative estimates; document assumptions |
| Overfitting via repeated parameter tuning on the same test set | High | Enforce a held-out test set; parameter search only on validation set |
| Memory overflow on large universes or long histories | Medium | Process in rolling windows; document memory estimates per symbol-year |

---

### 4.8 Monitoring

**Location:** `src/monitoring/`

#### Responsibility

Detect data quality problems, system health degradation, and pipeline anomalies. The Monitoring component does not fix problems — it detects them, logs them as structured events, and surfaces them for human review. In later phases it will gate pipeline execution when critical data quality checks fail.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| OHLCV Parquet files | `data/raw/` | Parquet |
| Feature Parquet files | `data/processed/` | Parquet |
| Structured logs | `logs/` | JSONL |
| Monitoring parameters | `configs/base.yaml` | gap thresholds, outlier bounds |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Data quality report | `logs/data_quality_<date>.json` | JSON |
| `MonitoringEvent` records | Structured log + event bus | JSON |

**Checks implemented in Phase 1:**

| Check | Condition |
|-------|-----------|
| Gap detection | Missing bars relative to expected frequency |
| Stale price detection | Zero or repeated close prices across consecutive bars |
| Volume anomaly | Volume = 0 on a bar |
| Schema drift | Parquet file columns or types differ from declared schema |
| OHLCV consistency | High < Low, or Close outside [Low, High] |

#### What this component must NOT do

- Modify data files. Monitoring is read-only with respect to `data/`.
- Block pipeline execution in Phase 1 (advisory only; gating is a Phase 2 feature).
- Attempt to correct data quality issues autonomously.
- Call external APIs.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| False positive gap detection on exchange holidays | Medium | Configure symbol-specific expected frequency; flag rather than error |
| Monitoring itself fails silently | Low | Monitoring errors are logged to a separate channel; they do not suppress the underlying event |
| Data quality report not read by anyone | High | LLM Oversight surfaces critical monitoring events in bitácora entries |

---

### 4.9 LLM Oversight

**Location:** `src/llm_oversight/`

#### Responsibility

Observe the system's activity through the event stream, produce human-readable narrative summaries, and maintain the project bitácora. The LLM Oversight layer is a passive consumer. It has no ability to modify system state, and no pathway to influence any Quant Core component.

#### Inputs

| Input | Source | Format |
|-------|--------|--------|
| `OversightEvent` records | Event bus (read-only) | Pydantic models |
| Structured logs (optional) | `logs/*.jsonl` | JSONL |

#### Outputs

| Output | Location | Format |
|--------|----------|--------|
| Narrative session summaries | `docs/bitacora/YYYY-MM-DD-<slug>.md` | Markdown |
| Anomaly flags (human-readable) | `docs/bitacora/` | Markdown |

#### What this component must NOT do

- **Generate trading signals.** The LLM has no path to `src/signals/`.
- **Modify portfolio weights or risk parameters.** Read-only access to `src/utils/` only.
- **Call exchange APIs.** No ccxt or HTTP client import in this module.
- **Write to `data/`, `configs/`, or `src/` directories.**
- **Execute code in the Quant Core.** It may read event records; it may not call functions.
- **Act autonomously.** Every LLM Oversight action occurs in response to a human-initiated session or a structured event. It does not run on a schedule without explicit invocation.

#### Technical risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| LLM hallucination in audit trail | Medium | All LLM-generated narratives are clearly labelled as such; they do not replace structured logs |
| Oversight module accidentally imports Quant Core modules | Low | Import boundary enforced by `ruff` linting rule; CI check on `src/llm_oversight` imports |
| User misinterprets oversight narrative as authoritative signal | Medium | All bitácora entries include a header: "This document is an observation record, not a trading signal" |
| LLM context window truncates long log sequences | Medium | Events are summarised in batches; raw logs are always authoritative over narrative summaries |

---

## 5. Dependency rules

The following import relationships are permitted. Any other import between components is a violation.

```
src/data/           → src/utils/
src/features/       → src/data/, src/utils/
src/signals/        → src/features/, src/utils/
src/portfolio/      → src/signals/, src/utils/
src/risk/           → src/portfolio/, src/utils/
src/execution/      → src/risk/, src/utils/
src/backtesting/    → src/data/, src/features/, src/signals/,
                      src/portfolio/, src/risk/, src/execution/, src/utils/
src/monitoring/     → src/data/, src/utils/
src/llm_oversight/  → src/utils/ only
```

**No circular imports.** If a circular dependency appears, the design is wrong. Refactor before merging.

**`src/utils/` has no imports from other `src/` packages.** It is the leaf of the dependency tree.

---

## 6. Critical constraint: LLM boundary

This section is normative. It defines the boundary between the Quant Core and the LLM Oversight layer in unambiguous terms.

### What the LLM layer observes

The LLM Oversight layer receives `OversightEvent` records. These are structured, immutable records that describe what happened in the Quant Core — not instructions for what should happen. The following events are routed to the oversight layer:

- Pipeline run start and completion
- Data download summary (symbols, candle counts, any gaps detected)
- Signal generation summary (signal values per symbol)
- Portfolio target summary (proposed weights)
- Risk Engine interventions (what was constrained and why)
- Execution dry-run log (what orders would have been placed)
- Monitoring alerts (data quality issues)
- Backtest completion summary (metrics at a high level)

### What the LLM layer does not receive

- Live price feeds
- Order book data
- API credentials
- Writable references to any system component

### What the LLM layer produces

The only permissible output of the LLM Oversight layer is human-readable Markdown written to `docs/bitacora/`. These documents are:

- **Observations**, not instructions.
- **Narrative summaries**, not structured data consumed by other components.
- **Labelled as LLM-generated** so they are not confused with authoritative system output.

### Enforcement

The boundary is not enforced solely by convention. It is enforced by:

1. **Import restriction** — `src/llm_oversight/` imports only from `src/utils/`. Imports from any other `src/` package will fail the `ruff` CI check.
2. **No exchange client** — `ccxt` is not imported anywhere in `src/llm_oversight/`.
3. **No write access to data/** — The observer function signature accepts events and returns `None`.
4. **Code review** — Any pull request that adds a call from `src/llm_oversight/` to a Quant Core function is rejected.

---

## 7. Failure modes and mitigations

| Failure | Affected components | Behaviour | Recovery |
|---------|-------------------|-----------|----------|
| Exchange API unavailable | Data Layer | Exception caught; `DataEvent` with severity=error logged; pipeline aborts | Retry with exponential backoff (configurable); alert human |
| Corrupted Parquet file | Feature Layer, Backtesting | PyArrow raises schema error on read | Quarantine file, re-download |
| All signals zero for N consecutive bars | Signal Engine, Portfolio Engine | All-cash portfolio; logged as warning | No action required; expected during low-signal periods |
| Risk Engine rejects all positions | Risk Engine | All-cash portfolio; logged as warning with reason | Review risk parameters if sustained |
| NaN propagation through feature pipeline | Backtesting | Assertion fails on equity curve computation | Fix feature warm-up handling; re-run backtest |
| Log directory full | All components | Log write fails; structlog emits to stderr | Rotate logs; increase retention limit |
| LLM Oversight generates incorrect narrative | LLM Oversight | Narrative written to bitácora; no system state affected | Human corrects or discards the bitácora entry |

---

## 8. Version history

| Version | Date | Summary |
|---------|------|---------|
| 1.0.0 | 2026-05-16 | Initial architecture document. Phase 1 (Foundation) and Phase 2 (Research) scope. Nine components specified. LLM boundary formalised. |

*Next revision (V2) will cover Phase 3: paper trading, streaming data feed, and live portfolio state management.*
