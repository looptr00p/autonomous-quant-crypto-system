"""Validate a benchmark suite JSON for self-certifying hash and consistency.

Exit codes:
  0  — benchmark is valid
  1  — benchmark validation failed
  2  — benchmark file cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.benchmark_suite import load_benchmark, validate_benchmark


@click.command()
@click.option(
    "--benchmark-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the benchmark suite JSON file.",
)
def main(benchmark_json: Path) -> None:
    """Validate a benchmark suite JSON.

    Exits 0 when valid, 1 when validation fails, 2 when the file is unreadable.
    """
    try:
        suite = load_benchmark(benchmark_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading benchmark: {exc}", err=True)
        sys.exit(2)

    is_valid, errors = validate_benchmark(suite)

    result = {
        "benchmark_json": str(benchmark_json),
        "benchmark_id": suite.benchmark_id,
        "benchmark_name": suite.benchmark_name,
        "benchmark_hash": suite.benchmark_hash,
        "valid": is_valid,
        "errors": errors,
        "total_campaigns": suite.total_campaigns,
        "regression_flags_count": len(suite.regression_flags),
        "regression_flags": list(suite.regression_flags),
        "issues_count": len(suite.issues),
        "recorded_issues": list(suite.issues),
        "advisory_disclaimer": (
            "Rankings are for governance review ONLY. "
            "They do not constitute deployment recommendations."
        ),
    }
    click.echo(json.dumps(result, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
