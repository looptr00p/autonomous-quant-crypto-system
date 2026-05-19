"""Validate a sensitivity audit report for self-certifying hash and consistency.

Exit codes:
  0  — audit report is valid
  1  — audit validation failed
  2  — audit file cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.sensitivity_audit import (
    load_sensitivity_audit,
    validate_sensitivity_audit,
)


@click.command()
@click.option(
    "--audit-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the sensitivity audit JSON file.",
)
def main(audit_json: Path) -> None:
    """Validate a sensitivity audit report JSON.

    Exits 0 when valid, 1 when validation fails, 2 when the file is unreadable.
    """
    try:
        audit = load_sensitivity_audit(audit_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading audit: {exc}", err=True)
        sys.exit(2)

    is_valid, errors = validate_sensitivity_audit(audit)

    result = {
        "audit_json": str(audit_json),
        "audit_id": audit.audit_id,
        "audit_hash": audit.audit_hash,
        "valid": is_valid,
        "errors": errors,
        "total_perturbations": len(audit.sensitivity_results),
        "instability_findings": len(audit.instability_findings),
        "overall_stability": audit.stability_scores.get("overall_stability"),
        "advisory_note": (
            "Sensitivity audits are advisory only. "
            "Human review is required before any parameter change or governance decision."
        ),
    }
    click.echo(json.dumps(result, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
