"""Execute a deterministic walk-forward validation on a local OHLCV dataset.

Loads a Parquet file, validates it, generates temporal windows, runs
the AQCS combined signal pipeline on each window's test period, and
writes a deterministic walk-forward report JSON.

Exit codes:
  0  — walk-forward completed; all windows evaluated; report is valid
  1  — completed with issues (failed windows or leakage detected)
  2  — invalid CLI arguments or dataset cannot be read

Manual command:
  PYTHONPATH=src python scripts/research/run_walkforward.py \\
    --dataset data/burn_in/BTC_USDT_1h.parquet \\
    --train-bars 500 \\
    --test-bars 100 \\
    --step-bars 100 \\
    --output-json reports/walkforward_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import pandas as pd

from aqcs.backtesting.models import BacktestConfig
from aqcs.data.validator import validate_ohlcv
from aqcs.research.walkforward import (
    run_walkforward,
    save_report,
)


@click.command()
@click.option(
    "--dataset",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the OHLCV Parquet file.",
)
@click.option(
    "--train-bars",
    required=True,
    type=int,
    help="Number of training bars per window.",
)
@click.option(
    "--test-bars",
    required=True,
    type=int,
    help="Number of test (evaluation) bars per window.",
)
@click.option(
    "--step-bars",
    required=True,
    type=int,
    help="Number of bars to advance between windows.",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write walk-forward report JSON to this path (default: stdout only).",
)
@click.option(
    "--initial-capital",
    default=10_000.0,
    show_default=True,
    type=float,
    help="Starting capital per window backtest.",
)
@click.option(
    "--fee-bps",
    default=10.0,
    show_default=True,
    type=float,
    help="Taker fee in basis points (e.g. 10 = 0.10%).",
)
@click.option(
    "--slippage-bps",
    default=2.0,
    show_default=True,
    type=float,
    help="Half-spread slippage in bps per side.",
)
def main(
    dataset: Path,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    output_json: Path | None,
    initial_capital: float,
    fee_bps: float,
    slippage_bps: float,
) -> None:
    """Execute a deterministic walk-forward validation.

    Prints a JSON summary to stdout.  Exits 0 on clean completion,
    1 if issues were detected, 2 on configuration errors.
    """
    import logging

    import structlog

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.WARNING, force=True)
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    if train_bars <= 0:
        click.echo(f"ERROR: --train-bars must be positive, got {train_bars}", err=True)
        sys.exit(2)
    if test_bars <= 0:
        click.echo(f"ERROR: --test-bars must be positive, got {test_bars}", err=True)
        sys.exit(2)
    if step_bars <= 0:
        click.echo(f"ERROR: --step-bars must be positive, got {step_bars}", err=True)
        sys.exit(2)

    # ── Load and validate dataset ─────────────────────────────────────────────
    try:
        ohlcv = pd.read_parquet(dataset)
    except Exception as exc:
        click.echo(f"ERROR loading dataset: {exc}", err=True)
        sys.exit(2)

    symbol = str(ohlcv["symbol"].iloc[0]) if "symbol" in ohlcv.columns else ""
    timeframe = str(ohlcv["timeframe"].iloc[0]) if "timeframe" in ohlcv.columns else "1h"
    vresult = validate_ohlcv(ohlcv, symbol, timeframe)
    if not vresult.is_valid:
        click.echo(
            "ERROR: Dataset validation failed:\n" + "\n".join(f"  • {e}" for e in vresult.errors),
            err=True,
        )
        sys.exit(2)

    ohlcv = ohlcv.sort_values("timestamp").reset_index(drop=True)

    config = BacktestConfig(
        initial_capital=initial_capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )

    # ── Run walk-forward ──────────────────────────────────────────────────────
    try:
        report = run_walkforward(
            ohlcv,
            config,
            train_bars,
            test_bars,
            step_bars,
            dataset_path=str(dataset),
        )
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        save_report(report, output_json)
        click.echo(f"Report written to {output_json}", err=True)

    has_issues = not report.leakage_validated or report.summary.n_windows_failed > 0

    summary = {
        "report_version": report.report_version,
        "dataset": str(dataset),
        "total_bars": report.total_bars,
        "train_bars": report.train_bars,
        "test_bars": report.test_bars,
        "step_bars": report.step_bars,
        "n_windows": report.n_windows,
        "n_windows_evaluated": report.summary.n_windows_evaluated,
        "n_windows_failed": report.summary.n_windows_failed,
        "n_windows_profitable": report.summary.n_windows_profitable,
        "mean_total_return": report.summary.mean_total_return,
        "std_total_return": report.summary.std_total_return,
        "mean_sharpe_ratio": report.summary.mean_sharpe_ratio,
        "test_overlap": report.summary.test_overlap,
        "leakage_validated": report.leakage_validated,
        "validation_issues": list(report.validation_issues),
        "report_hash": report.report_hash,
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    sys.exit(1 if has_issues else 0)


if __name__ == "__main__":
    main()
