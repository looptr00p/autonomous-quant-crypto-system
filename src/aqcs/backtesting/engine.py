"""Minimal deterministic backtesting engine for AQCS Phase 1.

Timing semantics (from docs/architecture/backtesting-standards.md §E):
  Signal generated at close of bar T  →  execution at open of bar T+1.

This is enforced by shifting the signal Series by 1 before the simulation
loop. A signal at bar T can NEVER influence bar T's execution.

Phase 1 constraints (intentional, not temporary):
  - Daily bars only
  - Long-only
  - Single asset
  - Fixed position sizing (position_size_fraction of equity)
  - No leverage, no shorting, no pyramiding, no intrabar simulation
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd

from aqcs.backtesting.execution import (
    buy_fill_price,
    compute_buy_quantity,
    compute_fee,
    sell_fill_price,
)
from aqcs.backtesting.metrics import compute_metrics
from aqcs.backtesting.models import (
    BacktestConfig,
    BacktestResult,
    EquityCurvePoint,
    Trade,
)
from aqcs.backtesting.validation import validate_backtest_inputs
from aqcs.data.validator import validate_ohlcv
from aqcs.utils.events import SignalDirection
from aqcs.utils.logging import get_logger

if TYPE_CHECKING:
    from aqcs.experiments.tracker import ExperimentTracker

logger = get_logger(__name__)

_UTC = timezone.utc


def run_backtest(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    config: BacktestConfig,
    *,
    tracker: "ExperimentTracker | None" = None,
    dataset_paths: list[str] | None = None,
    experiment_name: str = "",
) -> BacktestResult:
    """Run a deterministic backtest and return a complete result.

    Args:
        ohlcv: OHLCV DataFrame with UTC timestamps. This function validates
               both structure (columns, timestamps) AND data quality (prices,
               OHLCV consistency) before simulation. Do not pass unvalidated data.
        signals: Series of SignalDirection values indexed by UTC timestamp.
                 Aligned to OHLCV timestamps. Signal at T executes at T+1 open.
        config: BacktestConfig specifying capital, fees, slippage, dates.
        tracker: Optional ExperimentTracker. If provided, creates an
                 ExperimentRecord before simulation and updates it after.
        dataset_paths: Optional file paths for dataset fingerprinting.
        experiment_name: Name for the ExperimentRecord (if tracker provided).

    Returns:
        BacktestResult with equity curve, trade log, metrics, and experiment ID.

    Raises:
        ValueError: If OHLCV data fails structural or quality validation,
                    or if the date range contains no bars.
    """
    # ── 1. Structural validation (columns, timestamps, overlap) ───────────────
    validate_backtest_inputs(ohlcv, signals, config)

    # ── 2. OHLCV data quality validation ─────────────────────────────────────
    # Extract symbol and timeframe from data for the validator.
    symbol = str(ohlcv["symbol"].iloc[0]) if "symbol" in ohlcv.columns else ""
    timeframe = str(ohlcv["timeframe"].iloc[0]) if "timeframe" in ohlcv.columns else "1d"
    quality_result = validate_ohlcv(ohlcv, symbol, timeframe)
    if not quality_result.is_valid:
        raise ValueError(
            "OHLCV data failed quality validation. "
            "Fix the data before backtesting:\n"
            + "\n".join(f"  • {e}" for e in quality_result.errors)
        )
    if quality_result.has_warnings:
        for w in quality_result.warnings:
            logger.warning("ohlcv_quality_warning", warning=w, symbol=symbol)

    # ── 3. Date filtering ─────────────────────────────────────────────────────
    ohlcv_indexed = ohlcv.set_index("timestamp").sort_index()

    if config.start_date:
        start = pd.Timestamp(config.start_date, tz="UTC")
        ohlcv_indexed = ohlcv_indexed[ohlcv_indexed.index >= start]

    if config.end_date:
        end = pd.Timestamp(config.end_date, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        ohlcv_indexed = ohlcv_indexed[ohlcv_indexed.index <= end]

    if ohlcv_indexed.empty:
        raise ValueError(
            f"No OHLCV bars in date range "
            f"[{config.start_date or 'start'}, {config.end_date or 'end'}]"
        )

    # ── 4. Signal alignment and shift ────────────────────────────────────────
    # .shift(1) enforces next-bar execution:
    #   shifted[T] = signals[T-1] = the signal to ACT ON at bar T.
    signal_aligned = signals.reindex(ohlcv_indexed.index)
    shifted = signal_aligned.shift(1)

    # ── 5. Experiment tracking setup ─────────────────────────────────────────
    experiment_id = ""
    record = None
    if tracker is not None:
        try:
            _name = experiment_name or f"backtest_{config.start_date or 'all'}_{config.end_date or 'all'}"
            record = tracker.create_experiment(
                _name,
                experiment_type="backtest",
                parameters={
                    "initial_capital": config.initial_capital,
                    "fee_bps": config.fee_bps,
                    "slippage_bps": config.slippage_bps,
                    "position_size_fraction": config.position_size_fraction,
                    "allow_fractional": config.allow_fractional,
                    "start_date": config.start_date,
                    "end_date": config.end_date,
                    "periods_per_year": config.periods_per_year,
                    "n_bars": len(ohlcv_indexed),
                },
                dataset_paths=dataset_paths or [],
            )
            experiment_id = str(record.experiment_id)
        except Exception as exc:
            logger.warning("experiment_tracking_failed", error=str(exc))

    try:
        result = _simulate(ohlcv_indexed, shifted, config, experiment_id)
    except Exception as exc:
        if tracker is not None and record is not None:
            try:
                tracker.fail_experiment(record.experiment_id, reason=str(exc))
            except Exception:
                pass
        raise

    if tracker is not None and record is not None:
        try:
            tracker.complete_experiment(
                record.experiment_id,
                metrics={k: float(v) for k, v in result.metrics.items() if not _is_nan(v)},
            )
        except Exception as exc:
            logger.warning("experiment_complete_failed", error=str(exc))

    return result


def _is_nan(v: object) -> bool:
    try:
        return math.isnan(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _simulate(
    ohlcv: pd.DataFrame,
    shifted_signals: pd.Series,
    config: BacktestConfig,
    experiment_id: str,
) -> BacktestResult:
    """Core simulation loop — deterministic, no external calls."""
    cash = float(config.initial_capital)
    position = 0.0
    trades: list[Trade] = []
    equity_curve: list[EquityCurvePoint] = []

    for ts, row in ohlcv.iterrows():
        open_price = float(row["open"])
        close_price = float(row["close"])
        exec_signal = shifted_signals.get(ts)

        # ── Execute based on previous bar's signal ────────────────────────────
        if _is_long(exec_signal) and position == 0.0:
            fill = buy_fill_price(open_price, config)
            qty = compute_buy_quantity(cash, fill, config)
            if qty > 0:
                value = qty * fill
                fee = compute_fee(value, config)
                slippage_cost = abs(fill - open_price) * qty
                cost = value + fee
                if cost <= cash:
                    cash -= cost
                    position = qty
                    trades.append(Trade(
                        timestamp=_to_dt(ts),
                        side="buy",
                        fill_price=fill,
                        quantity=qty,
                        fee=fee,
                        slippage_amount=slippage_cost,
                        value=value,
                    ))

        elif not _is_long(exec_signal) and position > 0.0:
            fill = sell_fill_price(open_price, config)
            value = position * fill
            fee = compute_fee(value, config)
            slippage_cost = abs(open_price - fill) * position
            proceeds = value - fee
            cash += proceeds
            trades.append(Trade(
                timestamp=_to_dt(ts),
                side="sell",
                fill_price=fill,
                quantity=position,
                fee=fee,
                slippage_amount=slippage_cost,
                value=value,
            ))
            position = 0.0

        # ── Mark-to-market at bar close ───────────────────────────────────────
        equity = cash + position * close_price
        equity_curve.append(EquityCurvePoint(
            timestamp=_to_dt(ts),
            equity=equity,
            cash=cash,
            position=position,
            price=close_price,
        ))

    metrics = compute_metrics(
        tuple(equity_curve),
        tuple(trades),
        periods_per_year=config.periods_per_year,
    )

    logger.info(
        "backtest_complete",
        n_bars=len(ohlcv),
        n_trades=len([t for t in trades if t.side == "buy"]),
        total_return=metrics.get("total_return"),
        experiment_id=experiment_id,
    )

    return BacktestResult(
        config=config,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        metrics=metrics,
        n_bars=len(ohlcv),
        experiment_id=experiment_id,
    )


def _is_long(signal: object) -> bool:
    return signal == SignalDirection.LONG


def _to_dt(ts: object) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=_UTC)
    return pd.Timestamp(ts).to_pydatetime()
