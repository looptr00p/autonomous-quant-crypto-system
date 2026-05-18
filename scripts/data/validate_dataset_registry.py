"""Validate a previously built AQCS dataset registry JSON file.

Loads an existing registry and reports on issues, orphan manifests, and
duplicate dataset identities.  Does not re-scan the filesystem — validates
only the registry JSON's internal consistency.

Exit codes:
  0  — registry is clean (no issues recorded)
  1  — one or more issues found in the registry
  2  — registry JSON cannot be read or is malformed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from aqcs.data.dataset_registry import load_registry


@click.command()
@click.option(
    "--registry-json",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the registry JSON file produced by build_dataset_registry.py.",
)
def main(registry_json: Path) -> None:
    """Validate a dataset registry JSON file.

    Prints a deterministic JSON validation report to stdout.
    Exits 0 when the registry is clean, exits 1 when issues are found,
    exits 2 when the registry file cannot be parsed.
    """
    try:
        registry = load_registry(registry_json)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"ERROR loading registry: {exc}", err=True)
        sys.exit(2)

    entries_with_manifest = sum(1 for e in registry.entries if e.has_manifest)
    entries_missing_manifest = registry.total_datasets - entries_with_manifest
    entries_verified = sum(1 for e in registry.entries if e.manifest_verified)

    report = {
        "registry_version": registry.registry_version,
        "data_dir": registry.data_dir,
        "generation_timestamp_utc": registry.generation_timestamp_utc,
        "total_datasets": registry.total_datasets,
        "entries_with_manifest": entries_with_manifest,
        "entries_missing_manifest": entries_missing_manifest,
        "entries_manifest_verified": entries_verified,
        "orphan_manifests_count": len(registry.orphan_manifests),
        "orphan_manifests": list(registry.orphan_manifests),
        "duplicate_identity_groups": len(registry.duplicate_identities),
        "duplicate_identities": [list(g) for g in registry.duplicate_identities],
        "issues_count": len(registry.issues),
        "issues": list(registry.issues),
        "clean": len(registry.issues) == 0,
    }
    click.echo(json.dumps(report, indent=2, sort_keys=True))

    if registry.issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
