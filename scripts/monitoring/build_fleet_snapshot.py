"""Build a deterministic fleet snapshot from a local dataset directory.

Scans the specified data directory for OHLCV Parquet files and manifests,
builds a reproducible fleet-level snapshot, and writes it to a JSON file.
Prints a deterministic summary to stdout.

Exit codes:
  0  — snapshot built; no registry issues detected
  1  — snapshot built but registry issues were found
  2  — invalid CLI arguments or unreadable directory

Manual command:
  PYTHONPATH=src python scripts/monitoring/build_fleet_snapshot.py \\
    --data-dir data/burn_in/ \\
    --output-json data/fleet/fleet_snapshot.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.monitoring.fleet_monitoring import (
    build_snapshot,
    save_snapshot,
)


@click.command()
@click.option(
    "--data-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory to scan for OHLCV Parquet datasets and manifests.",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write snapshot JSON to this path (default: stdout only).",
)
@click.option(
    "--verify-manifests",
    is_flag=True,
    default=False,
    help="Re-verify each manifest against its parquet (slower).",
)
def main(data_dir: Path, output_json: Path | None, verify_manifests: bool) -> None:
    """Build a deterministic fleet snapshot from a dataset directory.

    Prints a JSON summary to stdout.  Exits 0 when no registry issues exist,
    exits 1 when issues are detected.
    """
    import logging

    import structlog

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.WARNING, force=True)
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    try:
        snapshot = build_snapshot(data_dir, verify_manifests=verify_manifests)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        try:
            save_snapshot(snapshot, output_json)
            click.echo(f"Snapshot written to {output_json}", err=True)
        except OSError as exc:
            click.echo(f"ERROR writing snapshot: {exc}", err=True)
            sys.exit(2)

    summary = {
        "snapshot_version": snapshot.snapshot_version,
        "generation_timestamp_utc": snapshot.generation_timestamp_utc,
        "registry_hash": snapshot.registry_hash,
        "total_datasets": snapshot.total_datasets,
        "total_manifests": snapshot.total_manifests,
        "symbols": list(snapshot.symbols),
        "timeframes": list(snapshot.timeframes),
        "orphan_manifest_count": snapshot.orphan_manifest_count,
        "duplicate_identity_count": snapshot.duplicate_identity_count,
        "issue_count": snapshot.issue_count,
        "issues": list(snapshot.issues),
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    if snapshot.issue_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
