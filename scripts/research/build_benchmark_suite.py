"""Build a deterministic benchmark suite from a directory of campaign JSON files.

Loads ResearchCampaign JSON artifacts, validates each, computes advisory
governance scores, produces a deterministic self-certifying benchmark report.

Exit codes:
  0  — benchmark built; no validation issues
  1  — benchmark built but issues were found or regressions detected
  2  — invalid CLI arguments or no valid campaigns found

Manual command:
  PYTHONPATH=src python scripts/research/build_benchmark_suite.py \\
    --campaigns-dir reports/campaigns/ \\
    --benchmark-name baseline_benchmark_suite \\
    --output-json reports/benchmark_suite.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.benchmark_suite import (
    build_benchmark_suite,
    save_benchmark,
)


@click.command()
@click.option(
    "--campaigns-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing ResearchCampaign JSON files.",
)
@click.option(
    "--benchmark-name",
    required=True,
    type=str,
    help="Human-readable benchmark suite name.",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write benchmark suite JSON to this path (default: stdout only).",
)
def main(
    campaigns_dir: Path,
    benchmark_name: str,
    output_json: Path | None,
) -> None:
    """Build a deterministic benchmark suite from campaign JSON files.

    Prints a JSON summary to stdout.  Rankings are advisory only.
    Exits 0 when clean, 1 when issues or regressions are detected.
    """
    campaign_files = sorted(campaigns_dir.glob("*.json"))
    if not campaign_files:
        click.echo(f"ERROR: No JSON files found in '{campaigns_dir}'", err=True)
        sys.exit(2)

    try:
        suite = build_benchmark_suite(campaign_files, benchmark_name)
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        try:
            save_benchmark(suite, output_json)
            click.echo(f"Benchmark suite written to {output_json}", err=True)
        except OSError as exc:
            click.echo(f"ERROR writing benchmark: {exc}", err=True)
            sys.exit(2)

    has_issues = bool(suite.issues) or bool(suite.regression_flags)

    summary = {
        "benchmark_version": suite.benchmark_version,
        "benchmark_id": suite.benchmark_id,
        "benchmark_name": suite.benchmark_name,
        "benchmark_hash": suite.benchmark_hash,
        "total_campaigns": suite.total_campaigns,
        "issues_count": len(suite.issues),
        "warnings_count": len(suite.warnings),
        "regression_flags_count": len(suite.regression_flags),
        "regression_flags": list(suite.regression_flags),
        "issues": list(suite.issues),
        "advisory_disclaimer": (
            "Rankings are for governance review ONLY. "
            "They do not constitute deployment recommendations."
        ),
        "ranking": [
            {
                "rank": e.rank,
                "campaign_name": e.campaign_name,
                "score": e.score,
                "regressions": len(e.regression_flags),
            }
            for e in suite.comparison_entries
        ],
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    sys.exit(1 if has_issues else 0)


if __name__ == "__main__":
    main()
