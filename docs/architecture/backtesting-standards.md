# AQCS Backtesting Standards

**Version:** 1.0.0  
**Date:** 2026-05-17  
**Status:** Active — Mandatory  
**Scope:** All backtesting and historical simulation in AQCS, all phases  
**Related ADR:** ADR-005

> These standards define what a valid backtest is. No simulation engine may be
> implemented in AQCS without satisfying every constraint in this document.

---

## A. Purpose

### Why standards before the engine

In quantitative finance, the most expensive mistake is discovering that a backtest was unrealistic after capital has been deployed. Overfit strategies, lookahead bias, zero-slippage assumptions, and survivorship effects have caused fund failures that institutional research would have prevented.

AQCS defines what constitutes a valid backtest *before* writing a single line of simulation code because:

1. **Retrofitting standards onto an existing engine is harder than building to them.** Assumptions become entrenched in code. Changing them later requires re-running all experiments.
2. **An invalid backtest is worse than no backtest.** It creates false confidence. A system that would fail immediately in live trading looks profitable in simulation.
3. **Governance requires auditability.** Every backtest run must be traceable to a specific code version, dataset, and set of assumptions. This is only enforceable if the format is defined before the first run.
4. **The LLM Oversight layer needs a stable reference.** The passive observer cannot audit backtests meaningfully without a canonical definition of what it should observe.

### Why realism matters more than speed

AQCS is not optimised for running thousands of backtests per second. It is optimised for running *valid* backtests that produce *trustworthy* signals about strategy quality. One honest backtest with conservative assumptions is worth more than a hundred optimistic simulations.

---

## B. Core principles

### Determinism

Given the same code version, the same dataset, and the same parameters, a backtest must produce exactly the same results on any machine. This requires:
- No random state without explicit seeding
- No time-dependent logic (e.g., `datetime.now()` inside simulation loops)
- No external API calls during simulation
- Pandas/NumPy operations must be deterministic given the same inputs

### Reproducibility

Every backtest run creates an `ExperimentRecord` that captures the full context needed to recreate the run. See §H for required fields.

### Auditability

Every assumption must be documented in the experiment record and in the configuration that produced the run. "The backtest used realistic assumptions" is not a valid audit statement. "The backtest used 10 bps taker fee and 5 bps half-spread slippage at daily close" is.

### Conservative assumptions

When in doubt, assume worse conditions than reality:
- Overestimate fees
- Overestimate slippage
- Underestimate fill rates
- Assume you are always the price-taker, never the market-maker

An overly conservative backtest that still shows edge is more valuable than an optimistic one that barely shows edge.

### Simplicity before sophistication

Phase 2 backtesting uses daily OHLCV bars. No tick data, no order book, no intrabar simulation. Complexity is introduced only when simpler approaches provably fail to capture a real market dynamic, and only with an ADR justifying the increase.

### Quant-first philosophy

Backtesting is a tool for hypothesis falsification, not hypothesis confirmation. A backtest that cannot fail is not a scientific test. Every backtest should begin with an explicit falsification condition: "This strategy has no edge if [X]."

---

## C. Explicitly forbidden assumptions

The following assumptions are **prohibited** in any AQCS backtest. Code that implements them is a governance violation caught by `tests/governance/test_anti_live_trading.py` and equivalent enforcement.

| Forbidden assumption | Why |
|---------------------|-----|
| Zero transaction fees | Fees are a primary driver of live strategy underperformance. Any strategy that requires zero fees to be profitable has no live edge. |
| Zero slippage | Every market order moves the price against the trader. Slippage is always positive for the taker. |
| Infinite liquidity | Crypto spot markets have finite depth. Large orders incur market impact that grows super-linearly. |
| Perfect fills at signal price | Orders fill at a price worse than the signal price by at least the bid-ask spread plus slippage. |
| Future data access (lookahead) | Using data from bar T+1 to make decisions for bar T is lookahead bias. All forms are prohibited. See §D. |
| Bar-close omniscience | A strategy cannot know the close price of bar T at the open of bar T. Decisions must be based on confirmed, complete bars. |
| Survivorship-free universe (undocumented) | If the backtested universe excludes instruments that delisted or lost value, the dataset must explicitly document this and the backtest must account for its effect. |
| Instantaneous execution | No order is filled instantaneously. All fills occur on the next available bar after signal generation. |
| Hidden leverage | Position sizing must be explicit. Leverage of any kind must be declared in the experiment parameters. Leverage is prohibited in Phase 1 and Phase 2 (see `phase_guard.py`). |
| Stale price fills | Fills must use prices from the execution bar, not from the signal bar. |

---

## D. Lookahead bias prevention

Lookahead bias occurs whenever a strategy uses information that would not have been available at the time a decision was made in historical simulation. It is the most common and most dangerous source of invalid backtests.

### Signal timestamping rule

**A signal generated using data available at the close of bar T may only trigger an execution at the open of bar T+1 or later.**

This means:
- `signal[T]` = f(data[0..T])  — signal uses only data up to and including bar T
- `execution[T+1]` = g(signal[T])  — execution occurs the next bar

Any reversal of this ordering is lookahead bias.

### Feature availability rule

A feature computed for bar T must use only data from bars 0 through T (inclusive). Rolling windows, exponential smoothers, and all statistical transformations must satisfy this invariant.

Formally: `feature[T] = f(data[0], data[1], ..., data[T])` — no future data.

This is verified in tests by asserting that feature functions satisfy `f(data[0..T]) == f(data[0..T+K])[T]` for all K > 0.

### Rolling window cold-start rule

Features that require N bars of history (e.g., a 90-day moving average) are undefined for bars 0 through N-1. These bars must be:
1. Excluded from signal generation (NaN propagation)
2. Excluded from the backtest period (set `start_date` at least N bars after data start)
3. Never filled with forward-projected or backward-projected values

### Target leakage prevention

Any supervised or semi-supervised feature (computed using a label or target variable) is prohibited. Examples:
- A normalisation that uses the full-sample mean and standard deviation
- A volatility estimate that includes the period being tested

All normalisations must use only data available at the time of the feature computation.

### Delayed feature availability

Some features have inherent publication delays. For example:
- On-chain data (e.g., exchange inflows) may be available hours after the fact
- Accounting or earnings data may be delayed days or weeks
- Alternative datasets may have look-ahead in their reported timestamps

All data sources must document their actual availability delay, and the backtesting engine must apply this delay before passing data to signal generators. In Phase 2, all data is assumed available at bar close unless explicitly documented otherwise.

---

## E. Execution timing standards

### Signal generation timing

Signals are generated after the close of bar T. A signal generated at the close of bar T uses:
- The open, high, low, close, and volume of bar T (complete)
- All features computed using data through bar T

### Order placement timing

Orders implied by a signal at bar T close are placed before the open of bar T+1. They are modelled as market orders at the open of bar T+1.

### Fill timing and price

**Default (Phase 2): Fill at open of bar T+1.**

- Fill price = open(T+1) × (1 + slippage_factor × side)
  - For buys: slippage adds to fill price
  - For sells: slippage subtracts from fill price
- Fee deducted from position value at fill time

This is the most common and most conservative daily-bar assumption. It avoids bar-close omniscience and ensures that the strategy cannot know where the day will close before deciding.

### Intrabar limitations

Phase 2 backtesting uses daily bars. Within a bar, no intrabar price path is simulated. The following are therefore prohibited in Phase 2:

- Stop-loss orders based on intrabar prices (a stop can be triggered by the bar's low, but the fill price is unknown)
- Multiple fills within a single bar
- Limit order modelling that requires intrabar price path

### Bar-close assumptions

The close price of bar T is confirmed after bar T ends. It cannot be used for execution during bar T. It can only be used for signals that execute in bar T+1 or later.

---

## F. Fee and slippage standards

### Mandatory fee modelling

Every backtest must include an explicit fee model. A backtest without fees is not valid.

**Phase 2 default fee model:**
```yaml
backtesting:
  fee_model:
    type: "fixed_bps"
    taker_fee_bps: 10      # 0.10% — Binance spot taker fee tier 0
    maker_fee_bps: 7       # 0.07% — Binance spot maker fee tier 0
    default_side: "taker"  # conservative: assume all fills are taker
```

All fee assumptions must be recorded in the experiment `parameters` field.

### Mandatory slippage modelling

Every backtest must include an explicit slippage model. A backtest with zero slippage is not valid.

**Phase 2 default slippage model:**
```yaml
backtesting:
  slippage_model:
    type: "fixed_bps"
    half_spread_bps: 5     # 0.05% half-spread per side
    market_impact_bps: 0   # Phase 2: market impact not modelled
```

Market impact modelling (where order size affects price) is deferred to Phase 3.

### Configurable assumptions

All fee and slippage parameters must be configurable via `configs/`. They must never be hardcoded in simulation logic. This allows sensitivity analysis: running the same strategy under different cost assumptions.

### Conservative defaults

Default parameters err on the side of higher costs. Researchers who believe the defaults are too conservative must justify their alternative assumptions in the experiment `notes` field.

---

## G. Data standards

### Validated OHLCV only

All backtesting data must pass through `src/aqcs/data/validator.py` before use in simulation. Data that has not been validated is prohibited as simulation input.

Validation failures that must block a backtest:
- Naive or non-UTC timestamps
- Duplicate timestamps
- Non-monotonic timestamps
- OHLCV consistency violations (high < low, prices ≤ 0)
- Missing required columns

### UTC timestamps only

All event timestamps in a backtest are UTC. Mixing timezones is prohibited. The simulation clock is UTC throughout.

### Deterministic datasets

A dataset used in a backtest must be frozen at the time of the run. This means:
- The data files must not be modified during the backtest
- The dataset fingerprint must be captured before simulation begins
- Any subsequent download that modifies the data invalidates earlier experiments

### Dataset fingerprinting requirements

Every backtest must capture the dataset fingerprint using `fingerprint_dataset()` from `src/aqcs/experiments/fingerprint.py`. This fingerprint must be stored in the `ExperimentRecord.dataset_fingerprint` field.

### Missing data handling

Missing bars (gaps) in OHLCV data must be explicitly handled. The backtesting engine must declare its gap handling policy in the experiment parameters. Acceptable policies:

| Policy | Description |
|--------|-------------|
| `"halt"` | Halt simulation at the first gap |
| `"carry_forward"` | Carry last known close forward (conservative — introduces stale price bias, must be documented) |
| `"skip"` | Skip the missing bar and continue |

The default policy for AQCS Phase 2 is `"halt"`. Any other policy requires explicit documentation in the experiment record.

### Schema consistency

All data used in a single backtest must share the same schema (columns, types, timezone). Mixing validated data with unvalidated data is prohibited.

---

## H. Experiment tracking integration

### Mandatory ExperimentRecord

Every backtest run must create an `ExperimentRecord` via `ExperimentTracker`. Running a backtest without creating a record is a governance violation.

### Required experiment fields

| Field | Content |
|-------|---------|
| `experiment_name` | Descriptive name including strategy name and version (e.g., `btc_momentum_v1_baseline`) |
| `experiment_type` | `"backtest"` |
| `git_commit_hash` | HEAD commit at the time of the run — must be clean working tree |
| `dataset_fingerprint` | From `fingerprint_dataset()` on all input data files |
| `dataset_paths` | All input data file paths |
| `parameters` | Complete simulation parameters: fee model, slippage model, universe, start_date, end_date, signal parameters, position sizing rules, gap policy |
| `metrics` | Minimum required metrics from §I |
| `artifacts` | Paths to output files: equity curve, trade log, metrics JSON |

### Git cleanliness requirement

Before running any backtest, verify:
```bash
git status  # must show clean working tree
git rev-parse HEAD  # record this in ExperimentRecord
```

A backtest run on a dirty working tree has an unreliable git hash. The research cannot be reproduced.

---

## I. Metrics standards

### Minimum required metrics

Every backtest must compute and record the following metrics in the `ExperimentRecord.metrics` field:

| Metric | Formula / Definition |
|--------|---------------------|
| `total_return` | (final_equity - initial_equity) / initial_equity |
| `cagr` | (final_equity / initial_equity) ^ (365.25 / days) - 1 |
| `max_drawdown` | max(peak - trough) / peak over the entire period |
| `sharpe_ratio` | annualised(mean(daily_returns)) / annualised(std(daily_returns)) |
| `sortino_ratio` | annualised(mean(daily_returns)) / annualised(std(negative_daily_returns)) |
| `annualised_volatility` | annualised(std(daily_returns)) |
| `turnover` | sum(|position_changes|) / mean(portfolio_value) / n_days |
| `win_rate` | n_winning_trades / n_total_trades |
| `profit_factor` | sum(winning_pnl) / abs(sum(losing_pnl)) |
| `exposure` | fraction of bars with non-zero positions |
| `n_trades` | total number of round-trip trades |

**Important:** These metrics are descriptive statistics about historical simulation performance. They are not proof of future profitability, statistical significance, or live edge. Every AQCS research document must include this disclaimer.

### Reporting requirements

All metrics must be reported with the following context:
- Backtest period (start date, end date, number of days)
- Universe (instruments included)
- Fee and slippage assumptions
- Initial capital assumption

A Sharpe ratio without its assumptions is not a valid research result.

---

## J. Validation standards (future requirements)

The following validation techniques are NOT implemented in Phase 1 or Phase 2. They are defined here so that future implementations have a specification to follow.

### Walk-forward analysis

The parameter space is optimised on a rolling training window and evaluated on a forward out-of-sample window. This detects overfitting to specific market regimes.

**Requirement:** The out-of-sample window must not be used for parameter selection at any point.

### Out-of-sample testing

A portion of the data (typically the most recent 20–30%) is held out from all parameter selection and used only for final evaluation. This held-out period must be declared before any parameter search begins.

### Regime analysis

Strategy performance must be decomposed by market regime (e.g., trending, ranging, volatile, low-volatility). A strategy that only performs in one regime is not robust.

### Monte Carlo analysis

Return series from the backtest are resampled to estimate the distribution of possible outcomes and the probability that the observed performance is luck.

### Stress testing

Strategy performance must be evaluated on historical stress periods (e.g., major drawdown events, liquidity crises). Strategies that perform well on average but fail catastrophically during stress are unacceptable for capital deployment.

**These techniques are planned for Phase 3+ and are not yet implemented.**

---

## K. Explicitly prohibited in Phase 1

The following are not implemented in Phase 1 and must not be introduced without an ADR:

| Prohibited | Reason |
|-----------|--------|
| Live trading | No execution pathway exists. Phase Guard enforces this. |
| Portfolio optimisation (mean-variance, black-litterman, etc.) | Requires validated signal framework first. |
| Reinforcement learning | `Feature.REINFORCEMENT_LEARNING` is blocked by Phase Guard. Never unblocked without ADR. |
| Autonomous execution | No agent may submit orders without explicit human review. |
| Adaptive online learning | Modifies model parameters during live operation — non-deterministic, non-auditable. |
| HFT assumptions | AQCS targets daily spot research. Tick-level assumptions are out of scope indefinitely. |
| Tick-level simulation | Not supported by the data infrastructure (OHLCV only). |
| Distributed backtesting clusters | Single-process research system. Scaling is a Phase 4+ consideration. |

---

## L. Future architecture direction

The following modules are planned but not yet implemented. Their specifications are defined here to constrain future development.

### `aqcs.backtesting.engine`

**Responsibility:** Orchestrate a vectorised simulation over a historical dataset. Accepts a signal DataFrame, a position sizing function, and an execution model. Returns an equity curve and a trade log.

**Must satisfy:** All standards in §C–§H.

**Dependency:** `aqcs.utils`, `aqcs.data`, `aqcs.experiments`. May not import from `aqcs.signals`, `aqcs.portfolio`, or `aqcs.execution` directly — receives computed signals as inputs.

### `aqcs.backtesting.execution`

**Responsibility:** Model order fills given signals, prices, and an execution model (fee + slippage). Must support pluggable models for sensitivity analysis.

**Must satisfy:** §E (execution timing) and §F (fee and slippage).

### `aqcs.backtesting.metrics`

**Responsibility:** Compute the minimum required metrics (§I) from an equity curve and trade log. Must be a set of pure functions: `(equity_curve, trades) → metrics_dict`.

**Must satisfy:** Deterministic given the same inputs.

### `aqcs.backtesting.validation`

**Responsibility:** Walk-forward, OOS, regime analysis, and Monte Carlo. Not implemented until Phase 3.

**Must satisfy:** §J (validation standards) when implemented.

---

*This document is the canonical backtesting policy for AQCS. Any backtest implementation that does not satisfy every section marked "Must" is non-compliant and must not be merged to `main`.*
