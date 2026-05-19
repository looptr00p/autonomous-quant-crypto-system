"""Validate a previously generated baseline research report.

Loads an existing report JSON, re-derives the report hash, and validates
self-certification and basic consistency.

Exit codes:
  0  — report is valid (hash verified, all checks pass)
  1  — report validation failed (hash mismatch or consistency error)
  2  — report file cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.baseline_report import load_report, validate_report


@click.command()
@click.option(
    "--report-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the baseline report JSON file.",
)
def main(report_json: Path) -> None:
    """Validate a baseline research report JSON file.

    Prints a deterministic JSON validation summary to stdout.
    Exits 0 when valid, 1 when validation fails, 2 when the file is unreadable.
    """
    try:
        report = load_report(report_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading report: {exc}", err=True)
        sys.exit(2)

    is_valid, errors = validate_report(report)

    result = {
        "report_json": str(report_json),
        "report_version": report.report_version,
        "experiment_id": report.experiment_id,
        "report_hash": report.report_hash,
        "valid": is_valid,
        "errors": errors,
        "replay_certified": report.replay_certified,
        "dataset_content_hash": report.dataset_content_hash,
        "dataset_schema_hash": report.dataset_schema_hash,
        "metrics_hash": report.metrics_hash,
        "disclaimer": report.disclaimer,
    }
    click.echo(json.dumps(result, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
