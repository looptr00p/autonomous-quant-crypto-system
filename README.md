# AQCS — Autonomous Quant Crypto System

An institutional-grade quantitative research laboratory for crypto spot markets.

## What this is

AQCS is a modular, reproducible foundation for systematic research on crypto spot markets. It is not a trading bot. It does not make trading decisions. It does not execute orders.

Phase 1 (current) establishes the infrastructure layer: data acquisition, storage conventions, structured logging, configuration management, and the event schema that all subsequent modules will use.

## What this is not

- A trading bot
- An autonomous agent with market access
- A black-box ML system
- A get-rich-quick tool

## Architecture overview

```
src/
├── data/          — Market data acquisition (OHLCV, order book, etc.)
├── features/      — Feature engineering (deterministic transforms)
├── signals/       — Signal generation (rules-based, statistical)
├── portfolio/     — Portfolio construction
├── risk/          — Risk management and position sizing
├── execution/     — Order management (read-only in Phase 1)
├── backtesting/   — Historical simulation engine
├── monitoring/    — System health and data quality
├── utils/         — Config, logging, events
└── llm_oversight/ — LLM observation layer (never a decision-maker)
```

See `docs/architecture/architecture.md` for the full design.

## Quick start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install

```bash
# Clone
git clone <repo-url>
cd aqcs

# Create virtual environment and install
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

# Or with pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Copy env template
cp .env.example .env
# Edit .env — add Binance read-only API keys if you want private endpoints
```

### Run the tests

```bash
pytest
```

### Download OHLCV data

```bash
# Daily BTC/USDT from 2023-01-01 to today
python -m src.data.ohlcv --symbol BTC/USDT --start 2023-01-01

# 4-hour ETH/USDT, custom range
python -m src.data.ohlcv --symbol ETH/USDT --timeframe 4h --start 2024-01-01 --end 2024-06-01

# Multiple symbols via shell loop
for sym in BTC/USDT ETH/USDT SOL/USDT; do
  python -m src.data.ohlcv --symbol "$sym" --start 2023-01-01
done
```

Data is saved to `data/raw/<SYMBOL>_<TIMEFRAME>.parquet`.

### Docker

```bash
docker compose up
```

## Configuration

All configuration lives in `configs/base.yaml`. Environment-specific overrides go in `configs/<env>.yaml`. Secret values (API keys) are loaded from `.env` via `python-dotenv` — never hardcoded.

The active environment is controlled by the `AQCS_ENV` variable (default: `development`).

## Design principles

| Principle | Implementation |
|-----------|---------------|
| Reproducibility | Parquet storage, pinned deps, deterministic transforms |
| Simplicity | Single config file, no frameworks beyond the stack |
| Modularity | Each `src/` subdirectory is independent |
| No hidden state | Structured JSON logs for everything |
| No LLM trading | `llm_oversight` is read-only by design |

## Project structure

```
aqcs/
├── configs/           — YAML configuration files
├── data/              — Local data store (gitignored)
├── docs/              — Architecture, standards, decisions, research
├── experiments/       — Ad-hoc notebooks and scripts
├── logs/              — Structured JSON logs (gitignored)
├── notebooks/         — Curated analysis notebooks
├── requirements/      — Pinned dependency files
├── scripts/           — Utility shell/Python scripts
├── src/               — Source packages
└── tests/             — pytest test suite
```

## Contributing

See `docs/standards/standards.md`.

## License

MIT
