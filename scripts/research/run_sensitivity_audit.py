"""Run a deterministic parameter sensitivity audit on a research artifact.

Evaluates how stable an artifact's metrics are under controlled, explicit
parameter perturbations defined in a config file.  Produces a self-certifying
sensitivity audit report.

Exit codes:
  0  — all perturbations are LOW severity (stable)
  1  — MEDIUM, HIGH, or CRITICAL instability findings detected
  2  — invalid CLI arguments or file cannot be read

Manual command:
  PYTHONPATH=src python scripts/research/run_sensitivity_audit.py \\
    --baseline-artifact reports/campaign_report.json \\
    --perturbation-config configs/sensitivity/default.json \\
    --output-json reports/sensitivity_audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.sensitivity_audit import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    run_sensitivity_audit,
    save_sensitivity_audit,
)


@click.command()
@click.option(
    "--baseline-artifact",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the baseline research artifact JSON file.",
)
@click.option(
    "--perturbation-config",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the perturbation config JSON file.",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write sensitivity audit JSON to this path (default: stdout only).",
)
def main(
    baseline_artifact: Path,
    perturbation_config: Path,
    output_json: Path | None,
) -> None:
    """Run a deterministic parameter sensitivity audit.

    Evaluates metric stability under explicit parameter perturbations.
    Exits 0 when all findings are LOW severity, 1 when instability is detected.
    """
    try:
        audit = run_sensitivity_audit(baseline_artifact, perturbation_config)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        try:
            save_sensitivity_audit(audit, output_json)
            click.echo(f"Sensitivity audit written to {output_json}", err=True)
        except OSError as exc:
            click.echo(f"ERROR writing audit: {exc}", err=True)
            sys.exit(2)

    critical = [f for f in audit.instability_findings if f.severity == SEVERITY_CRITICAL]
    high = [f for f in audit.instability_findings if f.severity == SEVERITY_HIGH]
    medium = [f for f in audit.instability_findings if f.severity == SEVERITY_MEDIUM]
    has_instability = bool(critical or high or medium)

    summary = {
        "audit_version": audit.audit_version,
        "audit_id": audit.audit_id,
        "audit_hash": audit.audit_hash,
        "total_perturbations": len(audit.sensitivity_results),
        "instability_findings": len(audit.instability_findings),
        "critical_findings": len(critical),
        "high_findings": len(high),
        "medium_findings": len(medium),
        "overall_stability": audit.stability_scores.get("overall_stability"),
        "has_instability": has_instability,
        "issues_count": len(audit.issues),
        "advisory_note": (
            "Sensitivity audits are advisory only. "
            "Human review is required before any parameter change or governance decision."
        ),
        "findings_summary": [
            {
                "severity": f.severity,
                "parameter": f.parameter_name,
                "magnitude": f.perturbation_magnitude,
                "governance_threshold": f.governance_threshold_crossed,
                "summary": f.deterministic_diff_summary,
            }
            for f in audit.instability_findings
            if f.severity in (SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM)
        ],
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    sys.exit(1 if has_instability else 0)


if __name__ == "__main__":
    main()
