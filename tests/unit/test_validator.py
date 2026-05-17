"""Tests for the OHLCV data validation layer."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from aqcs.data.validator import (
    REQUIRED_COLUMNS,
    ValidationResult,
    validate_ohlcv,
)
from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    DataGapDetectedEvent,
    DataSchemaMismatchEvent,
    DataValidationFailedEvent,
    EventCategory,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_df(n: int = 5, *, start: str = "2024-01-01", freq: str = "1D") -> pd.DataFrame:
    """Synthetic valid daily OHLCV frame."""
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "timestamp": dates,
        "open":      [100.0 + i for i in range(n)],
        "high":      [110.0 + i for i in range(n)],
        "low":       [90.0 + i for i in range(n)],
        "close":     [105.0 + i for i in range(n)],
        "volume":    [1000.0 + i for i in range(n)],
        "symbol":    "BTC/USDT",
        "timeframe": "1d",
        "exchange":  "binance",
    })


# ── ValidationResult ──────────────────────────────────────────────────────────

class TestValidationResult:
    def test_valid_result(self) -> None:
        r = ValidationResult(is_valid=True, errors=[], warnings=[])
        assert r.is_valid
        assert not r.has_warnings

    def test_invalid_result(self) -> None:
        r = ValidationResult(is_valid=False, errors=["bad thing"], warnings=[])
        assert not r.is_valid

    def test_has_warnings(self) -> None:
        r = ValidationResult(is_valid=True, errors=[], warnings=["gap detected"])
        assert r.has_warnings


# ── Happy path ────────────────────────────────────────────────────────────────

class TestValidOHLCV:
    def test_valid_frame_passes(self) -> None:
        df = _make_df()
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid
        assert result.errors == []

    def test_single_row_passes(self) -> None:
        df = _make_df(1)
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid

    def test_no_bus_does_not_raise(self) -> None:
        df = _make_df()
        result = validate_ohlcv(df, "BTC/USDT", "1d", bus=None)
        assert result.is_valid


# ── Schema check ──────────────────────────────────────────────────────────────

class TestSchemaValidation:
    def test_missing_column_is_invalid(self) -> None:
        df = _make_df().drop(columns=["volume"])
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("volume" in e for e in result.errors)

    def test_missing_column_emits_schema_mismatch_event(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = _make_df().drop(columns=["close"])
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert len(events) == 1
        assert isinstance(events[0], DataSchemaMismatchEvent)

    def test_multiple_missing_columns_reported(self) -> None:
        df = _make_df().drop(columns=["volume", "exchange"])
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("volume" in e for e in result.errors)

    def test_all_required_columns_accepted(self) -> None:
        df = _make_df()[REQUIRED_COLUMNS]
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid


# ── Null checks ───────────────────────────────────────────────────────────────

class TestNullValidation:
    def test_null_close_is_invalid(self) -> None:
        df = _make_df()
        df.loc[2, "close"] = None  # type: ignore[call-overload]
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("close" in e for e in result.errors)

    def test_null_volume_is_invalid(self) -> None:
        df = _make_df()
        df.loc[0, "volume"] = None  # type: ignore[call-overload]
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid

    def test_null_emits_validation_failed_event(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = _make_df()
        df.loc[1, "open"] = None  # type: ignore[call-overload]
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert any(isinstance(e, DataValidationFailedEvent) for e in events)


# ── UTC timestamp checks ──────────────────────────────────────────────────────

class TestTimestampValidation:
    def test_naive_timestamps_are_invalid(self) -> None:
        df = _make_df()
        df["timestamp"] = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03",
                                           "2024-01-04", "2024-01-05"])  # naive
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("UTC" in e or "naive" in e for e in result.errors)

    def test_utc_timestamps_pass(self) -> None:
        df = _make_df()
        assert df["timestamp"].dt.tz is not None
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid


# ── Duplicate timestamps ──────────────────────────────────────────────────────

class TestDuplicateTimestamps:
    def test_duplicate_timestamp_is_invalid(self) -> None:
        df = _make_df()
        df.loc[3, "timestamp"] = df.loc[0, "timestamp"]
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("duplicate" in e for e in result.errors)

    def test_no_duplicates_passes(self) -> None:
        df = _make_df()
        assert df["timestamp"].duplicated().sum() == 0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid


# ── OHLCV consistency ─────────────────────────────────────────────────────────

class TestOHLCVConsistency:
    def test_high_lt_low_is_invalid(self) -> None:
        df = _make_df()
        df.loc[1, "high"] = df.loc[1, "low"] - 1.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("high < low" in e for e in result.errors)

    def test_close_above_high_is_invalid(self) -> None:
        df = _make_df()
        df.loc[2, "close"] = df.loc[2, "high"] + 10.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("close" in e for e in result.errors)

    def test_close_below_low_is_invalid(self) -> None:
        df = _make_df()
        df.loc[2, "close"] = df.loc[2, "low"] - 10.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid

    def test_non_positive_price_is_invalid(self) -> None:
        df = _make_df()
        df.loc[0, "open"] = 0.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("non-positive" in e for e in result.errors)

    def test_negative_price_is_invalid(self) -> None:
        df = _make_df()
        df.loc[0, "close"] = -5.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid

    def test_negative_volume_is_invalid(self) -> None:
        df = _make_df()
        df.loc[1, "volume"] = -1.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("volume" in e for e in result.errors)

    def test_zero_volume_is_valid(self) -> None:
        df = _make_df()
        df.loc[1, "volume"] = 0.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid

    def test_consistency_emits_validation_failed_event(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = _make_df()
        df.loc[0, "high"] = df.loc[0, "low"] - 1.0
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert any(isinstance(e, DataValidationFailedEvent) for e in events)


# ── Gap detection ─────────────────────────────────────────────────────────────

class TestGapDetection:
    def _make_gapped_df(self) -> pd.DataFrame:
        """Daily frame with 2024-01-03 missing."""
        dates = [
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-01-02", tz="UTC"),
            # gap: 2024-01-03 missing
            pd.Timestamp("2024-01-04", tz="UTC"),
            pd.Timestamp("2024-01-05", tz="UTC"),
        ]
        return pd.DataFrame({
            "timestamp": dates,
            "open":  [100.0, 101.0, 103.0, 104.0],
            "high":  [110.0, 111.0, 113.0, 114.0],
            "low":   [90.0,  91.0,  93.0,  94.0],
            "close": [105.0, 106.0, 108.0, 109.0],
            "volume":[1000.0,1001.0,1003.0,1004.0],
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "exchange": "binance",
        })

    def test_gap_produces_warning(self) -> None:
        df = self._make_gapped_df()
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid  # gap is advisory, not blocking
        assert result.has_warnings
        assert any("missing bar" in w for w in result.warnings)

    def test_gap_emits_gap_event(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = self._make_gapped_df()
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        gap_events = [e for e in events if isinstance(e, DataGapDetectedEvent)]
        assert len(gap_events) == 1
        assert gap_events[0].missing_bars == 1
        assert "2024-01-03" in gap_events[0].gap_start

    def test_contiguous_data_has_no_gap_warning(self) -> None:
        df = _make_df(10)
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid
        assert not result.has_warnings

    def test_unknown_timeframe_skips_gap_check(self) -> None:
        df = _make_df(3)
        df["timeframe"] = "3d"  # not in _TIMEFRAME_TO_FREQ
        result = validate_ohlcv(df, "BTC/USDT", "3d")
        assert result.is_valid
        assert not result.has_warnings


# ── Event bus integration ─────────────────────────────────────────────────────

class TestEventBusIntegration:
    def test_multiple_errors_emit_multiple_events(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = _make_df()
        df.loc[0, "high"] = df.loc[0, "low"] - 1.0  # high < low
        df.loc[1, "volume"] = -5.0                    # negative volume
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert len(events) >= 2

    def test_no_events_emitted_for_valid_data(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append)
        df = _make_df()
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert events == []

    def test_component_field_in_event(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = _make_df().drop(columns=["close"])
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus, component="aqcs.test.component")
        assert events[0].component == "aqcs.test.component"
