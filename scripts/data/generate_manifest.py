"""Generate a deterministic dataset identity manifest for a local OHLCV Parquet file.

Reads the Parquet file, computes content and schema hashes, and writes a
canonical JSON manifest to stdout (default) or to a specified output path.

Exit codes:
  0  — manifest generated successfully
  1  — Parquet file cannot be read or fails validation
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.data.manifest import (
    SUPPORTED_TIMEFRAMES,
    generate_manifest,
    manifest_to_dict,
    save_manifest,
)

_TIMEFRAME_CHOICES = sorted(SUPPORTED_TIMEFRAMES)


@click.command()
@click.option(
    "--parquet",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to local OHLCV Parquet file.",
)
@click.option(
    "--symbol",
    required=True,
    type=str,
    help='Market symbol, e.g. "BTC/USDT".',
)
@click.option(
    "--timeframe",
    required=True,
    type=click.Choice(_TIMEFRAME_CHOICES),
    help="Candle timeframe.",
)
@click.option(
    "--output",
    default=None,
    type=click.Path(path_type=Path),
    help="Write manifest JSON to this path instead of stdout.",
)
def main(parquet: Path, symbol: str, timeframe: str, output: Path | None) -> None:
    """Generate a deterministic identity manifest for an OHLCV Parquet file.

    Outputs canonical JSON to stdout unless --output is specified.
    Exits 0 on success, 1 on any validation error.
    """
    try:
        manifest = generate_manifest(parquet, symbol, timeframe)
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    if output is not None:
        save_manifest(manifest, output)
        click.echo(f"Manifest written to {output}", err=True)
    else:
        click.echo(json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
