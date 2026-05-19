"""Deterministic dataset fleet monitoring snapshots for AQCS.

A fleet snapshot is an immutable, reproducible record of the full local dataset
registry state at a single point in time.  Comparing two snapshots reveals:

  - added datasets    (in candidate, absent from baseline)
  - removed datasets  (in baseline, absent from candidate)
  - modified datasets (content_hash changed between snapshots)
  - freshness changes (end_timestamp_utc advanced or regressed)
  - new / resolved registry issues

Snapshots are purely observational.  They never modify datasets, manifests,
or registry files.

Determinism
-----------
- Entries are ordered by ``(symbol, timeframe, dataset_path)`` (inherited from
  the registry scan).
- ``registry_hash`` and ``registry_entries_hash`` are SHA-256 over
  JSON-serialised state with ``sort_keys=True``.
- ``generation_timestamp_utc`` is the only wall-clock field; inject
  ``now_utc`` in tests for fully reproducible output.
- Comparison results use lexicographic ordering of dataset paths.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqcs.data.dataset_registry import (
    DatasetRegistry,
    scan_directory,
)

# ── Version ───────────────────────────────────────────────────────────────────

SNAPSHOT_VERSION: str = "1"


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FleetSnapshotEntry:
    """Immutable per-dataset record within a fleet snapshot.

    All paths are relative to the registry's ``data_dir``.
    ``manifest_verified`` reflects the registry's per-entry verification flag;
    it is False when no manifest is present or when verification was not
    requested.
    """

    dataset_path: str
    manifest_path: str | None
    exchange: str
    symbol: str
    timeframe: str
    row_count: int
    start_timestamp_utc: str
    end_timestamp_utc: str
    content_hash: str
    schema_hash: str
    manifest_verified: bool


@dataclass(frozen=True)
class FleetSnapshot:
    """Immutable fleet-wide snapshot of the local dataset registry.

    ``registry_hash`` is a SHA-256 digest of the full registry state
    (entries, issues, orphans, duplicates) at snapshot time.
    ``registry_entries_hash`` covers only the dataset paths and content
    hashes — it is stable across metadata-only changes.
    ``snapshot_entries`` is sorted by ``(symbol, timeframe, dataset_path)``
    for deterministic comparison and serialisation.
    """

    snapshot_version: str
    generation_timestamp_utc: str
    registry_hash: str
    registry_entries_hash: str
    total_datasets: int
    total_manifests: int
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    datasets_by_symbol: dict[str, int]
    datasets_by_timeframe: dict[str, int]
    orphan_manifest_count: int
    duplicate_identity_count: int
    issue_count: int
    issues: tuple[str, ...]
    snapshot_entries: tuple[FleetSnapshotEntry, ...]


@dataclass(frozen=True)
class FreshnessChange:
    """Records a change in a dataset's temporal extent between two snapshots."""

    dataset_path: str
    baseline_end_utc: str
    candidate_end_utc: str
    direction: str  # "updated" | "truncated" | "unchanged"


@dataclass(frozen=True)
class FleetDrift:
    """Comparison result between a baseline and a candidate fleet snapshot.

    ``has_drift`` is True when any of the following is non-empty:
    added_datasets, removed_datasets, modified_datasets, new_issues.
    Resolved issues and freshness changes are informational.
    """

    baseline_timestamp_utc: str
    candidate_timestamp_utc: str
    added_datasets: tuple[str, ...]
    removed_datasets: tuple[str, ...]
    modified_datasets: tuple[str, ...]
    freshness_changes: tuple[FreshnessChange, ...]
    new_issues: tuple[str, ...]
    resolved_issues: tuple[str, ...]
    has_drift: bool
    summary: str


# ── Public API ────────────────────────────────────────────────────────────────


def build_snapshot(
    data_dir: Path,
    *,
    verify_manifests: bool = False,
    now_utc: datetime | None = None,
) -> FleetSnapshot:
    """Scan ``data_dir`` and build a deterministic fleet snapshot.

    Args:
        data_dir: Root directory containing OHLCV Parquet files and manifests.
        verify_manifests: When True, each manifest is verified against its
            parquet.  Slower but detects data corruption.  The result is
            reflected in each entry's ``manifest_verified`` field.
        now_utc: Reference UTC time for ``generation_timestamp_utc``.
            Defaults to ``datetime.now(UTC)``.  Inject a fixed value in tests
            for fully deterministic snapshots.

    Returns:
        An immutable ``FleetSnapshot`` capturing the current registry state.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)

    registry = scan_directory(
        data_dir,
        verify_manifests=verify_manifests,
        now_utc=_now,
    )

    return _snapshot_from_registry(registry, _now)


def compare_snapshots(
    baseline: FleetSnapshot,
    candidate: FleetSnapshot,
) -> FleetDrift:
    """Compare a candidate fleet snapshot against a baseline and return drift.

    Args:
        baseline: The earlier snapshot (reference state).
        candidate: The later snapshot (observed state).

    Returns:
        ``FleetDrift`` with all detected changes.  ``has_drift`` is True when
        any dataset was added, removed, or modified, or when new issues appeared.
    """
    baseline_paths = {e.dataset_path: e for e in baseline.snapshot_entries}
    candidate_paths = {e.dataset_path: e for e in candidate.snapshot_entries}

    all_paths = sorted(set(baseline_paths) | set(candidate_paths))

    added: list[str] = []
    removed: list[str] = []
    modified: list[str] = []
    freshness: list[FreshnessChange] = []

    for path in all_paths:
        in_base = path in baseline_paths
        in_cand = path in candidate_paths

        if in_cand and not in_base:
            added.append(path)
        elif in_base and not in_cand:
            removed.append(path)
        else:
            be = baseline_paths[path]
            ce = candidate_paths[path]
            if be.content_hash and ce.content_hash and be.content_hash != ce.content_hash:
                modified.append(path)
            if (
                be.end_timestamp_utc
                and ce.end_timestamp_utc
                and ce.end_timestamp_utc != be.end_timestamp_utc
            ):
                direction = (
                    "updated" if ce.end_timestamp_utc > be.end_timestamp_utc else "truncated"
                )
                freshness.append(
                    FreshnessChange(
                        dataset_path=path,
                        baseline_end_utc=be.end_timestamp_utc,
                        candidate_end_utc=ce.end_timestamp_utc,
                        direction=direction,
                    )
                )

    baseline_issues = set(baseline.issues)
    candidate_issues = set(candidate.issues)
    new_issues = sorted(candidate_issues - baseline_issues)
    resolved_issues = sorted(baseline_issues - candidate_issues)

    has_drift = bool(added or removed or modified or new_issues)

    parts: list[str] = []
    if added:
        parts.append(f"{len(added)} dataset(s) added")
    if removed:
        parts.append(f"{len(removed)} dataset(s) removed")
    if modified:
        parts.append(f"{len(modified)} dataset(s) modified")
    if new_issues:
        parts.append(f"{len(new_issues)} new issue(s)")
    summary = "; ".join(parts) if parts else "No drift detected"

    return FleetDrift(
        baseline_timestamp_utc=baseline.generation_timestamp_utc,
        candidate_timestamp_utc=candidate.generation_timestamp_utc,
        added_datasets=tuple(sorted(added)),
        removed_datasets=tuple(sorted(removed)),
        modified_datasets=tuple(sorted(modified)),
        freshness_changes=tuple(freshness),
        new_issues=tuple(new_issues),
        resolved_issues=tuple(resolved_issues),
        has_drift=has_drift,
        summary=summary,
    )


def snapshot_to_dict(snapshot: FleetSnapshot) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``FleetSnapshot``.

    Output is deterministic when ``json.dumps(..., sort_keys=True)`` is used.
    """
    return {
        "snapshot_version": snapshot.snapshot_version,
        "generation_timestamp_utc": snapshot.generation_timestamp_utc,
        "registry_hash": snapshot.registry_hash,
        "registry_entries_hash": snapshot.registry_entries_hash,
        "total_datasets": snapshot.total_datasets,
        "total_manifests": snapshot.total_manifests,
        "symbols": list(snapshot.symbols),
        "timeframes": list(snapshot.timeframes),
        "datasets_by_symbol": dict(snapshot.datasets_by_symbol),
        "datasets_by_timeframe": dict(snapshot.datasets_by_timeframe),
        "orphan_manifest_count": snapshot.orphan_manifest_count,
        "duplicate_identity_count": snapshot.duplicate_identity_count,
        "issue_count": snapshot.issue_count,
        "issues": list(snapshot.issues),
        "snapshot_entries": [_entry_to_dict(e) for e in snapshot.snapshot_entries],
    }


def snapshot_from_dict(d: dict[str, Any]) -> FleetSnapshot:
    """Reconstruct a ``FleetSnapshot`` from a dict (e.g. loaded from JSON).

    Raises:
        KeyError: If any required field is missing.
    """
    entries = tuple(
        FleetSnapshotEntry(
            dataset_path=str(e["dataset_path"]),
            manifest_path=e.get("manifest_path"),
            exchange=str(e["exchange"]),
            symbol=str(e["symbol"]),
            timeframe=str(e["timeframe"]),
            row_count=int(e["row_count"]),
            start_timestamp_utc=str(e["start_timestamp_utc"]),
            end_timestamp_utc=str(e["end_timestamp_utc"]),
            content_hash=str(e["content_hash"]),
            schema_hash=str(e["schema_hash"]),
            manifest_verified=bool(e["manifest_verified"]),
        )
        for e in d["snapshot_entries"]
    )
    return FleetSnapshot(
        snapshot_version=str(d["snapshot_version"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        registry_hash=str(d["registry_hash"]),
        registry_entries_hash=str(d["registry_entries_hash"]),
        total_datasets=int(d["total_datasets"]),
        total_manifests=int(d["total_manifests"]),
        symbols=tuple(str(s) for s in d["symbols"]),
        timeframes=tuple(str(t) for t in d["timeframes"]),
        datasets_by_symbol=dict(d["datasets_by_symbol"]),
        datasets_by_timeframe=dict(d["datasets_by_timeframe"]),
        orphan_manifest_count=int(d["orphan_manifest_count"]),
        duplicate_identity_count=int(d["duplicate_identity_count"]),
        issue_count=int(d["issue_count"]),
        issues=tuple(str(i) for i in d["issues"]),
        snapshot_entries=entries,
    )


def drift_to_dict(drift: FleetDrift) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``FleetDrift``."""
    return {
        "baseline_timestamp_utc": drift.baseline_timestamp_utc,
        "candidate_timestamp_utc": drift.candidate_timestamp_utc,
        "added_datasets": list(drift.added_datasets),
        "removed_datasets": list(drift.removed_datasets),
        "modified_datasets": list(drift.modified_datasets),
        "freshness_changes": [
            {
                "dataset_path": fc.dataset_path,
                "baseline_end_utc": fc.baseline_end_utc,
                "candidate_end_utc": fc.candidate_end_utc,
                "direction": fc.direction,
            }
            for fc in drift.freshness_changes
        ],
        "new_issues": list(drift.new_issues),
        "resolved_issues": list(drift.resolved_issues),
        "has_drift": drift.has_drift,
        "summary": drift.summary,
    }


def save_snapshot(snapshot: FleetSnapshot, path: Path) -> None:
    """Write a snapshot to a JSON file at ``path``.

    The parent directory is created if it does not exist.
    Keys are sorted for deterministic output.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot_to_dict(snapshot), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_snapshot(path: Path) -> FleetSnapshot:
    """Load a snapshot from a JSON file written by ``save_snapshot``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in snapshot file '{path}': {exc}") from exc
    return snapshot_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _snapshot_from_registry(
    registry: DatasetRegistry,
    now_utc: datetime,
) -> FleetSnapshot:
    """Build a FleetSnapshot from a DatasetRegistry."""
    entries = tuple(
        FleetSnapshotEntry(
            dataset_path=e.dataset_path,
            manifest_path=e.manifest_path,
            exchange=e.exchange,
            symbol=e.symbol,
            timeframe=e.timeframe,
            row_count=e.row_count,
            start_timestamp_utc=e.start_timestamp_utc,
            end_timestamp_utc=e.end_timestamp_utc,
            content_hash=e.content_hash,
            schema_hash=e.schema_hash,
            manifest_verified=e.manifest_verified,
        )
        for e in registry.entries
    )

    symbols = tuple(sorted({e.symbol for e in entries if e.symbol}))
    timeframes = tuple(sorted({e.timeframe for e in entries if e.timeframe}))
    datasets_by_symbol: dict[str, int] = {}
    datasets_by_timeframe: dict[str, int] = {}
    total_manifests = 0
    for e in entries:
        if e.symbol:
            datasets_by_symbol[e.symbol] = datasets_by_symbol.get(e.symbol, 0) + 1
        if e.timeframe:
            datasets_by_timeframe[e.timeframe] = datasets_by_timeframe.get(e.timeframe, 0) + 1
        if e.manifest_path is not None:
            total_manifests += 1

    registry_hash = _compute_registry_hash(registry)
    registry_entries_hash = _compute_entries_hash(entries)

    return FleetSnapshot(
        snapshot_version=SNAPSHOT_VERSION,
        generation_timestamp_utc=now_utc.isoformat(),
        registry_hash=registry_hash,
        registry_entries_hash=registry_entries_hash,
        total_datasets=registry.total_datasets,
        total_manifests=total_manifests,
        symbols=symbols,
        timeframes=timeframes,
        datasets_by_symbol=datasets_by_symbol,
        datasets_by_timeframe=datasets_by_timeframe,
        orphan_manifest_count=len(registry.orphan_manifests),
        duplicate_identity_count=len(registry.duplicate_identities),
        issue_count=len(registry.issues),
        issues=registry.issues,
        snapshot_entries=entries,
    )


def _compute_registry_hash(registry: DatasetRegistry) -> str:
    """SHA-256 of the full registry state (entries, issues, anomalies)."""
    state = {
        "total_datasets": registry.total_datasets,
        "issues": sorted(registry.issues),
        "orphan_manifests": sorted(registry.orphan_manifests),
        "duplicate_identities": [sorted(g) for g in sorted(registry.duplicate_identities)],
        "entries": [
            {
                "path": e.dataset_path,
                "content_hash": e.content_hash,
                "schema_hash": e.schema_hash,
                "row_count": e.row_count,
            }
            for e in registry.entries
        ],
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest()


def _compute_entries_hash(entries: tuple[FleetSnapshotEntry, ...]) -> str:
    """SHA-256 of dataset paths and content hashes only (identity-stable hash)."""
    state = [
        {"path": e.dataset_path, "content_hash": e.content_hash}
        for e in sorted(entries, key=lambda e: e.dataset_path)
    ]
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest()


def _entry_to_dict(entry: FleetSnapshotEntry) -> dict[str, Any]:
    return {
        "dataset_path": entry.dataset_path,
        "manifest_path": entry.manifest_path,
        "exchange": entry.exchange,
        "symbol": entry.symbol,
        "timeframe": entry.timeframe,
        "row_count": entry.row_count,
        "start_timestamp_utc": entry.start_timestamp_utc,
        "end_timestamp_utc": entry.end_timestamp_utc,
        "content_hash": entry.content_hash,
        "schema_hash": entry.schema_hash,
        "manifest_verified": entry.manifest_verified,
    }
