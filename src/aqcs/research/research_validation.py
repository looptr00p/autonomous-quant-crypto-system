"""Minimal deterministic research validation runner.

This module wires existing AQCS components together for one local, reproducible
research validation run:

local Parquet -> OHLCV validation -> deterministic signal -> next-bar backtest
-> experiment record + artifacts.

It does not fetch data, optimize parameters, submit orders, or validate alpha.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from aqcs.backtesting import BacktestConfig, BacktestResult, run_backtest
from aqcs.data.validator import validate_ohlcv
from aqcs.experiments import ExperimentTracker
from aqcs.experiments.models import ExperimentRecord
from aqcs.signals.combined import combined_momentum_trend_signal


@dataclass(frozen=True)
class ResearchValidationConfig:
    """Explicit parameters for one deterministic validation run."""

    parquet_path: Path
    experiment_storage_dir: Path
    artifact_dir: Path
    experiment_name: str
    initial_capital: float
    fee_bps: float
    slippage_bps: float
    position_size_fraction: float = 1.0
    momentum_window: int = 20
    trend_short_window: int = 20
    trend_long_window: int = 50
    momentum_long_quantile: float = 0.7
    momentum_short_quantile: float = 0.3
    periods_per_year: int = 252
    start_date: str = ""
    end_date: str = ""
    config_path: str = ""
    gap_policy: str = "halt"


@dataclass(frozen=True)
class ResearchValidationResult:
    """Returned summary for a completed research validation run."""

    experiment: ExperimentRecord
    backtest: BacktestResult
    artifacts: tuple[Path, ...]


def run_research_validation(config: ResearchValidationConfig) -> ResearchValidationResult:
    """Run a deterministic local research validation and persist audit artifacts."""
    _validate_runner_config(config)

    parquet_path = config.parquet_path
    if not parquet_path.is_file():
        raise FileNotFoundError(f"Parquet input not found: {parquet_path}")

    ohlcv = pd.read_parquet(parquet_path)
    symbol, timeframe = _extract_symbol_timeframe(ohlcv)
    validation = validate_ohlcv(
        ohlcv,
        symbol,
        timeframe,
        component="aqcs.research.research_validation",
    )
    if not validation.is_valid:
        raise ValueError(
            "Research validation input failed OHLCV validation:\n"
            + "\n".join(f"  - {error}" for error in validation.errors)
        )
    if validation.has_warnings and config.gap_policy == "halt":
        raise ValueError(
            "Research validation halted because OHLCV validation produced warnings:\n"
            + "\n".join(f"  - {warning}" for warning in validation.warnings)
        )

    ohlcv = ohlcv.sort_values("timestamp").reset_index(drop=True)
    prices = pd.Series(ohlcv["close"].to_numpy(), index=ohlcv["timestamp"], name="close")
    signals = combined_momentum_trend_signal(
        prices,
        config.momentum_window,
        config.trend_short_window,
        config.trend_long_window,
        momentum_long_quantile=config.momentum_long_quantile,
        momentum_short_quantile=config.momentum_short_quantile,
    )

    backtest_config = BacktestConfig(
        initial_capital=config.initial_capital,
        fee_bps=config.fee_bps,
        slippage_bps=config.slippage_bps,
        position_size_fraction=config.position_size_fraction,
        start_date=config.start_date,
        end_date=config.end_date,
        periods_per_year=config.periods_per_year,
    )

    tracker = ExperimentTracker(storage_dir=config.experiment_storage_dir)
    record = tracker.create_experiment(
        config.experiment_name,
        experiment_type="research_validation",
        parameters=_parameters(config, validation.row_count, symbol, timeframe),
        config_path=config.config_path,
        dataset_paths=[str(parquet_path)],
        dataset_root=parquet_path.parent,
        tags=["research-validation", "deterministic"],
        notes=(
            "Deterministic research execution validation only. "
            "This record does not validate alpha, profitability, tradability, "
            "paper trading, or live trading readiness."
        ),
    )

    try:
        backtest = run_backtest(ohlcv, signals, backtest_config)
        artifacts = _persist_artifacts(
            backtest,
            signals,
            config.artifact_dir,
            str(record.experiment_id),
        )
        completed = tracker.complete_experiment(
            record.experiment_id,
            metrics={k: float(v) for k, v in backtest.metrics.items() if pd.notna(v)},
            artifacts=[str(path) for path in artifacts],
        )
    except Exception as exc:
        tracker.fail_experiment(record.experiment_id, reason=str(exc))
        raise

    return ResearchValidationResult(
        experiment=completed,
        backtest=backtest,
        artifacts=artifacts,
    )


def _validate_runner_config(config: ResearchValidationConfig) -> None:
    if config.gap_policy != "halt":
        raise ValueError("Only gap_policy='halt' is supported in this validation runner")
    if config.momentum_window <= 0:
        raise ValueError("momentum_window must be positive")
    if config.trend_short_window <= 0:
        raise ValueError("trend_short_window must be positive")
    if config.trend_long_window <= config.trend_short_window:
        raise ValueError("trend_long_window must be greater than trend_short_window")


def _extract_symbol_timeframe(ohlcv: pd.DataFrame) -> tuple[str, str]:
    if "symbol" not in ohlcv.columns or "timeframe" not in ohlcv.columns:
        return "", ""
    return str(ohlcv["symbol"].iloc[0]), str(ohlcv["timeframe"].iloc[0])


def _parameters(
    config: ResearchValidationConfig,
    row_count: int,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    return {
        "purpose": "deterministic_research_execution_validation",
        "parquet_path": str(config.parquet_path),
        "symbol": symbol,
        "timeframe": timeframe,
        "row_count": row_count,
        "gap_policy": config.gap_policy,
        "signal": {
            "name": "combined_momentum_trend_signal",
            "momentum_window": config.momentum_window,
            "trend_short_window": config.trend_short_window,
            "trend_long_window": config.trend_long_window,
            "momentum_long_quantile": config.momentum_long_quantile,
            "momentum_short_quantile": config.momentum_short_quantile,
        },
        "backtest": {
            "initial_capital": config.initial_capital,
            "fee_bps": config.fee_bps,
            "slippage_bps": config.slippage_bps,
            "position_size_fraction": config.position_size_fraction,
            "start_date": config.start_date,
            "end_date": config.end_date,
            "periods_per_year": config.periods_per_year,
            "execution_timing": "signal_t_executes_at_t_plus_1_open",
        },
    }


def _persist_artifacts(
    backtest: BacktestResult,
    signals: pd.Series,
    artifact_dir: Path,
    experiment_id: str,
) -> tuple[Path, ...]:
    run_dir = artifact_dir / experiment_id
    run_dir.mkdir(parents=True, exist_ok=True)

    equity_path = run_dir / "equity_curve.parquet"
    trades_path = run_dir / "trades.parquet"
    signals_path = run_dir / "signals.parquet"
    metrics_path = run_dir / "metrics.json"

    _equity_frame(backtest).to_parquet(equity_path, index=False)
    _trades_frame(backtest).to_parquet(trades_path, index=False)
    _signals_frame(signals).to_parquet(signals_path, index=False)
    metrics_path.write_text(
        json.dumps(
            {key: _json_metric_value(value) for key, value in backtest.metrics.items()},
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    return (equity_path, trades_path, signals_path, metrics_path)


def _equity_frame(backtest: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": point.timestamp,
                "equity": point.equity,
                "cash": point.cash,
                "position": point.position,
                "price": point.price,
            }
            for point in backtest.equity_curve
        ]
    )


def _trades_frame(backtest: BacktestResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": trade.timestamp,
                "side": trade.side,
                "fill_price": trade.fill_price,
                "quantity": trade.quantity,
                "fee": trade.fee,
                "slippage_amount": trade.slippage_amount,
                "value": trade.value,
            }
            for trade in backtest.trades
        ],
        columns=[
            "timestamp",
            "side",
            "fill_price",
            "quantity",
            "fee",
            "slippage_amount",
            "value",
        ],
    )


def _signals_frame(signals: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": signals.index,
            "signal": [str(value.value) for value in signals],
        }
    )


def _json_metric_value(value: float) -> float | None:
    return None if not math.isfinite(float(value)) else float(value)
