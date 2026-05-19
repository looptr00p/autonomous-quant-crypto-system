"""Build a deterministic research campaign from a directory of artifacts.

Scans the specified directory for DatasetManifest, ReplayCertificate,
WalkForwardReport, and BaselineReport JSON artifacts, validates each,
aggregates metrics, and produces an immutable campaign JSON.

Exit codes:
  0  — campaign built; no validation issues
  1  — campaign built but validation issues were found
  2  — invalid CLI arguments or artifacts directory cannot be read

Manual command:
  PYTHONPATH=src python scripts/research/build_campaign.py \\
    --artifacts-dir experiments/campaign_inputs/ \\
    --campaign-name baseline_campaign \\
    --output-json reports/campaign_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.campaign import build_campaign, save_campaign


@click.command()
@click.option(
    "--artifacts-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing artifact JSON files (manifests, certs, WF, baselines).",
)
@click.option(
    "--campaign-name",
    required=True,
    type=str,
    help="Human-readable campaign name.",
)
@click.option(
    "--output-json",
    default=None,
    type=click.Path(path_type=Path),
    help="Write campaign JSON to this path (default: stdout only).",
)
def main(
    artifacts_dir: Path,
    campaign_name: str,
    output_json: Path | None,
) -> None:
    """Build a deterministic research campaign from artifact JSON files.

    Prints a JSON summary to stdout.
    Exits 0 when no issues are found, 1 when issues are detected.
    """
    try:
        campaign = build_campaign(artifacts_dir, campaign_name)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(2)

    if output_json is not None:
        try:
            save_campaign(campaign, output_json)
            click.echo(f"Campaign written to {output_json}", err=True)
        except OSError as exc:
            click.echo(f"ERROR writing campaign: {exc}", err=True)
            sys.exit(2)

    summary = {
        "campaign_version": campaign.campaign_version,
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.campaign_name,
        "campaign_hash": campaign.campaign_hash,
        "total_experiments": campaign.total_experiments,
        "total_walkforward_windows": campaign.total_walkforward_windows,
        "n_manifests": len(campaign.dataset_manifest_hashes),
        "n_certificates": len(campaign.replay_certificate_hashes),
        "n_walkforward_reports": len(campaign.walkforward_report_hashes),
        "n_baseline_reports": len(campaign.baseline_report_hashes),
        "symbols": list(campaign.symbols),
        "timeframes": list(campaign.timeframes),
        "n_artifacts": len(campaign.artifact_hashes),
        "issues_count": len(campaign.issues),
        "warnings_count": len(campaign.warnings),
        "issues": list(campaign.issues),
        "warnings": list(campaign.warnings),
    }
    click.echo(json.dumps(summary, indent=2, sort_keys=True))

    if campaign.issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
