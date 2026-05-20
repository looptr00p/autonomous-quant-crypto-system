"""Adversarial: timestamp and data-structure corruption.

Verifies that AQCS rejects or flags malformed OHLCV data at every entry
point rather than silently propagating corrupt inputs.  Each test
deliberately introduces a specific data violation and asserts the system
fails loudly with a clear diagnostic.

Corruption classes covered:
- empty dataset
- missing required columns
- null values in OHLCV columns
- naive (tz-unaware) timestamps
- non-UTC timezone
- duplicate timestamps
- non-strictly-increasing timestamps
- zero or negative prices
- high < low (inverted range)
- open outside [low, high]
- negative volume
- symbol/timeframe metadata mismatch
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aqcs.data.manifest import generate_manifest
from aqcs.data.validator import validate_ohlcv

from .conftest import FIXED_NOW

_SYMBOL = "BTC/USDT"
_EXCHANGE = "binance"
_TIMEFRAME = "1d"
_N = 30


# ── Helpers ───────────────────────────────────────────────────────────────────


def _clean(n: int = _N) -> pd.DataFrame:
    """Return a valid OHLCV DataFrame — the clean baseline for corruption."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    close = np.linspace(45_000.0, 50_000.0, n)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": np.linspace(100.0, 200.0, n),
            "symbol": _SYMBOL,
            "timeframe": _TIMEFRAME,
            "exchange": _EXCHANGE,
        }
    )


def _corrupt(df: pd.DataFrame, **col_overrides: object) -> pd.DataFrame:
    """Return a copy of df with one or more columns replaced."""
    out = df.copy()
    for col, val in col_overrides.items():
        out[col] = val
    return out


def _validate(df: pd.DataFrame) -> tuple[bool, list[str]]:
    r = validate_ohlcv(df, _SYMBOL, _TIMEFRAME)
    return r.is_valid, r.errors


# ── Sanity check — clean data passes ─────────────────────────────────────────


class TestCleanDataPasses:
    def test_valid_ohlcv_passes_all_checks(self) -> None:
        valid, errors = _validate(_clean())
        assert valid is True, f"Clean OHLCV should pass validation; errors: {errors}"

    def test_validator_result_has_required_attributes(self) -> None:
        r = validate_ohlcv(_clean(), _SYMBOL, _TIMEFRAME)
        assert hasattr(r, "is_valid")
        assert hasattr(r, "errors")
        assert hasattr(r, "warnings")


# ── Structural corruption ─────────────────────────────────────────────────────


class TestStructuralCorruption:
    def test_empty_dataset_rejected(self) -> None:
        empty = _clean().iloc[0:0]
        valid, errors = _validate(empty)
        assert valid is False, "Empty dataset must be rejected"
        assert errors, "Empty dataset must produce error messages"

    def test_missing_column_rejected(self) -> None:
        df = _clean().drop(columns=["close"])
        valid, errors = _validate(df)
        assert valid is False
        assert any("close" in e.lower() or "column" in e.lower() for e in errors)

    def test_missing_timestamp_column_rejected(self) -> None:
        df = _clean().drop(columns=["timestamp"])
        valid, errors = _validate(df)
        assert valid is False

    def test_null_in_close_rejected(self) -> None:
        df = _clean().copy()
        df.loc[5, "close"] = float("nan")
        valid, errors = _validate(df)
        assert valid is False
        assert errors

    def test_null_in_volume_rejected(self) -> None:
        df = _clean().copy()
        df.loc[0, "volume"] = float("nan")
        valid, errors = _validate(df)
        assert valid is False


# ── Timestamp corruption ──────────────────────────────────────────────────────


class TestTimestampCorruption:
    def test_naive_timestamps_rejected(self) -> None:
        df = _clean().copy()
        # Strip timezone: naive timestamps
        df["timestamp"] = pd.date_range("2024-01-01", periods=_N, freq="1D")
        valid, errors = _validate(df)
        assert valid is False, "Naive timestamps must be rejected"
        assert errors

    def test_non_utc_timezone_rejected(self) -> None:
        df = _clean().copy()
        df["timestamp"] = pd.date_range("2024-01-01", periods=_N, freq="1D", tz="US/Eastern")
        valid, errors = _validate(df)
        assert valid is False, "Non-UTC timezone must be rejected"
        assert errors

    def test_duplicate_timestamps_rejected(self) -> None:
        df = _clean().copy()
        timestamps = list(df["timestamp"])
        timestamps[5] = timestamps[4]  # duplicate bar 4 and 5
        df["timestamp"] = timestamps
        valid, errors = _validate(df)
        assert valid is False, "Duplicate timestamps must be rejected"
        assert errors

    def test_unordered_timestamps_rejected(self) -> None:
        df = _clean().copy()
        ts = list(df["timestamp"])
        ts[3], ts[7] = ts[7], ts[3]  # swap two timestamps
        df["timestamp"] = ts
        valid, errors = _validate(df)
        assert valid is False, "Unordered timestamps must be rejected"
        assert errors


# ── Price corruption ──────────────────────────────────────────────────────────


class TestPriceCorruption:
    def test_zero_close_rejected(self) -> None:
        df = _clean().copy()
        df.loc[10, "close"] = 0.0
        df.loc[10, "low"] = 0.0
        valid, errors = _validate(df)
        assert valid is False, "Zero price must be rejected"

    def test_negative_close_rejected(self) -> None:
        df = _clean().copy()
        df.loc[10, "close"] = -100.0
        valid, errors = _validate(df)
        assert valid is False, "Negative price must be rejected"

    def test_high_below_low_rejected(self) -> None:
        df = _clean().copy()
        # Invert high and low
        df.loc[5, "high"] = df.loc[5, "low"] - 1.0
        valid, errors = _validate(df)
        assert valid is False, "high < low must be rejected"
        assert errors

    def test_open_above_high_rejected(self) -> None:
        df = _clean().copy()
        df.loc[5, "open"] = df.loc[5, "high"] * 1.01  # open > high
        valid, errors = _validate(df)
        assert valid is False, "open > high must be rejected"
        assert errors

    def test_open_below_low_rejected(self) -> None:
        df = _clean().copy()
        df.loc[5, "open"] = df.loc[5, "low"] * 0.99  # open < low
        valid, errors = _validate(df)
        assert valid is False, "open < low must be rejected"
        assert errors

    def test_negative_volume_rejected(self) -> None:
        df = _clean().copy()
        df.loc[3, "volume"] = -1.0
        valid, errors = _validate(df)
        assert valid is False, "Negative volume must be rejected"
        assert errors


# ── Metadata corruption ───────────────────────────────────────────────────────


class TestMetadataCorruption:
    def test_symbol_mismatch_rejected(self) -> None:
        df = _clean().copy()
        df["symbol"] = "ETH/USDT"  # data says ETH but validator called with BTC
        valid, errors = _validate(df)
        assert valid is False, "Symbol mismatch must be rejected"
        assert errors

    def test_timeframe_mismatch_rejected(self) -> None:
        df = _clean().copy()
        df["timeframe"] = "1h"  # data says 1h but validator called with 1d
        valid, errors = _validate(df)
        assert valid is False, "Timeframe mismatch must be rejected"
        assert errors


# ── Manifest rejects corrupt data ─────────────────────────────────────────────


class TestManifestTimestampRejection:
    def test_manifest_rejects_naive_timestamp_parquet(self, tmp_path: Path) -> None:
        df = _clean().copy()
        df["timestamp"] = pd.date_range("2024-01-01", periods=_N, freq="1D")  # naive
        p = tmp_path / "bad.parquet"
        df.to_parquet(p, index=False)
        with pytest.raises(ValueError, match="UTC"):
            generate_manifest(p, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)

    def test_manifest_rejects_empty_parquet(self, tmp_path: Path) -> None:
        empty = _clean().iloc[0:0]
        p = tmp_path / "empty.parquet"
        empty.to_parquet(p, index=False)
        with pytest.raises(ValueError):
            generate_manifest(p, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)

    def test_manifest_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            generate_manifest(tmp_path / "ghost.parquet", _SYMBOL, _TIMEFRAME)
