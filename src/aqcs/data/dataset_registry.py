"""Deterministic local dataset registry for AQCS OHLCV datasets.

The registry provides a reproducible inventory of all locally available OHLCV
Parquet datasets and their associated manifests.  It supports:

  - deterministic dataset discovery and ordering
  - manifest linkage validation
  - orphan manifest detection (manifest with no matching parquet)
  - missing manifest detection (parquet with no matching manifest)
  - duplicate identity detection (two parquets with the same content_hash)
  - dataset fleet auditing

The registry is read-only: it never modifies parquet files or manifests.

Naming convention
-----------------
The registry pairs Parquet files with manifests by file stem:

  BTC_USDT_1h.parquet  ←→  BTC_USDT_1h_manifest.json

Both files must reside in the **same directory**.  Manifests that do not
follow this convention are reported as orphans.

Determinism
-----------
- Registry entries are sorted by ``(symbol, timeframe, dataset_path)``.
- Duplicate-identity groups are sorted by path within each group.
- JSON output uses ``sort_keys=True``.
- ``generation_timestamp_utc`` is the only wall-clock value; inject
  ``now_utc`` in tests for fully deterministic output.
- Filesystem traversal uses ``sorted()`` for cross-platform stability.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from aqcs.data.manifest import load_manifest, verify_manifest

# ── Version ───────────────────────────────────────────────────────────────────

REGISTRY_VERSION: str = "1"


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DatasetRegistryEntry:
    """Metadata record for a single locally available OHLCV Parquet dataset.

    All paths are relative to the registry's ``data_dir``.
    ``has_manifest`` is True when a manifest file was found alongside the parquet.
    ``manifest_verified`` is True when manifest verification was requested and
    the content_hash / schema_hash matched the parquet.  It is False either when
    no manifest is present, when verification was not requested, or when
    verification failed.
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
    manifest_version: str
    generation_timestamp_utc: str
    has_manifest: bool
    manifest_verified: bool


@dataclass(frozen=True)
class DatasetRegistry:
    """Deterministic inventory of all locally available OHLCV datasets.

    ``entries`` is sorted by ``(symbol, timeframe, dataset_path)``.
    ``orphan_manifests`` lists manifest files with no matching parquet.
    ``duplicate_identities`` lists groups of dataset paths that share the same
    non-empty ``content_hash``.
    ``issues`` is a human-readable list of all anomalies detected.
    """

    registry_version: str
    data_dir: str
    generation_timestamp_utc: str
    total_datasets: int
    entries: tuple[DatasetRegistryEntry, ...]
    orphan_manifests: tuple[str, ...]
    duplicate_identities: tuple[tuple[str, ...], ...]
    issues: tuple[str, ...]


# ── Public API ────────────────────────────────────────────────────────────────


def scan_directory(
    data_dir: Path,
    *,
    verify_manifests: bool = False,
    now_utc: datetime | None = None,
) -> DatasetRegistry:
    """Scan ``data_dir`` recursively and return a deterministic registry.

    Args:
        data_dir: Root directory to scan for Parquet files and manifests.
        verify_manifests: When True, each manifest is verified against its
            parquet via ``verify_manifest``.  This re-reads every parquet file
            and is therefore slower than a plain scan.  Mismatches are recorded
            in ``issues`` and the entry's ``manifest_verified`` is set to False.
            When False, ``manifest_verified`` is always False (not checked).
        now_utc: UTC reference time for the registry's
            ``generation_timestamp_utc``.  Defaults to ``datetime.now(UTC)``.
            Inject a fixed value in tests for fully deterministic output.

    Returns:
        DatasetRegistry with all entries, issues, and anomaly lists populated.
    """
    data_dir = Path(data_dir)
    _now = now_utc if now_utc is not None else datetime.now(UTC)
    issues: list[str] = []

    # ── 1. Enumerate files (sorted for cross-platform determinism) ────────────
    parquet_files = sorted(data_dir.rglob("*.parquet"))
    manifest_files = sorted(data_dir.rglob("*_manifest.json"))

    # ── 2. Map stem → manifest path ────────────────────────────────────────────
    # Stem = manifest filename with "_manifest.json" stripped.
    # Only manifests in the same directory as a parquet can be auto-matched.
    matched_manifests: set[Path] = set()

    # ── 3. Build registry entries ─────────────────────────────────────────────
    raw_entries: list[DatasetRegistryEntry] = []

    for pq_path in parquet_files:
        rel_pq = str(pq_path.relative_to(data_dir))
        stem = pq_path.stem
        candidate_manifest = pq_path.parent / f"{stem}_manifest.json"

        if candidate_manifest.exists():
            matched_manifests.add(candidate_manifest)
            rel_mf = str(candidate_manifest.relative_to(data_dir))
            entry = _entry_from_manifest(
                pq_path,
                candidate_manifest,
                rel_pq,
                rel_mf,
                verify_manifests,
                issues,
            )
        else:
            issues.append(f"Missing manifest for dataset '{rel_pq}'")
            entry = _entry_no_manifest(pq_path, rel_pq, issues)

        raw_entries.append(entry)

    # ── 4. Detect orphan manifests ────────────────────────────────────────────
    orphan_paths: list[str] = []
    for mf in manifest_files:
        if mf not in matched_manifests:
            rel_mf = str(mf.relative_to(data_dir))
            orphan_paths.append(rel_mf)
            issues.append(f"Orphan manifest (no matching parquet): '{rel_mf}'")
    orphan_paths.sort()

    # ── 5. Sort entries deterministically ─────────────────────────────────────
    sorted_entries = tuple(
        sorted(
            raw_entries,
            key=lambda e: (e.symbol, e.timeframe, e.dataset_path),
        )
    )

    # ── 6. Detect duplicate identities ───────────────────────────────────────
    hash_to_paths: dict[str, list[str]] = defaultdict(list)
    for entry in sorted_entries:
        if entry.content_hash:
            hash_to_paths[entry.content_hash].append(entry.dataset_path)

    duplicate_groups: list[tuple[str, ...]] = []
    for paths in hash_to_paths.values():
        if len(paths) > 1:
            group = tuple(sorted(paths))
            duplicate_groups.append(group)
            issues.append(f"Duplicate dataset identity (same content_hash): {list(group)}")
    # Sort groups lexicographically by their first element
    duplicate_groups.sort(key=lambda g: g[0])

    return DatasetRegistry(
        registry_version=REGISTRY_VERSION,
        data_dir=str(data_dir),
        generation_timestamp_utc=_now.isoformat(),
        total_datasets=len(sorted_entries),
        entries=sorted_entries,
        orphan_manifests=tuple(orphan_paths),
        duplicate_identities=tuple(duplicate_groups),
        issues=tuple(issues),
    )


def registry_to_dict(registry: DatasetRegistry) -> dict[str, Any]:
    """Return a JSON-serializable dict from a DatasetRegistry.

    Output is deterministic when ``json.dumps(..., sort_keys=True)`` is used.
    """
    return {
        "registry_version": registry.registry_version,
        "data_dir": registry.data_dir,
        "generation_timestamp_utc": registry.generation_timestamp_utc,
        "total_datasets": registry.total_datasets,
        "entries": [_entry_to_dict(e) for e in registry.entries],
        "orphan_manifests": list(registry.orphan_manifests),
        "duplicate_identities": [list(g) for g in registry.duplicate_identities],
        "issues": list(registry.issues),
    }


def registry_from_dict(d: dict[str, Any]) -> DatasetRegistry:
    """Reconstruct a DatasetRegistry from a dict (e.g. loaded from JSON).

    Raises:
        KeyError: If any required field is missing.
        TypeError: If a field has an incompatible type.
    """
    entries = tuple(
        DatasetRegistryEntry(
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
            manifest_version=str(e["manifest_version"]),
            generation_timestamp_utc=str(e["generation_timestamp_utc"]),
            has_manifest=bool(e["has_manifest"]),
            manifest_verified=bool(e["manifest_verified"]),
        )
        for e in d["entries"]
    )
    return DatasetRegistry(
        registry_version=str(d["registry_version"]),
        data_dir=str(d["data_dir"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        total_datasets=int(d["total_datasets"]),
        entries=entries,
        orphan_manifests=tuple(str(p) for p in d["orphan_manifests"]),
        duplicate_identities=tuple(tuple(str(p) for p in g) for g in d["duplicate_identities"]),
        issues=tuple(str(i) for i in d["issues"]),
    )


def save_registry(registry: DatasetRegistry, path: Path) -> None:
    """Write a registry to a JSON file at ``path``.

    Keys are sorted for deterministic output.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry_to_dict(registry), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_registry(path: Path) -> DatasetRegistry:
    """Load a registry from a JSON file written by ``save_registry``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in registry file '{path}': {exc}") from exc
    return registry_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _entry_to_dict(entry: DatasetRegistryEntry) -> dict[str, Any]:
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
        "manifest_version": entry.manifest_version,
        "generation_timestamp_utc": entry.generation_timestamp_utc,
        "has_manifest": entry.has_manifest,
        "manifest_verified": entry.manifest_verified,
    }


def _entry_from_manifest(
    pq_path: Path,
    manifest_path: Path,
    rel_pq: str,
    rel_mf: str,
    verify: bool,
    issues: list[str],
) -> DatasetRegistryEntry:
    """Build a registry entry from a parquet + its manifest."""
    try:
        manifest = load_manifest(manifest_path)
    except (ValueError, KeyError) as exc:
        issues.append(f"Malformed manifest for '{rel_pq}': {exc}")
        return _entry_no_manifest(pq_path, rel_pq, issues, manifest_path=rel_mf)

    manifest_verified = False
    if verify:
        try:
            vresult = verify_manifest(pq_path, manifest)
            manifest_verified = vresult.verified
            if not vresult.verified:
                mismatch_fields = [f for f, _, _ in vresult.mismatches]
                issues.append(
                    f"Manifest mismatch for '{rel_pq}': " f"fields differ: {mismatch_fields}"
                )
        except ValueError as exc:
            issues.append(f"Manifest verification failed for '{rel_pq}': {exc}")

    return DatasetRegistryEntry(
        dataset_path=rel_pq,
        manifest_path=rel_mf,
        exchange=manifest.exchange,
        symbol=manifest.symbol,
        timeframe=manifest.timeframe,
        row_count=manifest.row_count,
        start_timestamp_utc=manifest.start_timestamp_utc,
        end_timestamp_utc=manifest.end_timestamp_utc,
        content_hash=manifest.content_hash,
        schema_hash=manifest.schema_hash,
        manifest_version=manifest.manifest_version,
        generation_timestamp_utc=manifest.generation_timestamp_utc,
        has_manifest=True,
        manifest_verified=manifest_verified,
    )


def _entry_no_manifest(
    pq_path: Path,
    rel_pq: str,
    issues: list[str],
    *,
    manifest_path: str | None = None,
) -> DatasetRegistryEntry:
    """Build a best-effort registry entry for a parquet without a valid manifest."""
    meta = _read_parquet_meta(pq_path, rel_pq, issues)
    return DatasetRegistryEntry(
        dataset_path=rel_pq,
        manifest_path=manifest_path,
        exchange=meta.get("exchange", ""),
        symbol=meta.get("symbol", ""),
        timeframe=meta.get("timeframe", ""),
        row_count=meta.get("row_count", 0),
        start_timestamp_utc=meta.get("start_timestamp_utc", ""),
        end_timestamp_utc=meta.get("end_timestamp_utc", ""),
        content_hash="",
        schema_hash="",
        manifest_version="",
        generation_timestamp_utc="",
        has_manifest=manifest_path is not None,
        manifest_verified=False,
    )


def _read_parquet_meta(
    path: Path,
    rel_path: str,
    issues: list[str],
) -> dict[str, Any]:
    """Extract basic metadata from a parquet file (no manifest required)."""
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        issues.append(f"Cannot read parquet '{rel_path}': {exc}")
        return {}

    if df.empty:
        issues.append(f"Parquet '{rel_path}' is empty")
        return {}

    meta: dict[str, Any] = {
        "exchange": str(df["exchange"].iloc[0]) if "exchange" in df.columns else "",
        "symbol": str(df["symbol"].iloc[0]) if "symbol" in df.columns else "",
        "timeframe": str(df["timeframe"].iloc[0]) if "timeframe" in df.columns else "",
        "row_count": len(df),
    }

    if "timestamp" in df.columns:
        try:
            tz = df["timestamp"].dt.tz
            if tz is not None:
                meta["start_timestamp_utc"] = df["timestamp"].min().to_pydatetime().isoformat()
                meta["end_timestamp_utc"] = df["timestamp"].max().to_pydatetime().isoformat()
            else:
                issues.append(f"Parquet '{rel_path}' has timezone-naive timestamps")
                meta["start_timestamp_utc"] = ""
                meta["end_timestamp_utc"] = ""
        except Exception:
            meta["start_timestamp_utc"] = ""
            meta["end_timestamp_utc"] = ""

    return meta
