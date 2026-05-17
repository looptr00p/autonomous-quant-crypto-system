"""End-to-end deterministic research pipeline for AQCS.

Sequence:
  load parquet → validate (UTC timestamps, schema, OHLCV consistency)
  → compute features → generate signal
  → run backtest (next-bar execution, fees, slippage enforced inside engine)
  → persist experiment artifact

Research only. No orders are submitted. No live data is used.
A successful run must NOT be interpreted as alpha, profitability, robustness,
tradability, or production readiness.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import click
import pandas as pd

from aqcs.backtesting.engine import run_backtest
from aqcs.backtesting.models import BacktestConfig
from aqcs.data.validator import validate_ohlcv
from aqcs.experiments.tracker import ExperimentTracker
from aqcs.features.returns import log_return
from aqcs.features.trend import distance_from_moving_average, simple_moving_average
from aqcs.features.volatility import rolling_volatility
from aqcs.signals.combined import combined_momentum_trend_signal
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)


def _last_valid(series: pd.Series) -> float | None:
    valid = series.dropna()
    return float(valid.iloc[-1]) if not valid.empty else None


def run_research_pipeline(
    parquet_path: Path,
    symbol: str,
    timeframe: str,
    *,
    initial_capital: float = 10_000.0,
    fee_bps: float,
    slippage_bps: float,
    momentum_window: int = 20,
    trend_short_window: int = 10,
    trend_long_window: int = 50,
    start_date: str = "",
    end_date: str = "",
    experiment_dir: Path | None = None,
    experiment_name: str = "",
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """Run the end-to-end research pipeline and return a results summary.

    Args:
        parquet_path: Path to a valid OHLCV Parquet file produced by aqcs.data.ohlcv.
        symbol: Market symbol expected in the data (e.g. "BTC/USDT").
        timeframe: Candle timeframe expected in the data (e.g. "1d").
        initial_capital: Starting capital in quote currency. Must be > 0.
        fee_bps: Taker fee in basis points (e.g. 10 = 0.10%). Required — no silent zero.
        slippage_bps: Half-spread slippage in bps per side. Required — no silent zero.
        momentum_window: Lookback N for the rolling N-period return in the momentum signal.
        trend_short_window: Fast MA window for the trend-filter signal.
        trend_long_window: Slow MA window for the trend-filter signal.
        start_date: Backtest start date YYYY-MM-DD (empty = use all data).
        end_date: Backtest end date YYYY-MM-DD, inclusive (empty = use all data).
        experiment_dir: Directory for JSON experiment artifact persistence.
                        Defaults to ``experiments/`` relative to cwd.
        experiment_name: Human-readable name stored in the experiment record.
        periods_per_year: Annualisation factor (252 daily, 8760 hourly).

    Returns:
        Dict containing:
            experiment_id  — UUID of the persisted experiment artifact
            metrics        — dict of backtest metrics (NaN values excluded)
            n_bars         — number of bars in the backtest date range
            n_trades       — total filled trades (buys + sells)
            signal_counts  — per-direction bar counts for the full signal series
            feature_summary — last valid value of each computed feature

    Raises:
        ValueError: Data fails validation, or the backtest cannot run
                    (e.g. no bars in the requested date range).
    """
    _dir = Path(experiment_dir) if experiment_dir is not None else Path("experiments")

    # ── 1. Load ───────────────────────────────────────────────────────────────
    logger.info("pipeline_step", step="load", path=str(parquet_path))
    ohlcv = pd.read_parquet(parquet_path)

    # ── 2. Validate (UTC-aware timestamps, monotonic, no duplicates, schema) ──
    logger.info("pipeline_step", step="validate", rows=len(ohlcv))
    vresult = validate_ohlcv(ohlcv, symbol, timeframe)
    if not vresult.is_valid:
        raise ValueError(
            "OHLCV validation failed — fix data before running pipeline:\n"
            + "\n".join(f"  • {e}" for e in vresult.errors)
        )
    for w in vresult.warnings:
        logger.warning("pipeline_data_warning", warning=w)

    # ── 3. Features (computed on full history — date filter applied later) ────
    #
    # Signals are generated from the full price series so that warm-up bars
    # fall before the backtest start date, not within the simulation window.
    # The engine applies start_date / end_date filtering after receiving the
    # full signal series.
    logger.info("pipeline_step", step="features")
    close = ohlcv.set_index("timestamp")["close"]

    log_rets = log_return(close)
    vol = rolling_volatility(log_rets, window=momentum_window, periods_per_year=periods_per_year)
    sma_short = simple_moving_average(close, trend_short_window)
    sma_long = simple_moving_average(close, trend_long_window)
    dist_ma = distance_from_moving_average(close, trend_long_window)

    feature_summary: dict[str, float | None] = {
        "rolling_vol_last": _last_valid(vol),
        "sma_short_last": _last_valid(sma_short),
        "sma_long_last": _last_valid(sma_long),
        "dist_from_ma_last": _last_valid(dist_ma),
    }

    # ── 4. Signal ─────────────────────────────────────────────────────────────
    logger.info("pipeline_step", step="signal")
    signals = combined_momentum_trend_signal(
        close,
        momentum_window,
        trend_short_window,
        trend_long_window,
    )
    signal_counts: dict[str, int] = {str(k): int(v) for k, v in signals.value_counts().items()}

    # ── 5. Experiment artifact (created before backtest — captures all config) ─
    _dir.mkdir(parents=True, exist_ok=True)
    tracker = ExperimentTracker(_dir)

    _name = experiment_name or f"{symbol.replace('/', '_')}_{timeframe}_momentum_trend"
    parameters: dict[str, Any] = {
        # Backtest config
        "initial_capital": initial_capital,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "start_date": start_date,
        "end_date": end_date,
        "periods_per_year": periods_per_year,
        # Feature config
        "feature.log_return": True,
        "feature.rolling_volatility_window": momentum_window,
        "feature.sma_short_window": trend_short_window,
        "feature.sma_long_window": trend_long_window,
        "feature.distance_from_ma_window": trend_long_window,
        # Signal config
        "signal.type": "combined_momentum_trend",
        "signal.momentum_window": momentum_window,
        "signal.trend_short_window": trend_short_window,
        "signal.trend_long_window": trend_long_window,
        "signal.momentum_long_quantile": 0.7,
        "signal.momentum_short_quantile": 0.3,
        # Data provenance
        "symbol": symbol,
        "timeframe": timeframe,
        "n_bars_loaded": len(ohlcv),
    }

    record = tracker.create_experiment(
        _name,
        experiment_type="research",
        parameters=parameters,
        dataset_paths=[str(parquet_path)],
    )

    # ── 6. Backtest ───────────────────────────────────────────────────────────
    # next-bar execution:  signal[T] → execution at open[T+1]  (enforced by
    # shift(1) inside run_backtest — not configurable from here)
    logger.info("pipeline_step", step="backtest")
    config = BacktestConfig(
        initial_capital=initial_capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        start_date=start_date,
        end_date=end_date,
        periods_per_year=periods_per_year,
    )

    try:
        bt_result = run_backtest(ohlcv, signals, config)
    except Exception as exc:
        tracker.fail_experiment(record.experiment_id, reason=str(exc))
        raise

    # ── 7. Persist metrics in experiment artifact ─────────────────────────────
    # Exclude NaN values — JSON does not support NaN.
    clean_metrics = {k: float(v) for k, v in bt_result.metrics.items() if not math.isnan(float(v))}
    tracker.complete_experiment(record.experiment_id, metrics=clean_metrics)

    logger.info(
        "pipeline_complete",
        experiment_id=str(record.experiment_id),
        n_bars=bt_result.n_bars,
        n_trades=len(bt_result.trades),
        metrics=clean_metrics,
    )

    return {
        "experiment_id": str(record.experiment_id),
        "metrics": clean_metrics,
        "n_bars": bt_result.n_bars,
        "n_trades": len(bt_result.trades),
        "signal_counts": signal_counts,
        "feature_summary": feature_summary,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--parquet",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to OHLCV Parquet file.",
)
@click.option("--symbol", required=True, help='Market symbol (e.g. "BTC/USDT").')
@click.option("--timeframe", required=True, help='Candle timeframe (e.g. "1d").')
@click.option("--initial-capital", default=10_000.0, show_default=True, help="Starting capital.")
@click.option(
    "--fee-bps", required=True, type=float, help="Taker fee in basis points (e.g. 10 = 0.10%)."
)
@click.option(
    "--slippage-bps", required=True, type=float, help="Slippage in basis points per side."
)
@click.option(
    "--momentum-window", default=20, show_default=True, help="Momentum lookback window (bars)."
)
@click.option("--trend-short", default=10, show_default=True, help="Fast MA window (bars).")
@click.option("--trend-long", default=50, show_default=True, help="Slow MA window (bars).")
@click.option("--start-date", default="", help="Backtest start YYYY-MM-DD (default: all data).")
@click.option("--end-date", default="", help="Backtest end YYYY-MM-DD (default: all data).")
@click.option(
    "--experiment-dir",
    default="experiments",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Experiment artifact directory.",
)
@click.option("--experiment-name", default="", help="Name for the experiment record.")
@click.option(
    "--periods-per-year",
    default=252,
    show_default=True,
    help="Annualisation factor (252 daily, 8760 hourly).",
)
def main(
    parquet: Path,
    symbol: str,
    timeframe: str,
    initial_capital: float,
    fee_bps: float,
    slippage_bps: float,
    momentum_window: int,
    trend_short: int,
    trend_long: int,
    start_date: str,
    end_date: str,
    experiment_dir: Path,
    experiment_name: str,
    periods_per_year: int,
) -> None:
    """Run the AQCS end-to-end research pipeline.

    Loads an OHLCV Parquet file, validates data quality, computes
    momentum-trend features and signals, runs a deterministic backtest,
    and persists a fully-auditable experiment artifact.

    This is a research tool only. No orders are submitted.
    """
    try:
        result = run_research_pipeline(
            parquet,
            symbol,
            timeframe,
            initial_capital=initial_capital,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            momentum_window=momentum_window,
            trend_short_window=trend_short,
            trend_long_window=trend_long,
            start_date=start_date,
            end_date=end_date,
            experiment_dir=experiment_dir,
            experiment_name=experiment_name,
            periods_per_year=periods_per_year,
        )
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    click.echo(f"\nExperiment  : {result['experiment_id']}")
    click.echo(f"Bars        : {result['n_bars']}")
    click.echo(f"Trades      : {result['n_trades']}")
    click.echo("\nMetrics:")
    for k, v in sorted(result["metrics"].items()):
        click.echo(f"  {k:<30} {v:.6f}")
    click.echo("\nSignal distribution:")
    for k, v in sorted(result["signal_counts"].items()):
        click.echo(f"  {k:<12} {v} bars")


if __name__ == "__main__":
    main()
