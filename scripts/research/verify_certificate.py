"""Verify a replay certificate against re-loaded experiment artifacts.

Loads the reference certificate JSON and re-certifies from the artifact
files.  Reports any hash mismatches to stdout as a JSON result.

Exit codes:
  0  — all hash fields verified (deterministic replay confirmed)
  1  — one or more hash fields differ (replay mismatch detected)
  2  — certificate or artifact file cannot be read
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import pandas as pd

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.storage import load_experiment_json
from aqcs.research.replay_certificate import (
    load_certificate,
    verify_certificate,
)
from aqcs.utils.events import SignalDirection


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


def _load_signals(artifact_dir: Path, experiment_id: str) -> pd.Series:
    path = artifact_dir / experiment_id / "signals.parquet"
    if not path.exists():
        return pd.Series(dtype=object)
    df = pd.read_parquet(path)
    directions = [SignalDirection(str(v)) for v in df["signal"]]
    timestamps = pd.to_datetime(df["timestamp"], utc=True)
    return pd.Series(directions, index=timestamps)


@click.command()
@click.option(
    "--certificate",
    "cert_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the reference certificate JSON.",
)
@click.option(
    "--experiment-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the experiment JSON artifact.",
)
@click.option(
    "--artifact-dir",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing per-experiment parquet artifacts.",
)
@click.option(
    "--dataset-content-hash",
    default="",
    help="Dataset content hash to verify against.",
)
@click.option(
    "--dataset-schema-hash",
    default="",
    help="Dataset schema hash to verify against.",
)
def main(
    cert_path: Path,
    experiment_json: Path,
    artifact_dir: Path,
    dataset_content_hash: str,
    dataset_schema_hash: str,
) -> None:
    """Verify a replay certificate against experiment artifacts.

    Exits 0 if verified, 1 on mismatch, 2 on load error.
    """
    try:
        reference = load_certificate(cert_path)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading certificate: {exc}", err=True)
        sys.exit(2)

    try:
        experiment = load_experiment_json(experiment_json)
    except Exception as exc:
        click.echo(f"ERROR loading experiment: {exc}", err=True)
        sys.exit(2)

    exp_id = str(experiment.experiment_id)
    content_hash = dataset_content_hash or reference.dataset_content_hash
    schema_hash = dataset_schema_hash or reference.dataset_schema_hash

    try:
        trades = _load_trades(artifact_dir, exp_id)
        equity_curve = _load_equity(artifact_dir, exp_id)
        signals = _load_signals(artifact_dir, exp_id)
    except Exception as exc:
        click.echo(f"ERROR loading artifacts: {exc}", err=True)
        sys.exit(2)

    params = experiment.parameters
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

    result = BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        metrics={k: float(v) for k, v in experiment.metrics.items() if v is not None},
        n_bars=len(equity_curve),
        experiment_id=exp_id,
    )

    try:
        vresult = verify_certificate(
            result, signals, content_hash, schema_hash, experiment, reference
        )
    except Exception as exc:
        click.echo(f"ERROR verifying: {exc}", err=True)
        sys.exit(2)

    output = {
        "verified": vresult.verified,
        "experiment_id": exp_id,
        "certificate_path": str(cert_path),
        "mismatches": [{"field": f, "expected": e, "actual": a} for f, e, a in vresult.mismatches],
    }
    click.echo(json.dumps(output, indent=2, sort_keys=True))
    sys.exit(0 if vresult.verified else 1)


if __name__ == "__main__":
    main()
