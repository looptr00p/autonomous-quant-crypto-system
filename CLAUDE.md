# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# All checks — must pass before any commit
PYTHONPATH=src pytest tests/ -q --no-cov
ruff check src/ tests/
black --check src/ tests/
mypy src/

# Single test file
PYTHONPATH=src pytest tests/unit/test_backtesting_engine.py -q --no-cov

# Single test by name
PYTHONPATH=src pytest tests/unit/test_backtesting_engine.py -q --no-cov -k "test_determinism"

# Download OHLCV data
PYTHONPATH=src python -m aqcs.data.ohlcv --symbol BTC/USDT --timeframe 1d --start 2023-01-01

# List experiments
PYTHONPATH=src python scripts/list_experiments.py --storage experiments/
```

Notebooks and `experiments/` are excluded from ruff, black, and mypy.

---

## Architecture

### Two-layer system — boundary is enforced by CI

```
Quant Core (deterministic):
  aqcs.utils → aqcs.data → aqcs.features → aqcs.signals
                                                      ↓
                                          aqcs.backtesting
                                          aqcs.experiments
                                          aqcs.monitoring

LLM Oversight (read-only observer):
  aqcs.llm_oversight — subscribes to EventBus, never writes to Quant Core
```

The import DAG is enforced by `tests/architecture/test_dependency_boundaries.py` via AST analysis — no runtime imports. Violating it is a CI failure. The canonical DAG lives in `ALLOWED` dict in that file.

`aqcs.llm_oversight` may only import from `aqcs.utils`. It cannot import data, features, signals, or any execution module.

### Event bus

`EventBus` in `aqcs.utils.event_bus` is synchronous, in-process only, and has no global singleton — it must be dependency-injected. Events flow Core → Oversight only. `OversightObserver` subscribes to all categories except `OVERSIGHT` (prevents feedback loops). Failing handlers do not crash other handlers.

### Phase Guard

`aqcs.utils.phase_guard.assert_allowed(Feature.X)` raises `PhaseConstraintError` if `X` is blocked in `CURRENT_PHASE`. Call it at the entry point of any gated capability. `CURRENT_PHASE = 1` currently. The full block list for Phase 1 is in `phase_guard.py` — it includes `ORDER_EXECUTION`, `MACHINE_LEARNING`, `LIVE_TRADING`, `PAPER_TRADING`, `WEBSOCKET_STREAMING`, and more.

Do not modify `CURRENT_PHASE` without an approved ADR and explicit human instruction.

### Backtesting engine

Entry point: `aqcs.backtesting.engine.run_backtest(ohlcv, signals, config)`.

- `BacktestConfig` (in `backtesting/models.py`) requires `fee_bps` and `slippage_bps` as mandatory fields — no silent zero defaults.
- `ohlcv` DataFrame must have a `timestamp` column (not just an index), plus `symbol`, `exchange`, `timeframe`, `open`, `high`, `low`, `close`, `volume`.
- `signals` is a `pd.Series` of `SignalDirection` (`LONG` / `SHORT` / `NEUTRAL`) indexed by UTC timestamps.
- Signal at T executes at T+1 open (enforced by `shift(1)` in engine). Same-bar execution is tested and must not be possible.
- Results are in `BacktestResult.metrics` (a dict), not as attributes. Fields: `total_return`, `cagr`, `max_drawdown`, `sharpe_ratio`, `annualised_volatility`, `trade_count`, `win_rate`, `exposure`.

### Experiment tracker

`ExperimentTracker(storage_dir: Path | str)` — `storage_dir` is coerced to `Path` internally.
Key methods: `create_experiment(name, ...)`, `complete_experiment(experiment_id, metrics={...})`, `get_experiment(experiment_id)`.
The field on `ExperimentRecord` is `experiment_id` (a `UUID`), not `id`.

### Data validation

`aqcs.data.validator.validate_ohlcv(df, symbol, timeframe)` runs 13 checks. It returns a `ValidationResult` — check `is_valid` and `errors` before using data. The backtesting engine calls this automatically; outside the engine, call it explicitly before feature computation.

---

## Git workflow

- Branch from `master`. Use prefixes: `feat/`, `fix/`, `docs/`, `test/`, `chore/`, `data/`, `exp/`
- Commit format: `<TASK-ID>: <imperative present-tense summary>` (e.g. `TASK-006: add momentum signal`)
- Non-task commits: `fix:`, `docs:`, `feat:`, `test:`, `chore:`
- Do not commit directly to `master`. Merging to `master` requires human approval.
- Delete remote branches after merge.

Full rules: `docs/standards/project-standards.md §6`.

---

## Governance requirements

Every agent session that modifies the repository must:
1. Use a task-scoped branch (never `master` directly).
2. Assign a `TASK-ID` following `docs/ai/TASK_PROTOCOL.md`.
3. Complete a handoff record in `docs/bitacora/` using `docs/ai/HANDOFF_TEMPLATE.md` before stopping.
4. Run and pass all four verification commands before committing.

Actions requiring explicit human approval before proceeding:
- Changing `CURRENT_PHASE` in `phase_guard.py`
- Setting any feature flag to `true` in `configs/base.yaml`
- Adding a new third-party dependency
- Creating or modifying an ADR (`docs/decisions/`)
- Merging to `master`

---

## What is implemented vs. stub

**Implemented and tested:**
- `aqcs.utils` — config, logging, events (20 typed event names), event bus, phase guard
- `aqcs.data` — OHLCV downloader (ccxt/Binance Spot, paginated), 13-step validator
- `aqcs.features` — `returns.py`, `trend.py`, `volatility.py` (pure functions, no EventBus dependency)
- `aqcs.signals` — momentum, trend, combined (pure functions, `SignalDirection` from `aqcs.utils.events`)
- `aqcs.experiments` — `ExperimentTracker`, `ExperimentRecord`, fingerprinting, JSON storage
- `aqcs.backtesting` — deterministic engine, fee/slippage model, 8 required metrics, ExperimentTracker integration
- `aqcs.llm_oversight` — `OversightObserver` (reads events, writes logs, never trades)

**Stubs (empty `__init__.py` only):**
- `aqcs.execution`, `aqcs.portfolio`, `aqcs.risk`, `aqcs.monitoring`

**Market data on disk** (`data/raw/`): BTC/ETH/SOL in `1d` (2023–present, ~1,233 rows each) and short `1h/1m/5m` samples from 2026-05-16 only.
