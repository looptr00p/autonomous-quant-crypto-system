"""Generate a deterministic baseline research report from experiment artifacts.

Reads an experiment JSON artifact, reconstructs the BacktestResult from
persisted equity/trades parquets, and produces a deterministic baseline
report JSON.

Exit codes:
  0  — report generated and self-validation passed
  1  — report generated but validation failed (hash mismatch or consistency error)
  2  — invalid CLI arguments or artifact loading failed

Manual command:
  PYTHONPATH=src python scripts/research/build_baseline_report.py \\
    --experiment-dir experiments/sample_experiment/ \\
    --output-json reports/baseline_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import pandas as pd

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.storage import load_experiment_json
from aqcs.research.baseline_report import (
    build_report,
    save_report,
    validate_report,
)


def _load_equity(artifact_dir: Path, experiment_id: str) -> tuple[EquityCurvePoint, ...]:
    path = artifact_dir / experiment_id / "equity_curve.parquet"
    if not path.exists():
        return ()
    df = pd.read_parquet(path)
    return tuple(
        EquityCurvePoint(
            timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
            equity=float(row["equity"]),
            cash=float(row["cash"]),
            position=float(row["position"]),
            price=float(row["price"]),
        )
        for _, row in df.iterrows()
    )


def _load_trades(artifact_dir: Path, experiment_id: str) -> tuple[Trade, ...]:
    path = artifact_dir / experiment_id / "trades.parquet"
    if not path.exists():
        return ()
    df = pd.read_parquet(path)
    return tuple(
        Trade(
            timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
            side=str(row["side"]),
            fill_price=float(row["fill_price"]),
            quantity=float(row["quantity"]),
            fee=float(row["fee"]),
            slippage_amount=float(row["slippage_amount"]),
            value=float(row["value"]),
        )
        for _, row in df.iterrows()
    )


def _find_experiment_json(experiment_dir: Path) -> Path:
    """Find the most recent experiment JSON in an experiment directory."""
    matches = sorted(experiment_dir.rglob("experiment_*.json"))
    if not matches:
        raise FileNotFoundError(f"No experiment_*.json files found in '{experiment_dir}'")
    return matches[-1]


@click.command()
@click.option(
    "--experiment-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing the experiment JSON artifact.",
)
@click.option(
    "--artifacts-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help=(
        "Directory containing per-experiment parquet artifacts "
        "(default: same as --experiment-dir)."
    ),
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write report JSON to this path (default: stdout only).",
)
@click.option(
    "--dataset-content-hash",
    default="",
    help="Dataset content hash (from DatasetManifest).",
)
@click.option(
    "--dataset-schema-hash",
    default="",
    help="Dataset schema hash (from DatasetManifest).",
)
@click.option(
    "--dataset-symbol",
    default="",
    help="Dataset market symbol (e.g. BTC/USDT).",
)
@click.option(
    "--dataset-timeframe",
    default="",
    help="Dataset candle timeframe (e.g. 1d).",
)
@click.option(
    "--dataset-exchange",
    default="",
    help="Dataset exchange name.",
)
def main(
    experiment_dir: Path,
    artifacts_dir: Path | None,
    output_json: Path | None,
    dataset_content_hash: str,
    dataset_schema_hash: str,
    dataset_symbol: str,
    dataset_timeframe: str,
    dataset_exchange: str,
) -> None:
    """Generate a deterministic baseline research report.

    Reads experiment artifacts, computes extended metrics, and prints a
    deterministic JSON report summary to stdout.  Exits 0 on success with
    passing validation, 1 on validation failure, 2 on load errors.
    """
    _art_dir = artifacts_dir or experiment_dir

    # ── Load experiment record ────────────────────────────────────────────────
    try:
        exp_json = _find_experiment_json(experiment_dir)
        experiment = load_experiment_json(exp_json)
    except (FileNotFoundError, Exception) as exc:
        click.echo(f"ERROR loading experiment: {exc}", err=True)
        sys.exit(2)

    exp_id = str(experiment.experiment_id)
    params = experiment.parameters

    # ── Reconstruct BacktestConfig from experiment parameters ─────────────────
    try:
        config = BacktestConfig(
            initial_capital=float(params.get("initial_capital", 10_000.0)),
            fee_bps=float(params.get("fee_bps", 0.0)),
            slippage_bps=float(params.get("slippage_bps", 0.0)),
            position_size_fraction=float(params.get("position_size_fraction", 1.0)),
            start_date=str(params.get("start_date", "")),
            end_date=str(params.get("end_date", "")),
            periods_per_year=int(params.get("periods_per_year", 252)),
        )
    except Exception as exc:
        click.echo(f"ERROR reconstructing config: {exc}", err=True)
        sys.exit(2)

    # ── Load artifacts ────────────────────────────────────────────────────────
    try:
        trades = _load_trades(_art_dir, exp_id)
        equity_curve = _load_equity(_art_dir, exp_id)
    except Exception as exc:
        click.echo(f"ERROR loading artifacts: {exc}", err=True)
        sys.exit(2)

    result = BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        metrics={k: float(v) for k, v in experiment.metrics.items() if v is not None},
        n_bars=len(equity_curve),
        experiment_id=exp_id,
    )

    # ── Build and validate report ─────────────────────────────────────────────
    report = build_report(
        result,
        dataset_content_hash=dataset_content_hash,
        dataset_schema_hash=dataset_schema_hash,
        dataset_symbol=dataset_symbol,
        dataset_timeframe=dataset_timeframe,
        dataset_exchange=dataset_exchange,
        experiment_record=experiment,
    )

    is_valid, errors = validate_report(report)

    if output_json is not None:
        save_report(report, output_json)
        click.echo(f"Report written to {output_json}", err=True)

    summary = {
        "report_version": report.report_version,
        "experiment_id": report.experiment_id,
        "report_hash": report.report_hash,
        "report_valid": is_valid,
        "validation_errors": errors,
        "total_return": (
            None if report.total_return != report.total_return else report.total_return
        ),
        "max_drawdown": report.max_drawdown,
        "sharpe_ratio": (
            None if report.sharpe_ratio != report.sharpe_ratio else report.sharpe_ratio
        ),
        "trade_count": report.trade_count,
        "benchmark_total_return": (
            None
            if report.benchmark_total_return != report.benchmark_total_return
            else report.benchmark_total_return
        ),
        "excess_return": (
            None if report.excess_return != report.excess_return else report.excess_return
        ),
        "total_fees_paid": report.total_fees_paid,
        "replay_certified": report.replay_certified,
        "disclaimer": report.disclaimer,
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
