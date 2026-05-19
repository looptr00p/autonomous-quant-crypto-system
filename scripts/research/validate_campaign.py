"""Validate a previously built research campaign JSON.

Loads an existing campaign and validates its self-certifying hash,
campaign_id derivation, and internal consistency.

Exit codes:
  0  — campaign is valid (hash verified, no recorded issues)
  1  — campaign validation failed (hash mismatch or recorded issues)
  2  — campaign file cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.research.campaign import load_campaign, validate_campaign


@click.command()
@click.option(
    "--campaign-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the campaign JSON file.",
)
def main(campaign_json: Path) -> None:
    """Validate a research campaign JSON.

    Exits 0 when valid, 1 when validation fails, 2 when the file is unreadable.
    """
    try:
        campaign = load_campaign(campaign_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading campaign: {exc}", err=True)
        sys.exit(2)

    is_valid, errors = validate_campaign(campaign)

    result = {
        "campaign_json": str(campaign_json),
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.campaign_name,
        "campaign_hash": campaign.campaign_hash,
        "valid": is_valid,
        "errors": errors,
        "total_experiments": campaign.total_experiments,
        "total_walkforward_windows": campaign.total_walkforward_windows,
        "n_manifests": len(campaign.dataset_manifest_hashes),
        "n_certificates": len(campaign.replay_certificate_hashes),
        "recorded_issues": list(campaign.issues),
        "recorded_warnings": list(campaign.warnings),
    }
    click.echo(json.dumps(result, indent=2, sort_keys=True))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
