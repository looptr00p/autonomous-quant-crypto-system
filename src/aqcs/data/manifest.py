"""Deterministic canonical dataset identity manifests for OHLCV Parquet datasets.

A DatasetManifest certifies:
  - dataset identity  (exchange, symbol, timeframe, row span, timezone)
  - content integrity (SHA-256 over sorted OHLCV value bytes — content_hash)
  - schema identity   (SHA-256 over column names and Arrow type strings — schema_hash)
  - quality summary   (duplicate timestamp count, missing interval count)
  - generation provenance (UTC wall-clock injected via now_utc for testability)

Hashing guarantees
------------------
content_hash: identical OHLCV data → identical hash regardless of row order,
  parquet file metadata, pandas version, or system locale.  Implementation
  normalises timestamps to int64 milliseconds since epoch and OHLCV columns to
  little-endian float64 before hashing, so there is no floating-point
  serialisation ambiguity.

schema_hash: computed from the Arrow schema embedded in the Parquet file footer
  (column names + Arrow logical type strings, JSON-sorted).  Detects added,
  removed, or retyped columns.

Determinism requirements
------------------------
- Rows are sorted by timestamp before hashing.
- All numeric bytes are little-endian.
- Row count is included as a fixed-width prefix to guard against length extension.
- Timezone-naive or non-UTC timestamps cause an immediate ValueError — no
  implicit coercion.
- generation_timestamp_utc uses wall-clock time; inject now_utc in tests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from aqcs.data.validator import REQUIRED_COLUMNS

# ── Constants ─────────────────────────────────────────────────────────────────

MANIFEST_VERSION: str = "1"

# Maps ccxt-style timeframe strings to pandas date_range freq aliases.
_TIMEFRAME_TO_FREQ: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1D",
}

SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset(_TIMEFRAME_TO_FREQ)

# OHLCV value columns hashed in content_hash (metadata columns excluded).
_VALUE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

_UTC_NAMES: frozenset[str] = frozenset({"UTC", "UTC+00:00", "UTC-00:00", "+00:00"})


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DatasetManifest:
    """Immutable identity certificate for a single OHLCV Parquet dataset.

    All timestamp fields are ISO-8601 UTC strings.
    ``content_hash`` and ``schema_hash`` are lowercase hex SHA-256 digests.
    ``missing_interval_summary`` contains ``{"count": int}`` (plus
    ``"first_gap_utc"`` / ``"last_gap_utc"`` ISO-8601 strings when count > 0).
    """

    manifest_version: str
    exchange: str
    symbol: str
    timeframe: str
    timezone: str
    row_count: int
    start_timestamp_utc: str
    end_timestamp_utc: str
    schema_hash: str
    content_hash: str
    duplicate_count: int
    missing_interval_summary: dict[str, Any]
    generation_timestamp_utc: str


@dataclass(frozen=True)
class ManifestVerificationResult:
    """Outcome of verifying a Parquet file against a reference DatasetManifest.

    ``verified`` is True only when all checked fields match exactly.
    ``mismatches`` lists (field_name, expected, actual) triples for each
    field that differs.
    """

    verified: bool
    mismatches: list[tuple[str, str, str]]


# ── Public API ────────────────────────────────────────────────────────────────


def generate_manifest(
    path: Path,
    symbol: str,
    timeframe: str,
    *,
    now_utc: datetime | None = None,
) -> DatasetManifest:
    """Generate a deterministic identity manifest for a local OHLCV Parquet file.

    Args:
        path: Path to the Parquet file.
        symbol: Expected market symbol (e.g. ``"BTC/USDT"``).  Stored as-is;
                the caller is responsible for consistency with the file content.
        timeframe: Expected candle timeframe (e.g. ``"1d"``).  Must be in
                   ``SUPPORTED_TIMEFRAMES`` to enable missing-interval counting.
        now_utc: Reference UTC datetime for ``generation_timestamp_utc``.
                 Defaults to ``datetime.now(UTC)``.  Inject a fixed value in
                 tests to ensure fully deterministic manifest output.

    Returns:
        DatasetManifest with all fields populated.

    Raises:
        ValueError: If ``path`` does not exist, cannot be read as Parquet, has
                    missing required columns, is empty, or contains non-UTC
                    timestamps.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Parquet file not found: {path}")

    try:
        schema_hash = _compute_schema_hash(path)
        df = pd.read_parquet(path)
    except Exception as exc:
        raise ValueError(f"Cannot read Parquet file '{path}': {exc}") from exc

    if df.empty:
        raise ValueError(f"Parquet file is empty (0 rows): {path}")

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns {missing_cols} in '{path}'")

    _assert_utc(df, path)

    df_sorted = df.sort_values("timestamp").reset_index(drop=True)

    content_hash = _compute_content_hash(df_sorted)
    duplicate_count = int(df["timestamp"].duplicated().sum())
    missing_summary = _compute_missing_intervals(df_sorted, timeframe)

    exchange = str(df_sorted["exchange"].iloc[0])
    start_ts = df_sorted["timestamp"].min().to_pydatetime()
    end_ts = df_sorted["timestamp"].max().to_pydatetime()

    _now = now_utc if now_utc is not None else datetime.now(UTC)

    return DatasetManifest(
        manifest_version=MANIFEST_VERSION,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        timezone="UTC",
        row_count=len(df_sorted),
        start_timestamp_utc=start_ts.isoformat(),
        end_timestamp_utc=end_ts.isoformat(),
        schema_hash=schema_hash,
        content_hash=content_hash,
        duplicate_count=duplicate_count,
        missing_interval_summary=missing_summary,
        generation_timestamp_utc=_now.isoformat(),
    )


def verify_manifest(
    path: Path,
    reference: DatasetManifest,
) -> ManifestVerificationResult:
    """Verify a Parquet file's integrity against a reference DatasetManifest.

    Generates a fresh manifest from ``path`` (reusing
    ``reference.generation_timestamp_utc`` so the non-deterministic field does
    not cause a spurious mismatch) and compares every field.

    Args:
        path: Path to the Parquet file to verify.
        reference: Previously generated manifest to compare against.

    Returns:
        ManifestVerificationResult.  ``verified`` is True only when all fields
        match.  ``mismatches`` is an empty list when verified.
    """
    try:
        gen_ts = datetime.fromisoformat(reference.generation_timestamp_utc)
    except ValueError:
        gen_ts = datetime.now(UTC)

    fresh = generate_manifest(
        path,
        symbol=reference.symbol,
        timeframe=reference.timeframe,
        now_utc=gen_ts,
    )

    checked_fields = (
        "manifest_version",
        "exchange",
        "symbol",
        "timeframe",
        "timezone",
        "row_count",
        "start_timestamp_utc",
        "end_timestamp_utc",
        "schema_hash",
        "content_hash",
        "duplicate_count",
    )

    mismatches: list[tuple[str, str, str]] = []
    for field in checked_fields:
        expected = str(getattr(reference, field))
        actual = str(getattr(fresh, field))
        if expected != actual:
            mismatches.append((field, expected, actual))

    # Compare missing_interval_summary count separately (dict comparison)
    ref_count = reference.missing_interval_summary.get("count", 0)
    fresh_count = fresh.missing_interval_summary.get("count", 0)
    if ref_count != fresh_count:
        mismatches.append(
            (
                "missing_interval_summary.count",
                str(ref_count),
                str(fresh_count),
            )
        )

    return ManifestVerificationResult(
        verified=len(mismatches) == 0,
        mismatches=mismatches,
    )


def manifest_to_dict(manifest: DatasetManifest) -> dict[str, Any]:
    """Return a JSON-serializable dict from a DatasetManifest.

    Output is deterministic when ``json.dumps(..., sort_keys=True)`` is used.
    """
    return {
        "manifest_version": manifest.manifest_version,
        "exchange": manifest.exchange,
        "symbol": manifest.symbol,
        "timeframe": manifest.timeframe,
        "timezone": manifest.timezone,
        "row_count": manifest.row_count,
        "start_timestamp_utc": manifest.start_timestamp_utc,
        "end_timestamp_utc": manifest.end_timestamp_utc,
        "schema_hash": manifest.schema_hash,
        "content_hash": manifest.content_hash,
        "duplicate_count": manifest.duplicate_count,
        "missing_interval_summary": dict(manifest.missing_interval_summary),
        "generation_timestamp_utc": manifest.generation_timestamp_utc,
    }


def manifest_from_dict(d: dict[str, Any]) -> DatasetManifest:
    """Reconstruct a DatasetManifest from a dict (e.g. loaded from JSON).

    Raises:
        KeyError: If any required field is missing from ``d``.
        TypeError: If a field has an incompatible type.
    """
    return DatasetManifest(
        manifest_version=str(d["manifest_version"]),
        exchange=str(d["exchange"]),
        symbol=str(d["symbol"]),
        timeframe=str(d["timeframe"]),
        timezone=str(d["timezone"]),
        row_count=int(d["row_count"]),
        start_timestamp_utc=str(d["start_timestamp_utc"]),
        end_timestamp_utc=str(d["end_timestamp_utc"]),
        schema_hash=str(d["schema_hash"]),
        content_hash=str(d["content_hash"]),
        duplicate_count=int(d["duplicate_count"]),
        missing_interval_summary=dict(d["missing_interval_summary"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
    )


def save_manifest(manifest: DatasetManifest, path: Path) -> None:
    """Write a manifest to a JSON file at ``path``.

    Keys are sorted for deterministic output.  Raises ``OSError`` if the
    directory does not exist or cannot be written.
    """
    path = Path(path)
    path.write_text(
        json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_manifest(path: Path) -> DatasetManifest:
    """Load a manifest from a JSON file previously written by ``save_manifest``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in manifest file '{path}': {exc}") from exc
    return manifest_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _assert_utc(df: pd.DataFrame, path: Path) -> None:
    """Raise ValueError if 'timestamp' column is absent, naive, or non-UTC."""
    if "timestamp" not in df.columns:
        raise ValueError(f"'timestamp' column missing in '{path}'")
    tz = df["timestamp"].dt.tz
    if tz is None:
        raise ValueError(f"'timestamp' column in '{path}' is timezone-naive — UTC required")
    if not _is_utc(tz):
        raise ValueError(f"'timestamp' column in '{path}' uses timezone '{tz}' — UTC required")


def _is_utc(tz: object) -> bool:
    """Return True only when tz is unambiguously UTC with zero offset."""
    if tz is UTC:
        return True
    return str(tz).upper() in _UTC_NAMES


def _compute_schema_hash(path: Path) -> str:
    """SHA-256 of the Parquet Arrow schema (column names + type strings, sorted).

    Reads only the Parquet file footer — no row-data I/O.
    """
    schema = pq.read_schema(path)  # type: ignore[no-untyped-call]
    fields = sorted((f.name, str(f.type)) for f in schema)
    schema_bytes = json.dumps(fields, sort_keys=True).encode("utf-8")
    return hashlib.sha256(schema_bytes).hexdigest()


def _compute_content_hash(df_sorted: pd.DataFrame) -> str:
    """SHA-256 over sorted OHLCV data in canonical little-endian byte format.

    Input must already be sorted by timestamp (ascending).

    Hashing order:
      1. row_count as little-endian uint64  (guards against length extension)
      2. timestamp column as int64 milliseconds-since-epoch, little-endian
      3. open, high, low, close, volume columns as float64 little-endian

    Only columns present in ``_VALUE_COLUMNS`` are included; metadata columns
    (symbol, timeframe, exchange) are excluded because they are already captured
    in the manifest fields themselves.
    """
    h = hashlib.sha256()
    row_count = len(df_sorted)
    h.update(row_count.to_bytes(8, byteorder="little", signed=False))

    # Timestamps → milliseconds since UTC epoch → int64 little-endian.
    # np.asarray bypasses pandas DatetimeArray (ExtensionArray) so mypy is happy.
    ts_np: np.ndarray = np.asarray(df_sorted["timestamp"], dtype="datetime64[ms]")
    h.update(ts_np.view(np.int64).astype("<i8").tobytes())

    # OHLCV value columns → float64 little-endian.
    for col in _VALUE_COLUMNS:
        arr: np.ndarray = np.asarray(df_sorted[col], dtype=np.float64)
        h.update(arr.astype("<f8").tobytes())

    return h.hexdigest()


def _compute_missing_intervals(df_sorted: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    """Count missing candle intervals between first and last timestamp.

    Returns ``{"count": 0}`` when no gaps are found, timeframe is unsupported,
    or the dataset has fewer than 2 rows.

    For datasets with gaps, returns:
        ``{"count": N, "first_gap_utc": "<ISO-8601>", "last_gap_utc": "<ISO-8601>"}``
    """
    freq = _TIMEFRAME_TO_FREQ.get(timeframe)
    if freq is None or len(df_sorted) < 2:
        return {"count": 0}

    first_ts = df_sorted["timestamp"].min()
    last_ts = df_sorted["timestamp"].max()
    expected = pd.date_range(start=first_ts, end=last_ts, freq=freq, tz="UTC")
    actual: set[pd.Timestamp] = set(df_sorted["timestamp"].tolist())
    missing = sorted(t for t in expected if t not in actual)

    if not missing:
        return {"count": 0}

    return {
        "count": len(missing),
        "first_gap_utc": missing[0].isoformat(),
        "last_gap_utc": missing[-1].isoformat(),
    }
