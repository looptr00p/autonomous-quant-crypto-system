"""Build a deterministic local dataset registry from an OHLCV data directory.

Scans the specified directory for Parquet datasets and their manifest files,
validates linkage, detects orphans and duplicates, and writes a deterministic
JSON registry.  Prints a summary to stdout.

Exit codes:
  0  — registry built; no issues detected
  1  — registry built but issues were found (missing manifests, orphans, etc.)
  2  — invalid CLI arguments or unreadable data directory

Manual command:
  PYTHONPATH=src python scripts/data/build_dataset_registry.py \\
    --data-dir data/burn_in/ \\
    --output-json data/registry/dataset_registry.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.data.dataset_registry import (
    save_registry,
    scan_directory,
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
    help="Write registry JSON to this path (default: stdout only).",
)
@click.option(
    "--verify-manifests",
    is_flag=True,
    default=False,
    help="Re-verify each manifest against its parquet (slower).",
)
def main(data_dir: Path, output_json: Path | None, verify_manifests: bool) -> None:
    """Build a deterministic dataset registry from a data directory.

    Prints a JSON summary to stdout.  Exits 0 when no issues are found,
    exits 1 when issues are detected (missing manifests, orphans, duplicates).
    """
    # Redirect logs to stderr so stdout stays clean JSON.
    import logging

    import structlog

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.WARNING, force=True)
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    try:
        registry = scan_directory(data_dir, verify_manifests=verify_manifests)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        try:
            save_registry(registry, output_json)
            click.echo(f"Registry written to {output_json}", err=True)
        except OSError as exc:
            click.echo(f"ERROR writing registry: {exc}", err=True)
            sys.exit(2)

    summary = {
        "registry_version": registry.registry_version,
        "data_dir": registry.data_dir,
        "generation_timestamp_utc": registry.generation_timestamp_utc,
        "total_datasets": registry.total_datasets,
        "orphan_manifests_count": len(registry.orphan_manifests),
        "duplicate_identity_groups": len(registry.duplicate_identities),
        "issues_count": len(registry.issues),
        "issues": list(registry.issues),
        "symbols": sorted({e.symbol for e in registry.entries if e.symbol}),
        "timeframes": sorted({e.timeframe for e in registry.entries if e.timeframe}),
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    if registry.issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
