"""No-lookahead tests for the merged deterministic research pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import run_pipeline

from aqcs.backtesting.engine import run_backtest
from aqcs.backtesting.models import BacktestConfig, BacktestResult
from aqcs.signals.combined import combined_momentum_trend_signal
from aqcs.signals.types import SignalDirection

_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1d"
_SIGNAL_TS = pd.Timestamp("2024-01-05", tz="UTC")
_EXECUTION_TS = pd.Timestamp("2024-01-06", tz="UTC")
_SAME_BAR_OPEN = 1_000.0
_NEXT_BAR_OPEN = 2_000.0


def _make_no_lookahead_ohlcv() -> pd.DataFrame:
    """Return a price path where same-bar execution is easy to detect."""
    timestamps = pd.date_range("2024-01-01", periods=8, freq="1D", tz="UTC")
    opens = [100.0, 100.0, 100.0, 100.0, _SAME_BAR_OPEN, _NEXT_BAR_OPEN, 2_000.0, 2_000.0]
    closes = [100.0, 100.0, 100.0, 100.0, 200.0, 200.0, 200.0, 200.0]

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": opens,
            "low": closes,
            "close": closes,
            "volume": [10.0] * len(timestamps),
            "symbol": [_SYMBOL] * len(timestamps),
            "timeframe": [_TIMEFRAME] * len(timestamps),
            "exchange": ["binance"] * len(timestamps),
        }
    )


@pytest.fixture()
def no_lookahead_parquet(tmp_path: Path) -> Path:
    path = tmp_path / "no_lookahead.parquet"
    _make_no_lookahead_ohlcv().to_parquet(path, index=False)
    return path


def _pipeline_kwargs(experiment_dir: Path) -> dict[str, Any]:
    return {
        "symbol": _SYMBOL,
        "timeframe": _TIMEFRAME,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
        "initial_capital": 10_000.0,
        "momentum_window": 1,
        "trend_short_window": 1,
        "trend_long_window": 2,
        "periods_per_year": 365,
        "experiment_dir": experiment_dir,
    }


def test_pipeline_execution_timestamps_are_after_signal_timestamps(
    no_lookahead_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_results: list[BacktestResult] = []

    def capturing_backtest(
        ohlcv: pd.DataFrame,
        signals: pd.Series,
        config: BacktestConfig,
    ) -> BacktestResult:
        result = run_backtest(ohlcv, signals, config)
        captured_results.append(result)
        return result

    monkeypatch.setattr(run_pipeline, "run_backtest", capturing_backtest)

    result = run_pipeline.run_research_pipeline(
        no_lookahead_parquet,
        **_pipeline_kwargs(tmp_path / "exp"),
    )

    backtest = captured_results[0]
    buy = next(trade for trade in backtest.trades if trade.side == "buy")
    sell = next(trade for trade in backtest.trades if trade.side == "sell")

    assert buy.timestamp > _SIGNAL_TS.to_pydatetime()
    assert sell.timestamp > _EXECUTION_TS.to_pydatetime()
    assert buy.timestamp == _EXECUTION_TS.to_pydatetime()
    assert buy.timestamp != _SIGNAL_TS.to_pydatetime()
    assert result["n_trades"] == 2


def test_signal_at_t_cannot_execute_at_t(no_lookahead_parquet: Path, tmp_path: Path) -> None:
    ohlcv = pd.read_parquet(no_lookahead_parquet)
    close = ohlcv.set_index("timestamp")["close"]
    signals = combined_momentum_trend_signal(
        close,
        momentum_window=1,
        trend_short_window=1,
        trend_long_window=2,
    )

    result = run_backtest(
        ohlcv,
        signals,
        BacktestConfig(
            initial_capital=10_000.0,
            fee_bps=0.0,
            slippage_bps=0.0,
            periods_per_year=365,
        ),
    )

    buy = next(trade for trade in result.trades if trade.side == "buy")

    assert signals.loc[_SIGNAL_TS] == SignalDirection.LONG
    # Regression trap: if the engine ever removes shift(1), this buy would
    # happen on the signal bar at 1_000.0 instead of the next bar at 2_000.0.
    assert buy.timestamp == _EXECUTION_TS.to_pydatetime()
    assert buy.fill_price == _NEXT_BAR_OPEN
    assert buy.fill_price != _SAME_BAR_OPEN


def test_pipeline_artifact_metrics_match_next_bar_trade_log(
    no_lookahead_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_results: list[BacktestResult] = []

    def capturing_backtest(
        ohlcv: pd.DataFrame,
        signals: pd.Series,
        config: BacktestConfig,
    ) -> BacktestResult:
        result = run_backtest(ohlcv, signals, config)
        captured_results.append(result)
        return result

    exp_dir = tmp_path / "exp"
    monkeypatch.setattr(run_pipeline, "run_backtest", capturing_backtest)

    pipeline_result = run_pipeline.run_research_pipeline(
        no_lookahead_parquet,
        **_pipeline_kwargs(exp_dir),
    )

    backtest = captured_results[0]
    buy = next(trade for trade in backtest.trades if trade.side == "buy")
    artifact = json.loads(next(exp_dir.rglob("experiment_*.json")).read_text(encoding="utf-8"))

    assert buy.timestamp == _EXECUTION_TS.to_pydatetime()
    assert buy.fill_price == _NEXT_BAR_OPEN
    assert artifact["metrics"] == pipeline_result["metrics"]
    assert artifact["metrics"] == {
        key: float(value) for key, value in backtest.metrics.items() if not pd.isna(float(value))
    }
