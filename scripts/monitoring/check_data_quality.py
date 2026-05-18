"""Deterministic OHLCV data-quality check CLI.

Reads a local Parquet file, runs all quality checks, and outputs a
deterministic JSON report to stdout.

Exit codes:
  0  — all checks passed (report.passed is True)
  1  — one or more errors found (report.passed is False)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.monitoring.data_quality import (
    check_ohlcv_parquet_quality,
    report_to_dict,
)

_TIMEFRAME_CHOICES = ["1m", "5m", "1h", "4h", "1d"]


@click.command()
@click.option(
    "--parquet",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to local OHLCV Parquet file.",
)
@click.option(
    "--timeframe",
    required=True,
    type=click.Choice(_TIMEFRAME_CHOICES),
    help="Expected candle timeframe (1m, 5m, 1h, 4h, 1d).",
)
def main(parquet: Path, timeframe: str) -> None:
    """Run deterministic OHLCV data-quality checks on a local Parquet file.

    Outputs a JSON report to stdout. Exits 0 when all checks pass,
    exits 1 when any structural error is found.
    """
    report = check_ohlcv_parquet_quality(parquet, timeframe)
    click.echo(json.dumps(report_to_dict(report), indent=2, sort_keys=True))
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
