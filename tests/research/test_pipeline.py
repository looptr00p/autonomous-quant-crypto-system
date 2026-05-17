"""Integration tests for the end-to-end research pipeline.

These tests verify the pipeline contract:
- Valid data flows through load → validate → features → signal → backtest → artifact.
- Invalid data (non-UTC, non-monotonic, duplicate timestamps) is rejected before
  the backtest runs.
- The experiment artifact is persisted with the expected structure.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from run_pipeline import run_research_pipeline  # injected by tests/research/conftest.py

# ── Fixtures ──────────────────────────────────────────────────────────────────

_N = 300  # bars — enough warmup for momentum_window=20 and trend_long_window=50
_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1d"

_REQUIRED_METRIC_KEYS = {
    "total_return",
    "cagr",
    "max_drawdown",
    "sharpe_ratio",
    "annualised_volatility",
    "trade_count",
    "win_rate",
    "exposure",
}


def _make_valid_ohlcv(n: int = _N) -> pd.DataFrame:
    """Return a minimal, schema-valid OHLCV DataFrame with UTC timestamps."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2023-01-01", periods=n, freq="1D", tz="UTC")

    # Deterministic random walk — always positive (seed ensures reproducibility)
    prices = 40_000.0 + np.cumsum(rng.normal(0, 200.0, n))
    prices = np.maximum(prices, 1_000.0)

    opens = prices * (1.0 + rng.uniform(-0.003, 0.003, n))
    highs = np.maximum(prices, opens) * (1.0 + rng.uniform(0.0, 0.005, n))
    lows = np.minimum(prices, opens) * (1.0 - rng.uniform(0.0, 0.005, n))
    lows = np.maximum(lows, 1.0)

    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": rng.uniform(100.0, 500.0, n),
            "symbol": _SYMBOL,
            "timeframe": _TIMEFRAME,
            "exchange": "binance",
        }
    )


@pytest.fixture()
def valid_parquet(tmp_path: Path) -> Path:
    path = tmp_path / "BTC_USDT_1d.parquet"
    _make_valid_ohlcv().to_parquet(path, index=False)
    return path


@pytest.fixture()
def pipeline_defaults() -> dict:
    return {
        "symbol": _SYMBOL,
        "timeframe": _TIMEFRAME,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
        "initial_capital": 10_000.0,
        "momentum_window": 20,
        "trend_short_window": 10,
        "trend_long_window": 50,
        "periods_per_year": 365,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPipelineSuccess:
    def test_returns_required_keys(self, valid_parquet, pipeline_defaults, tmp_path):
        result = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp"
        )
        assert "experiment_id" in result
        assert "metrics" in result
        assert "n_bars" in result
        assert "n_trades" in result
        assert "signal_counts" in result
        assert "feature_summary" in result

    def test_metrics_contain_required_keys(self, valid_parquet, pipeline_defaults, tmp_path):
        result = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp"
        )
        missing = _REQUIRED_METRIC_KEYS - result["metrics"].keys()
        assert not missing, f"Missing metric keys: {missing}"

    def test_n_bars_positive(self, valid_parquet, pipeline_defaults, tmp_path):
        result = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp"
        )
        assert result["n_bars"] > 0

    def test_experiment_artifact_persisted(self, valid_parquet, pipeline_defaults, tmp_path):
        exp_dir = tmp_path / "exp"
        result = run_research_pipeline(valid_parquet, **pipeline_defaults, experiment_dir=exp_dir)
        artifacts = list(exp_dir.rglob("experiment_*.json"))
        assert artifacts, "No experiment JSON artifact was written"

        data = json.loads(artifacts[0].read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert data["experiment_id"] == result["experiment_id"]
        assert data["parameters"]["signal.type"] == "combined_momentum_trend"
        assert data["parameters"]["fee_bps"] == pipeline_defaults["fee_bps"]
        assert data["parameters"]["slippage_bps"] == pipeline_defaults["slippage_bps"]
        assert "git_commit_hash" in data
        assert "dataset_fingerprint" in data

    def test_artifact_metrics_match_return_value(self, valid_parquet, pipeline_defaults, tmp_path):
        exp_dir = tmp_path / "exp"
        result = run_research_pipeline(valid_parquet, **pipeline_defaults, experiment_dir=exp_dir)
        artifact = json.loads(next(exp_dir.rglob("experiment_*.json")).read_text())
        assert artifact["metrics"] == result["metrics"]

    def test_deterministic_across_runs(self, valid_parquet, pipeline_defaults, tmp_path):
        r1 = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp1"
        )
        r2 = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp2"
        )
        assert r1["metrics"] == r2["metrics"]
        assert r1["n_bars"] == r2["n_bars"]
        assert r1["n_trades"] == r2["n_trades"]

    def test_signal_counts_cover_all_bars(self, valid_parquet, pipeline_defaults, tmp_path):
        result = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp"
        )
        # Signal series spans the full _N bars; backtest may use a subset.
        total = sum(result["signal_counts"].values())
        assert total == _N

    def test_feature_summary_populated(self, valid_parquet, pipeline_defaults, tmp_path):
        result = run_research_pipeline(
            valid_parquet, **pipeline_defaults, experiment_dir=tmp_path / "exp"
        )
        fs = result["feature_summary"]
        assert fs["rolling_vol_last"] is not None
        assert fs["sma_short_last"] is not None
        assert fs["sma_long_last"] is not None
        assert fs["dist_from_ma_last"] is not None


class TestPipelineValidationRejections:
    """Pipeline must reject invalid data before the backtest runs."""

    def test_rejects_naive_timestamps(self, tmp_path, pipeline_defaults):
        df = _make_valid_ohlcv()
        df["timestamp"] = pd.date_range("2023-01-01", periods=_N, freq="1D")  # no tz
        path = tmp_path / "naive.parquet"
        df.to_parquet(path, index=False)

        with pytest.raises(ValueError, match="validation failed"):
            run_research_pipeline(path, **pipeline_defaults, experiment_dir=tmp_path / "exp")

    def test_rejects_non_monotonic_timestamps(self, tmp_path, pipeline_defaults):
        df = _make_valid_ohlcv()
        # Shuffle timestamps so they are no longer monotonically increasing.
        shuffled = df["timestamp"].sample(frac=1, random_state=99).reset_index(drop=True)
        df = df.copy()
        df["timestamp"] = shuffled
        path = tmp_path / "shuffled.parquet"
        df.to_parquet(path, index=False)

        with pytest.raises(ValueError, match="validation failed"):
            run_research_pipeline(path, **pipeline_defaults, experiment_dir=tmp_path / "exp")

    def test_rejects_duplicate_timestamps(self, tmp_path, pipeline_defaults):
        df = _make_valid_ohlcv()
        dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        path = tmp_path / "duplicate.parquet"
        dup.to_parquet(path, index=False)

        with pytest.raises(ValueError, match="validation failed"):
            run_research_pipeline(path, **pipeline_defaults, experiment_dir=tmp_path / "exp")
