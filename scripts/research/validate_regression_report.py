"""Validate a regression report for self-certifying hash and consistency.

Exit codes:
  0  — report is valid
  1  — report validation failed
  2  — report file cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.regression_guard import (
    load_regression_report,
    validate_regression_report,
)


@click.command()
@click.option(
    "--report-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the regression report JSON file.",
)
def main(report_json: Path) -> None:
    """Validate a regression report JSON.

    Exits 0 when valid, 1 when validation fails, 2 when the file is unreadable.
    """
    try:
        report = load_regression_report(report_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading report: {exc}", err=True)
        sys.exit(2)

    is_valid, errors = validate_regression_report(report)

    result = {
        "report_json": str(report_json),
        "regression_id": report.regression_id,
        "regression_hash": report.regression_hash,
        "valid": is_valid,
        "errors": errors,
        "total_findings": len(report.regression_findings),
        "governance_violations": report.governance_validation_results.get("violation_count", 0),
        "advisory_note": (
            "Regression reports are advisory only. "
            "Human review is required before any merge or operational decision."
        ),
    }
    click.echo(json.dumps(result, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
