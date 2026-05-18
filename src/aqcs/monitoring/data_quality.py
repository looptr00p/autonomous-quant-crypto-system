"""Deterministic OHLCV data-quality monitoring for local Parquet datasets.

Checks performed:
  1. File is readable as Parquet
  2. Required OHLCV columns present
  3. Dataset is non-empty
  4. UTC-aware timestamps
  5. Monotonically increasing timestamps
  6. Duplicate timestamp count
  7. Missing interval count (exact, via expected date range)
  8. NaN counts per value column
  9. Freshness lag (seconds since last timestamp)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from aqcs.data.validator import REQUIRED_COLUMNS

# ── Constants ─────────────────────────────────────────────────────────────────

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}

# Pandas frequency aliases for exact missing-bar enumeration.
_TIMEFRAME_FREQ: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset(_TIMEFRAME_SECONDS)

# Value columns included in NaN counting (excludes metadata columns).
_VALUE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

# UTC timezone name aliases (uppercase for comparison).
_UTC_NAMES: frozenset[str] = frozenset({"UTC", "UTC+00:00", "UTC-00:00", "+00:00"})

# Freshness lag threshold: warn if lag > 2× expected interval.
_STALE_MULTIPLIER: int = 2


# ── Report model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DataQualityReport:
    """Deterministic quality summary for a single OHLCV Parquet dataset.

    ``passed`` is True when ``errors`` is empty.
    ``warnings`` are advisory — they do not affect ``passed``.
    """

    parquet_path: str
    row_count: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    expected_interval: str
    missing_interval_count: int
    duplicate_timestamp_count: int
    nan_count_by_column: dict[str, int]
    required_columns_present: bool
    utc_valid: bool
    monotonic: bool
    freshness_lag_seconds: float | None
    passed: bool
    warnings: list[str]
    errors: list[str]


def report_to_dict(report: DataQualityReport) -> dict[str, Any]:
    """Return a JSON-serializable dict from a DataQualityReport.

    Datetime fields are serialised to ISO-8601 strings.
    Output is deterministic when ``json.dumps(..., sort_keys=True)`` is used.
    """
    return {
        "parquet_path": report.parquet_path,
        "row_count": report.row_count,
        "first_timestamp": (
            report.first_timestamp.isoformat() if report.first_timestamp is not None else None
        ),
        "last_timestamp": (
            report.last_timestamp.isoformat() if report.last_timestamp is not None else None
        ),
        "expected_interval": report.expected_interval,
        "missing_interval_count": report.missing_interval_count,
        "duplicate_timestamp_count": report.duplicate_timestamp_count,
        "nan_count_by_column": report.nan_count_by_column,
        "required_columns_present": report.required_columns_present,
        "utc_valid": report.utc_valid,
        "monotonic": report.monotonic,
        "freshness_lag_seconds": report.freshness_lag_seconds,
        "passed": report.passed,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }


# ── Core check ────────────────────────────────────────────────────────────────


def check_ohlcv_parquet_quality(
    path: Path,
    timeframe: str,
    *,
    now_utc: datetime | None = None,
) -> DataQualityReport:
    """Run deterministic data-quality checks on a local OHLCV Parquet file.

    Args:
        path: Path to the Parquet file.
        timeframe: Expected candle timeframe. Must be one of the supported
                   values in ``SUPPORTED_TIMEFRAMES``.
        now_utc: Reference UTC time for freshness-lag computation.
                 Defaults to ``datetime.now(UTC)``. Inject a fixed value
                 in tests to obtain fully deterministic output.

    Returns:
        DataQualityReport with all quality metrics populated.
        ``passed`` is True when no structural errors are found.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── 1. Validate timeframe ─────────────────────────────────────────────────
    if timeframe not in _TIMEFRAME_SECONDS:
        return DataQualityReport(
            parquet_path=str(path),
            row_count=0,
            first_timestamp=None,
            last_timestamp=None,
            expected_interval=timeframe,
            missing_interval_count=0,
            duplicate_timestamp_count=0,
            nan_count_by_column={},
            required_columns_present=False,
            utc_valid=False,
            monotonic=False,
            freshness_lag_seconds=None,
            passed=False,
            warnings=[],
            errors=[
                f"Unsupported timeframe '{timeframe}'. " f"Supported: {sorted(_TIMEFRAME_SECONDS)}"
            ],
        )

    # ── 2. Read parquet ───────────────────────────────────────────────────────
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        return DataQualityReport(
            parquet_path=str(path),
            row_count=0,
            first_timestamp=None,
            last_timestamp=None,
            expected_interval=timeframe,
            missing_interval_count=0,
            duplicate_timestamp_count=0,
            nan_count_by_column={},
            required_columns_present=False,
            utc_valid=False,
            monotonic=False,
            freshness_lag_seconds=None,
            passed=False,
            warnings=[],
            errors=[f"Cannot read Parquet file: {exc}"],
        )

    row_count = len(df)

    # ── 3. Required columns ───────────────────────────────────────────────────
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    required_columns_present = not missing_cols
    if not required_columns_present:
        errors.append(f"Missing required columns: {missing_cols}")

    # ── 4. Empty dataset ──────────────────────────────────────────────────────
    if row_count == 0:
        errors.append("Dataset is empty (0 rows)")
        return DataQualityReport(
            parquet_path=str(path),
            row_count=0,
            first_timestamp=None,
            last_timestamp=None,
            expected_interval=timeframe,
            missing_interval_count=0,
            duplicate_timestamp_count=0,
            nan_count_by_column={col: 0 for col in _VALUE_COLUMNS if col in df.columns},
            required_columns_present=required_columns_present,
            utc_valid=False,
            monotonic=False,
            freshness_lag_seconds=None,
            passed=False,
            warnings=warnings,
            errors=errors,
        )

    # ── 5. UTC-aware timestamps ───────────────────────────────────────────────
    utc_valid = False
    if "timestamp" in df.columns:
        try:
            tz = df["timestamp"].dt.tz
            if tz is None:
                errors.append("Timestamps are timezone-naive — UTC required")
            elif str(tz).upper() not in _UTC_NAMES:
                errors.append(f"Timestamps use timezone '{tz}' — UTC required")
            else:
                utc_valid = True
        except AttributeError:
            errors.append("'timestamp' column is not a datetime type")

    # ── 6. Monotonic timestamps ───────────────────────────────────────────────
    monotonic = False
    if "timestamp" in df.columns and utc_valid:
        monotonic = bool(df["timestamp"].is_monotonic_increasing)
        if not monotonic:
            errors.append("Timestamps are not monotonically increasing")

    # ── 7. Duplicate timestamps ───────────────────────────────────────────────
    duplicate_timestamp_count = 0
    if "timestamp" in df.columns:
        duplicate_timestamp_count = int(df["timestamp"].duplicated().sum())
        if duplicate_timestamp_count > 0:
            warnings.append(f"{duplicate_timestamp_count} duplicate timestamp(s) detected")

    # ── 8. Missing intervals (exact count via expected date range) ────────────
    #
    # Builds the full expected date range and counts timestamps that are
    # present in the expected range but absent in the actual data.
    # Requires UTC-valid, monotonic data with at least 2 rows.
    missing_interval_count = 0
    if "timestamp" in df.columns and utc_valid and monotonic and row_count > 1:
        freq = _TIMEFRAME_FREQ[timeframe]
        first_ts = df["timestamp"].min()
        last_ts = df["timestamp"].max()
        expected = pd.date_range(start=first_ts, end=last_ts, freq=freq, tz="UTC")
        actual_set: set[pd.Timestamp] = set(df["timestamp"].tolist())
        missing_interval_count = sum(1 for t in expected if t not in actual_set)
        if missing_interval_count > 0:
            warnings.append(
                f"{missing_interval_count} missing interval(s) for timeframe '{timeframe}'"
            )

    # ── 9. NaN counts per value column ────────────────────────────────────────
    nan_count_by_column: dict[str, int] = {
        col: int(df[col].isna().sum()) for col in _VALUE_COLUMNS if col in df.columns
    }
    for col, n in nan_count_by_column.items():
        if n > 0:
            warnings.append(f"{n} NaN value(s) in column '{col}'")

    # ── 10. Timestamps ────────────────────────────────────────────────────────
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    if "timestamp" in df.columns and utc_valid:
        first_timestamp = df["timestamp"].min().to_pydatetime()
        last_timestamp = df["timestamp"].max().to_pydatetime()

    # ── 11. Freshness lag ─────────────────────────────────────────────────────
    freshness_lag_seconds: float | None = None
    if last_timestamp is not None:
        _now = now_utc if now_utc is not None else datetime.now(UTC)
        freshness_lag_seconds = (_now - last_timestamp).total_seconds()
        stale_threshold = _TIMEFRAME_SECONDS[timeframe] * _STALE_MULTIPLIER
        if freshness_lag_seconds > stale_threshold:
            warnings.append(
                f"Dataset may be stale: last timestamp is "
                f"{freshness_lag_seconds:.0f}s ago "
                f"(threshold: {stale_threshold}s for '{timeframe}')"
            )

    passed = len(errors) == 0

    return DataQualityReport(
        parquet_path=str(path),
        row_count=row_count,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        expected_interval=timeframe,
        missing_interval_count=missing_interval_count,
        duplicate_timestamp_count=duplicate_timestamp_count,
        nan_count_by_column=nan_count_by_column,
        required_columns_present=required_columns_present,
        utc_valid=utc_valid,
        monotonic=monotonic,
        freshness_lag_seconds=freshness_lag_seconds,
        passed=passed,
        warnings=warnings,
        errors=errors,
    )
