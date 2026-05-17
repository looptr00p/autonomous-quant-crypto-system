# AQCS — Autonomous Quant Crypto System

A modular, reproducible quantitative research laboratory for crypto spot markets.

---

## Purpose

AQCS is an infrastructure project. Its objective is to provide a rigorous, well-tested foundation on which systematic quantitative research on crypto spot markets can be conducted. Every design decision prioritises correctness and reproducibility over speed of delivery or sophistication of output.

The system is built around a strict separation of concerns: deterministic quantitative logic on one side, observational tooling on the other. These two layers never cross.

---

## What this project is not

This list is not a disclaimer. It is a constraint that shapes every architectural decision.

- **Not a trading bot.** No component issues orders in Phase 1. No order submission pathway exists.
- **Not an autonomous agent.** No component makes discretionary decisions without explicit human review.
- **Not a black-box system.** Every transformation, signal, and configuration value is auditable and reproducible.
- **Not an ML platform.** Phase 1 contains no model training, inference, or probabilistic forecasting.
- **Not a production trading system.** This is a research laboratory. Paper trading and live execution belong to later phases, gated behind explicit architectural reviews.

---

## Philosophy: robustness over sophistication

The quantitative finance industry has a long history of systems that were clever in design and fragile in practice. AQCS takes the opposite approach.

> A system that reproduces yesterday's results exactly is more valuable than one that produces slightly better results unpredictably.

Concrete implications:

- All data transformations are deterministic. Given the same input, the output is identical across machines and time.
- Configuration is centralised and version-controlled. No runtime magic, no environment-specific surprises.
- Dependencies are pinned. Reproducibility is a first-class requirement, not an afterthought.
- Failures are loud. Silent data corruption is worse than a hard crash.
- The Quant Core has no awareness of the LLM layer. The flow of information is one-directional: quant components emit events; the oversight layer reads them.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Quant Core                            │
│                                                              │
│   Data ──► Features ──► Signals ──► Portfolio ──► Risk      │
│     │                                                 │      │
│   (Parquet)                                     Execution   │
│                                                 (read-only  │
│                                                  Phase 1)   │
└──────────────────────────────────────────────────────────────┘
                              │
                        Event stream
                    (OversightEvent, read-only)
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     LLM Oversight Layer                      │
│                                                              │
│   Observes events. Writes narrative logs. Takes no actions.  │
└──────────────────────────────────────────────────────────────┘
```

### Source packages

| Package | Responsibility |
|---------|---------------|
| `src/aqcs/data/` | Market data acquisition. Downloads, validates, and persists OHLCV and other market data. No transformation logic. |
| `src/aqcs/features/` | Deterministic feature engineering applied to raw data frames. Pure functions only. |
| `src/aqcs/signals/` | Rules-based and statistical signal generation. Output is a scalar or series in {−1, 0, +1} or a probability. |
| `src/aqcs/portfolio/` | Combines signals into target weight vectors, subject to constraints. |
| `src/aqcs/risk/` | Position sizing, drawdown limits, concentration limits. All thresholds are configuration-driven. |
| `src/aqcs/execution/` | Order management interface. Read-only in Phase 1. Dry-run logging only. |
| `src/aqcs/backtesting/` | Historical simulation. No look-ahead bias by construction. |
| `src/aqcs/monitoring/` | Data quality probes and system health checks. |
| `src/aqcs/utils/` | Configuration loader, structured logging, typed event schema. |
| `src/aqcs/llm_oversight/` | Read-only observer. Receives `OversightEvent` records. Never modifies state. |

Full component specifications: [`docs/architecture/system-architecture-v1.md`](docs/architecture/system-architecture-v1.md).

---

## Quant Core

The Quant Core comprises all modules except `llm_oversight`. It operates under the following invariants:

1. **Determinism.** All functions are pure or explicitly stateful with auditable state. Random processes receive an explicit seed.
2. **No runtime configuration mutation.** Configuration is loaded once at startup. No component may alter it during execution.
3. **No external API calls from signal logic.** Data is fetched by `src/aqcs/data/`. Signal and feature modules operate on local files only.
4. **Typed contracts.** All inter-module data is exchanged via typed Pydantic models or typed Pandas DataFrames with declared schemas.
5. **Explicit failures.** Schema violations, missing data, and unexpected values raise exceptions. No silent fallbacks.

---

## LLM Oversight

The LLM Oversight layer is a passive observer. Its role is documentation and auditability, not decision-making.

**It is permitted to:**
- Receive `OversightEvent` records emitted by Quant Core components.
- Write narrative observations to `docs/bitacora/`.
- Summarise what happened, in human-readable form.
- Flag anomalies in logs for human review.

**It is prohibited from:**
- Modifying any system state.
- Calling any exchange API.
- Generating trading signals or weight adjustments.
- Running autonomously without a human review checkpoint.

The boundary is enforced architecturally: `src/aqcs/llm_oversight` has read access to the event bus and write access only to `docs/bitacora/`. It imports from `src/aqcs/utils` only.

---

## Roadmap

### Phase 1 — Foundation Layer (current)

Infrastructure. Data acquisition. Storage conventions. Logging. Configuration. Event schema. Unit tests. No trading logic.

- [x] Repository structure and tooling
- [x] Centralised YAML configuration with environment overrides
- [x] Structured JSON logging (`structlog`)
- [x] Typed, immutable event schema (Pydantic v2)
- [x] OHLCV downloader: Binance Spot → Parquet (ccxt, paginated, CLI)
- [x] LLM Oversight observer skeleton
- [x] Unit test suite (pytest, mocked network)

### Phase 2 — Research Layer

Deterministic feature pipeline. Vectorised backtesting. Data quality monitoring.

- [ ] Feature engineering pipeline (moving averages, volatility, momentum)
- [ ] Vectorised backtesting engine with transaction cost model
- [ ] Data quality checks (gap detection, stale price detection, outlier flagging)
- [ ] Performance metrics (Sharpe, Calmar, max drawdown, turnover)
- [ ] CI/CD pipeline (GitHub Actions)

### Phase 3 — Signal Layer

Rules-based signal generation. Portfolio construction. Risk management.

- [ ] Signal framework (entry/exit rules, combiners)
- [ ] Long-only portfolio construction (equal weight, volatility parity)
- [ ] Risk constraints (position limits, drawdown stops, concentration limits)
- [ ] Paper trading integration (read-only exchange connection)

### Phase 4 — Execution Layer

Live execution infrastructure, conditional on Phase 3 audit.

- [ ] Order management system (OMS)
- [ ] Execution algorithm library (TWAP, VWAP)
- [ ] Real-time data feed integration
- [ ] Live risk monitoring

> **Phases 3 and 4 require an explicit architecture review before implementation begins.**

---

## Setup

### Requirements

- Python 3.11 or later
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`
- Binance account with a **read-only** API key (optional; public endpoints work without credentials)

### Install

```bash
git clone <repo-url>
cd aqcs

# With uv (recommended)
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

# With pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env — credentials are optional for public data
```

### Verify the installation

```bash
pytest
```

All tests should pass. No network access is required.

---

## Basic usage

### Download OHLCV data

```bash
# Daily candles, BTC/USDT, from 2023-01-01 to today
python -m aqcs.data.ohlcv --symbol BTC/USDT --start 2023-01-01

# 4-hour candles, custom date range
python -m aqcs.data.ohlcv --symbol ETH/USDT --timeframe 4h \
    --start 2024-01-01 --end 2024-06-01

# Batch download
for sym in BTC/USDT ETH/USDT SOL/USDT; do
    python -m aqcs.data.ohlcv --symbol "$sym" --start 2023-01-01
done

# Shell convenience wrapper
AQCS_SYMBOLS="BTC/USDT ETH/USDT SOL/USDT" ./scripts/download_ohlcv.sh
```

Output is written to `data/raw/<SYMBOL>_<TIMEFRAME>.parquet`.

### Read downloaded data

```python
import pandas as pd

df = pd.read_parquet("data/raw/BTC_USDT_1d.parquet")
print(df.dtypes)
print(df.head())
```

### Docker

```bash
docker compose up
```

The container runs the test suite by default. Override the command to run other scripts.

---

## Configuration

Configuration is hierarchical:

```
configs/base.yaml           — project-wide defaults (version-controlled)
configs/<AQCS_ENV>.yaml     — environment override (version-controlled)
.env                        — secrets: API keys (never committed)
```

The active environment is set via `AQCS_ENV` (default: `development`). Secret values are accessed exclusively through `src/aqcs/utils/config.Settings`; no `os.environ` calls appear in business logic.

Feature flags in `base.yaml` enforce the Phase 1 constraints at the configuration level:

```yaml
features:
  live_data: false
  order_execution: false
  autonomous_trading: false
```

These flags are checked at startup. Enabling them in production requires a deliberate configuration change and a corresponding log entry.

---

## Conventions

### Code

| Concern | Tool | Configuration |
|---------|------|---------------|
| Formatting | `black` | line-length 100 |
| Linting | `ruff` | target py311, strict |
| Type checking | `mypy` | `--strict` |
| Testing | `pytest` | `tests/` directory |

Run before committing:

```bash
black src/ tests/
ruff check src/ tests/ --fix
mypy src/
pytest
```

### Data

- Raw data is immutable. Transformations produce new files in `data/processed/`.
- All timestamps are UTC. Naive datetimes are not permitted.
- All Parquet files are written with a declared PyArrow schema. Schema drift raises an error at write time.
- File naming: `<SYMBOL>_<TIMEFRAME>.parquet`, where `/` in symbol names is replaced with `_`.

### Logging

- `structlog` exclusively. No `print()`.
- Every log call leads with a named event string: `logger.info("ohlcv_fetched", symbol=..., rows=...)`.
- `DEBUG` — internal state. `INFO` — significant milestones. `WARNING` — degraded behaviour. `ERROR` — requires human attention.

### Git

- Branch naming follows lightweight Gitflow:
  `feat/`, `fix/`, `docs/`, `test/`, `chore/`, `data/`, `exp/`
- Task commits use `<TASK-ID>: <imperative present-tense summary>`
- Non-trivial design decisions are documented as ADRs in `docs/decisions/`
- Full branch, commit, push, and merge rules live in
  `docs/standards/project-standards.md#6-git-workflow`

---

## Critical constraints

The following constraints apply to all phases. They are not relaxed without an explicit architecture decision record.

1. **No secrets in version control.** API keys, passphrases, and credentials live exclusively in `.env`.
2. **No order submission in Phase 1.** The execution module is read-only. Any code path that would submit an order is a defect.
3. **No LLM-generated trading signals.** The LLM Oversight layer does not produce signals, weights, or any input to the Quant Core.
4. **No mutable global state.** Configuration is loaded once. Modules communicate through function arguments and return values.
5. **API keys are read-only.** Binance API keys used in AQCS must be provisioned with market data permissions only. Withdrawal and trading permissions must be disabled at the exchange level.
6. **All downloaded data passes schema validation before being written to disk.**

---

## Project layout

```
aqcs/
├── configs/                  — YAML configuration
├── data/
│   ├── raw/                  — Verbatim from exchange (gitignored)
│   ├── processed/            — Transformed data (gitignored)
│   └── external/             — Third-party datasets (gitignored)
├── docs/
│   ├── architecture/         — System design documents
│   ├── bitacora/             — Chronological project log
│   ├── decisions/            — Architecture Decision Records (ADRs)
│   ├── research/             — Research notes and references
│   └── standards/            — Engineering standards
├── experiments/              — Disposable exploratory scripts
├── logs/                     — Structured JSON logs (gitignored)
├── notebooks/                — Curated analysis notebooks
├── requirements/
│   ├── base.txt              — Runtime dependencies (pinned)
│   └── dev.txt               — Development dependencies (pinned)
├── scripts/                  — Utility scripts
├── src/
│   └── aqcs/
│       ├── data/                 — Data acquisition
│       ├── features/             — Feature engineering
│       ├── signals/              — Signal generation
│       ├── portfolio/            — Portfolio construction
│       ├── risk/                 — Risk management
│       ├── execution/            — Order management (read-only, Phase 1)
│       ├── backtesting/          — Simulation engine
│       ├── monitoring/           — Data quality and system health
│       ├── utils/                — Config, logging, events
│       └── llm_oversight/        — LLM observer (read-only)
└── tests/
    ├── unit/                 — Mocked, no network
    └── integration/          — Requires live credentials
```

---

## Governance (for AI agents)

AQCS uses multiple AI systems in collaboration with human oversight. Every AI agent must read the following documents before making changes:

| Document | Purpose |
|----------|---------|
| [`AGENTS.md`](AGENTS.md) | Entry point — constraints, forbidden actions, workflow |
| [`docs/ai/AQCS_CONTEXT.md`](docs/ai/AQCS_CONTEXT.md) | Canonical project context and implemented layers |
| [`docs/ai/AGENT_ROLES.md`](docs/ai/AGENT_ROLES.md) | Role boundaries and permissions per agent |
| [`docs/ai/TASK_PROTOCOL.md`](docs/ai/TASK_PROTOCOL.md) | Task format, ID system, workflow |
| [`docs/ai/HANDOFF_TEMPLATE.md`](docs/ai/HANDOFF_TEMPLATE.md) | Mandatory handoff record format |
| [`docs/ai/agent_registry.yaml`](docs/ai/agent_registry.yaml) | Static agent registry |

Architecture Decision Records: [`docs/decisions/`](docs/decisions/)  
Objective tracking: [`docs/objectives/`](docs/objectives/)  
Project log: [`docs/bitacora/`](docs/bitacora/)

---

## License

MIT
