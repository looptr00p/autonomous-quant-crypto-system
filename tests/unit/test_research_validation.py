"""Tests for deterministic research validation runner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from aqcs.experiments.models import ExperimentStatus
from aqcs.research import ResearchValidationConfig, run_research_validation


def _make_ohlcv(n: int = 90) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    closes = [100.0 + i * 0.4 + (2.0 if i > 45 else 0.0) for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [close - 0.2 for close in closes],
            "high": [close + 1.0 for close in closes],
            "low": [close - 1.0 for close in closes],
            "close": closes,
            "volume": [1000.0 + i for i in range(n)],
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "exchange": "binance",
        }
    )


def _write_parquet(tmp_path: Path, df: pd.DataFrame) -> Path:
    path = tmp_path / "BTC_USDT_1d.parquet"
    df.to_parquet(path, index=False)
    return path


def _config(tmp_path: Path, parquet_path: Path) -> ResearchValidationConfig:
    return ResearchValidationConfig(
        parquet_path=parquet_path,
        experiment_storage_dir=tmp_path / "experiments",
        artifact_dir=tmp_path / "artifacts",
        experiment_name="unit_research_validation",
        initial_capital=10_000.0,
        fee_bps=10.0,
        slippage_bps=5.0,
        momentum_window=5,
        trend_short_window=3,
        trend_long_window=8,
    )


def test_research_validation_loads_parquet_and_validates_ohlcv(tmp_path: Path) -> None:
    parquet_path = _write_parquet(tmp_path, _make_ohlcv())

    result = run_research_validation(_config(tmp_path, parquet_path))

    assert result.backtest.n_bars == 90
    assert result.experiment.status == ExperimentStatus.COMPLETED
    assert result.experiment.parameters["row_count"] == 90
    assert result.experiment.parameters["symbol"] == "BTC/USDT"


def test_research_validation_rejects_invalid_ohlcv(tmp_path: Path) -> None:
    df = _make_ohlcv()
    df.loc[3, "close"] = 0.0
    parquet_path = _write_parquet(tmp_path, df)

    with pytest.raises(ValueError, match="failed OHLCV validation"):
        run_research_validation(_config(tmp_path, parquet_path))


def test_research_validation_halts_on_gap_warning_by_default(tmp_path: Path) -> None:
    df = _make_ohlcv().drop(index=10).reset_index(drop=True)
    parquet_path = _write_parquet(tmp_path, df)

    with pytest.raises(ValueError, match="halted because OHLCV validation produced warnings"):
        run_research_validation(_config(tmp_path, parquet_path))


def test_research_validation_persists_artifacts_and_experiment_metadata(
    tmp_path: Path,
) -> None:
    parquet_path = _write_parquet(tmp_path, _make_ohlcv())

    result = run_research_validation(_config(tmp_path, parquet_path))

    assert len(result.artifacts) == 4
    for path in result.artifacts:
        assert path.exists()
    assert result.experiment.artifacts == [str(path) for path in result.artifacts]
    assert result.experiment.dataset_paths == [str(parquet_path)]
    assert result.experiment.dataset_fingerprint
    assert result.experiment.parameters["gap_policy"] == "halt"
    assert result.experiment.parameters["backtest"]["fee_bps"] == 10.0
    assert (
        result.experiment.parameters["backtest"]["execution_timing"]
        == "signal_t_executes_at_t_plus_1_open"
    )


def test_research_validation_metrics_json_is_strict_json(tmp_path: Path) -> None:
    parquet_path = _write_parquet(tmp_path, _make_ohlcv())

    result = run_research_validation(_config(tmp_path, parquet_path))
    metrics_path = next(path for path in result.artifacts if path.name == "metrics.json")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

    assert set(result.backtest.metrics).issubset(metrics)


def test_research_validation_runs_backtest_with_next_bar_execution(tmp_path: Path) -> None:
    parquet_path = _write_parquet(tmp_path, _make_ohlcv())

    result = run_research_validation(_config(tmp_path, parquet_path))
    if result.backtest.trades:
        first_trade = result.backtest.trades[0]
        signal_artifact = next(path for path in result.artifacts if path.name == "signals.parquet")
        signals = pd.read_parquet(signal_artifact)
        first_long = signals[signals["signal"] == "long"].iloc[0]["timestamp"]
        assert pd.Timestamp(first_trade.timestamp) > pd.Timestamp(first_long)


def test_repeated_research_validation_produces_identical_outputs(tmp_path: Path) -> None:
    parquet_path = _write_parquet(tmp_path, _make_ohlcv())

    first = run_research_validation(_config(tmp_path / "a", parquet_path))
    second = run_research_validation(_config(tmp_path / "b", parquet_path))

    assert first.backtest.metrics == second.backtest.metrics
    assert first.backtest.trades == second.backtest.trades
    assert first.backtest.equity_curve == second.backtest.equity_curve


def test_research_validation_does_not_call_ohlcv_downloader(tmp_path: Path) -> None:
    parquet_path = _write_parquet(tmp_path, _make_ohlcv())

    with (
        patch("aqcs.data.ohlcv.fetch_ohlcv") as mock_fetch,
        patch("aqcs.data.ohlcv._build_exchange") as mock_exchange,
    ):
        run_research_validation(_config(tmp_path, parquet_path))

    mock_fetch.assert_not_called()
    mock_exchange.assert_not_called()
