"""Generate a replay certificate for a completed research experiment.

Reads the persisted experiment JSON artifact and, optionally, a dataset
manifest JSON to extract dataset hashes.  Loads the artifact parquets
(equity curve, trades, signals) and produces a ReplayCertificate.

Exit codes:
  0  — certificate generated successfully
  1  — artifact loading or certification failed
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
    certificate_to_dict,
    certify_result,
    save_certificate,
)
from aqcs.utils.events import SignalDirection


def _load_trades(artifact_dir: Path, experiment_id: str) -> tuple[Trade, ...]:
    path = artifact_dir / experiment_id / "trades.parquet"
    if not path.exists():
        return ()
    df = pd.read_parquet(path)
    trades = []
    for _, row in df.iterrows():
        trades.append(
            Trade(
                timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
                side=str(row["side"]),
                fill_price=float(row["fill_price"]),
                quantity=float(row["quantity"]),
                fee=float(row["fee"]),
                slippage_amount=float(row["slippage_amount"]),
                value=float(row["value"]),
            )
        )
    return tuple(trades)


def _load_equity(artifact_dir: Path, experiment_id: str) -> tuple[EquityCurvePoint, ...]:
    path = artifact_dir / experiment_id / "equity_curve.parquet"
    if not path.exists():
        return ()
    df = pd.read_parquet(path)
    points = []
    for _, row in df.iterrows():
        points.append(
            EquityCurvePoint(
                timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
                equity=float(row["equity"]),
                cash=float(row["cash"]),
                position=float(row["position"]),
                price=float(row["price"]),
            )
        )
    return tuple(points)


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
    "--manifest-json",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Dataset manifest JSON (provides content_hash and schema_hash).",
)
@click.option(
    "--dataset-content-hash",
    default="",
    help="Dataset content hash (overrides --manifest-json).",
)
@click.option(
    "--dataset-schema-hash",
    default="",
    help="Dataset schema hash (overrides --manifest-json).",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(path_type=Path),
    help="Write certificate JSON to this path instead of stdout.",
)
def main(
    experiment_json: Path,
    artifact_dir: Path,
    manifest_json: Path | None,
    dataset_content_hash: str,
    dataset_schema_hash: str,
    output: Path | None,
) -> None:
    """Generate a replay certificate for a completed research experiment.

    Exits 0 on success, 1 on error.
    """
    # ── Resolve dataset hashes ─────────────────────────────────────────────────
    content_hash = dataset_content_hash
    schema_hash = dataset_schema_hash
    if manifest_json is not None:
        try:
            manifest_data = json.loads(manifest_json.read_text(encoding="utf-8"))
            content_hash = content_hash or str(manifest_data.get("content_hash", ""))
            schema_hash = schema_hash or str(manifest_data.get("schema_hash", ""))
        except Exception as exc:
            click.echo(f"ERROR loading manifest: {exc}", err=True)
            sys.exit(1)

    # ── Load experiment record ─────────────────────────────────────────────────
    try:
        experiment = load_experiment_json(experiment_json)
    except Exception as exc:
        click.echo(f"ERROR loading experiment: {exc}", err=True)
        sys.exit(1)

    exp_id = str(experiment.experiment_id)

    # ── Load backtest artifacts ────────────────────────────────────────────────
    try:
        trades = _load_trades(artifact_dir, exp_id)
        equity_curve = _load_equity(artifact_dir, exp_id)
        signals = _load_signals(artifact_dir, exp_id)
    except Exception as exc:
        click.echo(f"ERROR loading artifacts: {exc}", err=True)
        sys.exit(1)

    # ── Reconstruct BacktestConfig from experiment parameters ──────────────────
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
        sys.exit(1)

    # Build a minimal BacktestResult from artifacts
    result = BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        metrics={k: float(v) for k, v in experiment.metrics.items() if v is not None},
        n_bars=len(equity_curve),
        experiment_id=exp_id,
    )

    # ── Certify ────────────────────────────────────────────────────────────────
    try:
        cert = certify_result(result, signals, content_hash, schema_hash, experiment)
    except Exception as exc:
        click.echo(f"ERROR certifying: {exc}", err=True)
        sys.exit(1)

    if output is not None:
        save_certificate(cert, output)
        click.echo(f"Certificate written to {output}", err=True)
    else:
        import json as _json

        click.echo(_json.dumps(certificate_to_dict(cert), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
