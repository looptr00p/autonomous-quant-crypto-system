# AQCS Project Standards

**Version:** 1.0.0  
**Date:** 2026-05-16  
**Status:** Mandatory  
**Scope:** All code, configuration, experiments, and documentation in this repository.

These standards are not guidelines. Non-conforming code is not accepted into `main`.

---

## Table of contents

1. [Naming conventions](#1-naming-conventions)
2. [Logging](#2-logging)
3. [Configuration](#3-configuration)
4. [Experiments](#4-experiments)
5. [Testing](#5-testing)
6. [Anti-complexity rules](#6-anti-complexity-rules)

---

## 1. Naming conventions

### 1.1 Files and modules

| Entity | Convention | Example |
|--------|-----------|---------|
| Python source files | `snake_case` | `ohlcv_downloader.py` |
| Configuration files | `snake_case` | `base.yaml`, `development.yaml` |
| Test files | `test_<module>.py` | `test_ohlcv_downloader.py` |
| Shell scripts | `snake_case.sh` | `download_ohlcv.sh` |
| Documentation | `kebab-case.md` | `project-standards.md` |
| Experiment records | `YYYY-MM-DD_<slug>.md` | `2026-05-16_btc-momentum-baseline.md` |

### 1.2 Python identifiers

| Entity | Convention | Example |
|--------|-----------|---------|
| Functions | `snake_case` | `fetch_ohlcv`, `compute_rolling_vol` |
| Variables | `snake_case` | `close_price`, `lookback_days` |
| Module-level constants | `UPPER_SNAKE_CASE` | `OHLCV_SCHEMA`, `MAX_CANDLES_PER_REQUEST` |
| Classes | `PascalCase` | `OHLCVDownloader`, `RiskConstraints` |
| Pydantic models | `PascalCase` | `DataEvent`, `PortfolioWeights` |
| Enums and enum members | class `PascalCase`, members `UPPER_SNAKE_CASE` | `EventSeverity.INFO` |
| Private functions | leading `_` | `_build_exchange`, `_paginate` |
| Private class attributes | leading `_` | `self._cache` |
| Type aliases | `PascalCase` | `WeightVector = dict[str, float]` |

### 1.3 Rules

- **No abbreviations** unless they are universally understood in the quant finance domain (`ohlcv`, `vwap`, `pnl`, `nav`). `calc` is not acceptable; `compute` is.
- **No single-letter variables** outside of mathematical loop indices (`i`, `j`) or conventional notation in documented formulas (`mu`, `sigma`).
- **Booleans are named as predicates**: `is_valid`, `has_data`, `enable_live_data` — never `valid`, `data_flag`, `live`.
- **Collection names are plural**: `symbols`, `candles`, `weights` — never `symbol_list`, `candle_array`.
- **Functions that return booleans** begin with `is_`, `has_`, `can_`, or `should_`.
- **Functions that produce side effects** (I/O, network, disk) begin with `fetch_`, `save_`, `write_`, `send_`, or `load_`. Pure transforms do not.

---

## 2. Logging

### 2.1 Required fields

Every log record must include the following fields. The `structlog` framework enforces this when configured via `src/utils/logging.configure_logging()`.

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 UTC string | Moment the event occurred. Always UTC. Never local time. |
| `level` | string | `debug`, `info`, `warning`, `error`, `critical` |
| `event` | string | Machine-readable event identifier. See §2.3. |
| `component` | string | Dotted module path of the emitting code (`src.data.ohlcv`) |
| `message` | string | Human-readable description of what happened |

### 2.2 Conditional fields

| Field | Type | When required |
|-------|------|--------------|
| `correlation_id` | UUID string | Any multi-step operation that spans more than one function call or process boundary. Set at the start of a pipeline run and propagated via `structlog.contextvars`. |
| `symbol` | string | Any event related to a specific instrument |
| `timeframe` | string | Any event related to a specific data resolution |
| `duration_ms` | int | Any event that measures elapsed time |
| `rows` | int | Any event that describes a data operation |
| `error` | string | Any `warning`, `error`, or `critical` event |
| `traceback` | string | Any `error` or `critical` event with an exception |

### 2.3 Event naming

Log events are `snake_case` identifiers that follow the pattern `<subject>_<verb>` or `<subject>_<state>`:

```
ohlcv_fetch_started
ohlcv_page_fetched
ohlcv_fetch_complete
ohlcv_fetch_failed
parquet_saved
parquet_schema_mismatch
config_loaded
exchange_connected
exchange_timeout
data_gap_detected
```

Rules:
- Event identifiers are stable across releases. Renaming a log event is a breaking change.
- Use past tense for completed actions (`ohlcv_fetched`), present progressive for in-progress (`ohlcv_fetching`), and `_failed` suffix for error states.
- No free-form messages as the primary event key. The event key must be greppable and consistent.

### 2.4 What not to log

- Raw API credentials or secrets, even partially.
- Full response bodies from external APIs unless `LOG_LEVEL=DEBUG` is explicitly set.
- Personal information.
- Redundant state that is already captured by a surrounding event.

### 2.5 Usage

```python
from aqcs.utils.logging import get_logger
import structlog

logger = get_logger(__name__)

# Correct
logger.info("ohlcv_fetch_complete", symbol="BTC/USDT", rows=365, duration_ms=1240)

# Incorrect — no event key, no structured fields
logger.info(f"Fetched 365 rows for BTC/USDT in 1240ms")

# Correct — correlation_id propagated across a pipeline run
structlog.contextvars.bind_contextvars(correlation_id=str(run_id))
logger.info("pipeline_started")
# ... downstream calls inherit correlation_id automatically
structlog.contextvars.clear_contextvars()
```

---

## 3. Configuration

### 3.1 Hierarchy

Configuration is loaded in priority order, later sources overriding earlier ones:

```
1. configs/base.yaml          — project-wide defaults (always present, always committed)
2. configs/<AQCS_ENV>.yaml    — environment-specific overrides (committed)
3. .env                       — secret values only (never committed)
4. Environment variables      — CI/CD and container overrides
```

### 3.2 Rules

**Nothing is hardcoded.** The following categories of values must never appear as literals in source code:

- Exchange names, symbols, or timeframes used as defaults
- Numeric thresholds: lookback windows, fee rates, slippage estimates, position limits
- File paths beyond the project root
- Timeout values and retry counts
- Anything that might differ between environments or experiments

The test for whether a value should be in config: *would changing this value require editing source code?* If yes, it belongs in `configs/base.yaml`.

**Sensitive values are isolated.** The `.env` file contains only:

- API keys and secrets
- Passwords and tokens
- Any value that must not appear in git history or CI logs

Sensitive values are accessed exclusively via the `Settings` class in `src/utils/config`. No module outside of `src/utils/config` calls `os.environ` or `os.getenv` directly.

**Configs are versioned.** `configs/base.yaml` and all environment override files are committed to version control. Changes to configuration that affect research results must be accompanied by a git commit. An experiment run is only reproducible if the config state at the time of the run can be reconstructed from git history.

**Experiment parameters are explicit.** Parameters that affect research outputs — lookback windows, universe selection criteria, rebalancing frequency, transaction cost assumptions — are declared in configuration or passed explicitly as function arguments. They are never derived implicitly from environment state or external calls.

### 3.3 Adding a new configuration value

1. Add the key to `configs/base.yaml` with a conservative default.
2. Add a comment above the key explaining what it controls and valid ranges.
3. If the value is environment-specific, add overrides to the appropriate `configs/<env>.yaml`.
4. If the value is typed and accessed from Python, add a typed field to `Settings` or update `load_config()` callers.
5. Add or update the corresponding unit test in `tests/unit/test_config.py`.

---

## 4. Experiments

### 4.1 Definition

An experiment is any research run that produces a result intended to inform a decision: signal evaluation, parameter search, strategy comparison, or data quality assessment.

Exploratory code in `experiments/` that is discarded does not require a record. Any result that is cited, compared against, or used to justify a design choice does.

### 4.2 Required record

Each experiment produces a Markdown record in `experiments/` with the following structure:

```markdown
# Experiment: <short descriptive title>

## Metadata

| Field          | Value |
|----------------|-------|
| Date           | YYYY-MM-DD |
| Commit hash    | <full git SHA at time of run> |
| Author         | <name> |
| Status         | draft | complete | superseded |

## Dataset

| Field          | Value |
|----------------|-------|
| Source         | Binance Spot / external / synthetic |
| Symbols        | BTC/USDT, ETH/USDT, ... |
| Timeframe      | 1d / 4h / 1h |
| Start date     | YYYY-MM-DD |
| End date       | YYYY-MM-DD |
| Candle count   | <integer> |
| Data file(s)   | data/raw/BTC_USDT_1d.parquet |

## Parameters

```yaml
lookback_days: 90
signal_threshold: 0.02
rebalancing_frequency: weekly
transaction_cost_bps: 10
```

## Metrics

| Metric              | Value |
|---------------------|-------|
| Annualised return   | x.xx% |
| Annualised vol      | x.xx% |
| Sharpe ratio        | x.xx |
| Max drawdown        | x.xx% |
| Calmar ratio        | x.xx |
| Turnover (annual)   | x.xx% |

## Output files

- `experiments/<slug>/results.parquet`
- `experiments/<slug>/equity_curve.csv`

## Notes

<Observations, anomalies, next steps, open questions. Written in complete sentences.>

## Conclusion

<One or two sentences: what this experiment established or ruled out.>
```

### 4.3 Reproducibility requirement

An experiment record is only considered complete when a second person can run the experiment from scratch — using the recorded commit hash, dataset, and parameters — and obtain results within acceptable numerical tolerance (rounding differences only).

If the experiment cannot be reproduced exactly, the record must document why (e.g., external data source no longer available, stochastic process with unfixed seed) and what steps approximate reproduction.

### 4.4 Commit hash discipline

Run experiments on a clean working tree. Record the commit hash before running. If the experiment requires code changes, commit those changes first. An experiment run on an unclean working tree is not reproducible by definition.

```bash
git status          # must show "nothing to commit, working tree clean"
git rev-parse HEAD  # record this in the experiment metadata
```

---

## 5. Testing

### 5.1 Framework

`pytest` is the only accepted test runner. No `unittest.TestCase` subclasses unless interoperability with an external library requires it.

### 5.2 Test organisation

```
tests/
├── unit/          — Fast, no I/O, no network. All external dependencies mocked.
└── integration/   — May use real data files or live APIs. Requires AQCS_ENV=integration.
```

Every source module in `src/` has a corresponding test file in `tests/unit/`:

```
src/data/ohlcv.py           →  tests/unit/test_ohlcv.py
src/utils/config.py         →  tests/unit/test_config.py
```

### 5.3 What must be tested

The following always require unit tests:

- Any function that transforms data (feature engineering, signal computation, weight construction)
- Any function that validates or rejects input (schema checks, parameter bounds)
- Any function that produces a file or structured output
- Any configuration loading or parsing logic
- Any event schema or Pydantic model

The following do not require unit tests, but may have integration tests:

- Functions whose entire body is a third-party API call
- CLI entry points (test the underlying logic, not the click wrappers)

### 5.4 Test rules

**No network calls in unit tests.** Use `unittest.mock.patch` or `pytest-mock` to intercept all ccxt, HTTP, and filesystem calls. A unit test that touches the network is not a unit test.

**No `time.sleep` in tests.** Mock time-dependent behaviour.

**Tests are independent.** No test depends on the execution order of other tests. No shared mutable state between tests. Use `tmp_path` (pytest fixture) for any file I/O.

**Tests are named descriptively.** The test name states what is being tested and what the expected outcome is:

```python
# Correct
def test_fetch_ohlcv_deduplicates_overlapping_candles():
def test_settings_rejects_invalid_log_level():
def test_parquet_schema_enforces_utc_timestamps():

# Incorrect
def test_fetch():
def test_settings_2():
def test_parquet():
```

**Tests assert specific values**, not just that no exception was raised:

```python
# Correct
assert df["symbol"].unique()[0] == "BTC/USDT"
assert len(df) == 365
assert df["timestamp"].dt.tz == timezone.utc

# Insufficient
assert not df.empty
```

### 5.5 Coverage

Minimum enforced coverage: **80%** on `src/`. Coverage is measured by `pytest-cov` on every CI run. Coverage regressions block merges to `main`.

Coverage below 80% is a signal that a module is not testable as written, which is a design problem, not a coverage problem.

### 5.6 Non-testable code is not accepted

If a function cannot be unit-tested without significant mocking complexity, it should be refactored before it is merged. The inability to test a function is evidence that it has too many responsibilities. Extract the testable logic into a pure function and isolate the side-effecting wrapper.

---

## 6. Anti-complexity rules

These rules exist because complexity in a research system is not a feature — it is a liability. Every layer of abstraction added without a concrete, immediate justification increases the probability of undetected bugs in research results.

### 6.1 No machine learning without approval

ML models — including but not limited to neural networks, gradient boosting, clustering, and dimensionality reduction — are not permitted in `src/` without a written architecture decision record (ADR) that:

- Justifies why a statistical or rules-based approach is insufficient.
- Specifies how the model will be validated out-of-sample.
- Specifies how the model will be monitored for degradation in production.
- Has been reviewed and approved by at least one other person.

Phase 1 and Phase 2 contain no ML. This is not a temporary limitation — it is a deliberate sequencing decision. A rigorous rules-based baseline must exist before any ML component is introduced, so that the ML component can be evaluated against a known reference.

### 6.2 No microservices

All Phase 1–2 code runs as a single Python process or as a scheduled script. No inter-service communication, no message queues, no service meshes, no distributed state stores.

If a component genuinely requires independent scaling or fault isolation, that requirement must be documented and approved before any microservice infrastructure is introduced. The burden of proof is on the proposal, not the opposition.

### 6.3 No live order execution in Phase 1

No code path that submits an order to an exchange exists in Phase 1. The `src/execution/` module is present for architecture purposes. It contains read-only helpers, dry-run logging, and order builder utilities. Any function that would call `exchange.create_order()`, `exchange.place_order()`, or equivalent is a defect.

The transition from Phase 2 to Phase 3 (paper trading) and from Phase 3 to Phase 4 (live execution) each require a dedicated architecture review. The configuration flag `features.order_execution` remains `false` until that review is completed and documented.

### 6.4 No premature optimisation

Performance optimisation is not permitted unless:

- A concrete, measured performance problem exists (profiler output, not intuition).
- The baseline (unoptimised) implementation is already correct and tested.
- The optimisation does not reduce readability or testability.

Vectorisation for clarity (using pandas/numpy instead of Python loops over DataFrames) is not optimisation — it is idiomatic. Caching, parallelism, and algorithmic shortcuts introduced before a bottleneck is measured are premature and are not accepted.

### 6.5 No abstraction without two concrete use cases

A new abstraction (base class, protocol, generic function, decorator, metaclass) requires at least two existing concrete use cases in the codebase. An abstraction written for one caller is a prediction about the future. That prediction is usually wrong and always costly.

Prefer three similar functions over a premature abstraction. Refactor when the pattern is clear from evidence, not from anticipation.

### 6.6 No configuration-as-code

Logic that belongs in configuration must not be embedded in code. The inverse also applies: logic that cannot be expressed declaratively must not be forced into YAML. When the boundary is unclear, write a plain Python function with explicit parameters and test it. Configuration supplies the parameters; code supplies the logic.

---

## Enforcement

These standards are enforced through:

1. **CI/CD checks** — `black`, `ruff`, `mypy`, and `pytest` run on every pull request. Failures block merges.
2. **Code review** — Reviewers are expected to check for violations of §1, §3, §4, and §6 that automated tools cannot detect.
3. **ADR process** — Any proposed exception to §6 must be submitted as an ADR in `docs/decisions/` before implementation begins.

Exceptions to these standards are permitted only when documented and approved. The documentation must explain what is being excepted, why the standard cannot be met in that specific case, and what mitigations are in place.

---

*This document supersedes `docs/standards/standards.md`, which is deprecated. `standards.md` is retained for historical context only. This document is the sole canonical standards reference.*
