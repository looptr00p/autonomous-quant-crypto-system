"""Verify a local OHLCV Parquet file against a previously generated manifest.

Regenerates the manifest from the Parquet file and compares every field against
the reference manifest.  Reports mismatches to stderr and outputs a JSON summary
to stdout.

Exit codes:
  0  — all fields match (dataset integrity confirmed)
  1  — one or more fields differ (corruption or schema drift detected)
  2  — manifest or Parquet file cannot be read
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.data.manifest import load_manifest, verify_manifest


@click.command()
@click.option(
    "--parquet",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the OHLCV Parquet file to verify.",
)
@click.option(
    "--manifest",
    "manifest_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the reference manifest JSON file.",
)
def main(parquet: Path, manifest_path: Path) -> None:
    """Verify an OHLCV Parquet file against a reference manifest.

    Outputs a JSON result to stdout.  Exits 0 if verified, 1 if mismatches
    are found, 2 if the manifest or Parquet file cannot be read.
    """
    try:
        reference = load_manifest(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading manifest: {exc}", err=True)
        sys.exit(2)

    try:
        result = verify_manifest(parquet, reference)
    except ValueError as exc:
        click.echo(f"ERROR verifying parquet: {exc}", err=True)
        sys.exit(2)

    output = {
        "verified": result.verified,
        "parquet_path": str(parquet),
        "manifest_path": str(manifest_path),
        "mismatches": [{"field": f, "expected": e, "actual": a} for f, e, a in result.mismatches],
    }
    click.echo(json.dumps(output, indent=2, sort_keys=True))
    sys.exit(0 if result.verified else 1)


if __name__ == "__main__":
    main()
