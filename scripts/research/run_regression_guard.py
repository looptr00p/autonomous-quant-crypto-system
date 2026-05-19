"""Run a deterministic research regression guard.

Compares two directories of research artifacts (baseline vs candidate),
detects metric drift, hash mismatches, replay drift, and governance
violations, and produces a self-certifying regression report.

Exit codes:
  0  — no regressions or governance violations detected
  1  — regressions or governance violations detected
  2  — invalid CLI arguments or directory cannot be read

Manual command:
  PYTHONPATH=src python scripts/research/run_regression_guard.py \\
    --baseline-dir reports/baseline_suite/ \\
    --candidate-dir reports/candidate_suite/ \\
    --output-json reports/regression_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.regression_guard import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    run_regression_guard,
    save_regression_report,
)


@click.command()
@click.option(
    "--baseline-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing baseline (reference) artifact JSON files.",
)
@click.option(
    "--candidate-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing candidate (proposed) artifact JSON files.",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write regression report JSON to this path (default: stdout only).",
)
def main(
    baseline_dir: Path,
    candidate_dir: Path,
    output_json: Path | None,
) -> None:
    """Run a deterministic research regression guard.

    Compares baseline and candidate artifact directories.
    Exits 0 when no regressions are detected, 1 when regressions exist.
    """
    try:
        report = run_regression_guard(baseline_dir, candidate_dir)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        try:
            save_regression_report(report, output_json)
            click.echo(f"Regression report written to {output_json}", err=True)
        except OSError as exc:
            click.echo(f"ERROR writing report: {exc}", err=True)
            sys.exit(2)

    critical = [f for f in report.regression_findings if f.severity == SEVERITY_CRITICAL]
    warnings_ = [f for f in report.regression_findings if f.severity == SEVERITY_WARNING]
    has_regression = (
        bool(critical) or report.governance_validation_results.get("violation_count", 0) > 0
    )

    summary = {
        "regression_version": report.regression_version,
        "regression_id": report.regression_id,
        "regression_hash": report.regression_hash,
        "total_findings": len(report.regression_findings),
        "critical_findings": len(critical),
        "warning_findings": len(warnings_),
        "governance_violations": report.governance_validation_results.get("violation_count", 0),
        "has_regression": has_regression,
        "issues_count": len(report.issues),
        "advisory_note": (
            "Regression reports are advisory only. "
            "Human review is required before any merge or operational decision."
        ),
        "findings_summary": [
            {
                "severity": f.severity,
                "type": f.finding_type,
                "artifact": f.artifact_reference,
                "summary": f.deterministic_diff_summary,
            }
            for f in report.regression_findings
            if f.severity in (SEVERITY_CRITICAL, SEVERITY_WARNING)
        ],
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    sys.exit(1 if has_regression else 0)


if __name__ == "__main__":
    main()
