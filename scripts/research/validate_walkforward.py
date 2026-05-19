"""Validate a walk-forward report for temporal consistency and leakage safety.

Loads an existing walk-forward report JSON and validates:
- self-certifying hash
- window temporal ordering
- no train/test overlap within each window
- chronological window ordering

Exit codes:
  0  — report is valid
  1  — validation failed (hash mismatch or temporal inconsistency)
  2  — report file cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.walkforward import load_report, validate_report


@click.command()
@click.option(
    "--walkforward-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the walk-forward report JSON.",
)
def main(walkforward_json: Path) -> None:
    """Validate a walk-forward report for temporal consistency.

    Exits 0 when valid, 1 when validation fails, 2 when the file is unreadable.
    """
    try:
        report = load_report(walkforward_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading report: {exc}", err=True)
        sys.exit(2)

    is_valid, errors = validate_report(report)

    result = {
        "walkforward_json": str(walkforward_json),
        "report_version": report.report_version,
        "total_bars": report.total_bars,
        "train_bars": report.train_bars,
        "test_bars": report.test_bars,
        "step_bars": report.step_bars,
        "n_windows": report.n_windows,
        "leakage_validated": report.leakage_validated,
        "valid": is_valid,
        "errors": errors,
        "report_hash": report.report_hash,
        "summary": {
            "n_windows_evaluated": report.summary.n_windows_evaluated,
            "n_windows_failed": report.summary.n_windows_failed,
            "n_windows_profitable": report.summary.n_windows_profitable,
            "mean_total_return": (
                None
                if report.summary.mean_total_return != report.summary.mean_total_return
                else report.summary.mean_total_return
            ),
            "test_overlap": report.summary.test_overlap,
        },
    }
    click.echo(json.dumps(result, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
