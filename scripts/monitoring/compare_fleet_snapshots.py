"""Compare two fleet snapshots and report drift.

Loads a baseline and a candidate fleet snapshot JSON, computes drift
(added/removed/modified datasets, freshness changes, new/resolved issues),
and prints a deterministic JSON report to stdout.

Exit codes:
  0  — no drift detected
  1  — drift or new issues detected
  2  — snapshot files cannot be read or are malformed

Manual command:
  PYTHONPATH=src python scripts/monitoring/compare_fleet_snapshots.py \\
    --baseline data/fleet/fleet_snapshot_v1.json \\
    --candidate data/fleet/fleet_snapshot_v2.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.monitoring.fleet_monitoring import (
    compare_snapshots,
    drift_to_dict,
    load_snapshot,
)


@click.command()
@click.option(
    "--baseline",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the baseline fleet snapshot JSON.",
)
@click.option(
    "--candidate",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the candidate fleet snapshot JSON.",
)
def main(baseline: Path, candidate: Path) -> None:
    """Compare two fleet snapshots and report drift.

    Prints a deterministic JSON report to stdout.
    Exits 0 when no drift is detected, 1 when drift or new issues are found,
    2 when snapshot files cannot be read.
    """
    try:
        base_snap = load_snapshot(baseline)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading baseline: {exc}", err=True)
        sys.exit(2)

    try:
        cand_snap = load_snapshot(candidate)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading candidate: {exc}", err=True)
        sys.exit(2)

    drift = compare_snapshots(base_snap, cand_snap)
    click.echo(json.dumps(drift_to_dict(drift), indent=2, sort_keys=True))

    sys.exit(0 if not drift.has_drift else 1)


if __name__ == "__main__":
    main()
