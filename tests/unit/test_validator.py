"""Tests for the OHLCV data validation layer."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

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
    """Synthetic valid daily OHLCV frame with UTC timestamps."""
    dates = pd.date_range(start=start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [100.0 + i for i in range(n)],
            "high": [110.0 + i for i in range(n)],
            "low": [90.0 + i for i in range(n)],
            "close": [105.0 + i for i in range(n)],
            "volume": [1000.0 + i for i in range(n)],
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "exchange": "binance",
        }
    )


# ── ValidationResult metadata ─────────────────────────────────────────────────


class TestValidationResultMetadata:
    def test_valid_result_has_metadata(self) -> None:
        df = _make_df(5)
        r = validate_ohlcv(df, "BTC/USDT", "1d")
        assert r.is_valid
        assert r.row_count == 5
        assert r.symbol == "BTC/USDT"
        assert r.timeframe == "1d"
        assert r.exchange == "binance"
        assert r.start_timestamp is not None
        assert r.end_timestamp is not None
        assert r.start_timestamp <= r.end_timestamp

    def test_result_timestamps_are_utc(self) -> None:
        df = _make_df(3)
        r = validate_ohlcv(df, "BTC/USDT", "1d")
        assert r.start_timestamp is not None
        assert r.start_timestamp.tzinfo == UTC

    def test_empty_dataset_result_has_zero_row_count(self) -> None:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        r = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not r.is_valid
        assert r.row_count == 0
        assert r.start_timestamp is None
        assert r.end_timestamp is None

    def test_schema_failure_result_has_row_count(self) -> None:
        df = _make_df(3).drop(columns=["close"])
        r = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not r.is_valid
        assert r.row_count == 3

    def test_result_is_immutable(self) -> None:
        r = ValidationResult(is_valid=True)
        with pytest.raises(FrozenInstanceError):
            r.is_valid = False  # type: ignore[misc]

    def test_has_warnings_property(self) -> None:
        r = ValidationResult(is_valid=True, warnings=["gap detected"])
        assert r.has_warnings

    def test_no_warnings_property(self) -> None:
        r = ValidationResult(is_valid=True)
        assert not r.has_warnings


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


# ── Empty dataset ─────────────────────────────────────────────────────────────


class TestEmptyDataset:
    def test_empty_dataframe_is_invalid(self) -> None:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("empty" in e.lower() for e in result.errors)

    def test_empty_dataframe_emits_event(self) -> None:
        bus = EventBus()
        events: list = []
        bus.subscribe(events.append, EventCategory.VALIDATION)
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert len(events) == 1
        assert isinstance(events[0], DataValidationFailedEvent)

    def test_empty_dataframe_returns_early(self) -> None:
        df = pd.DataFrame(columns=REQUIRED_COLUMNS)
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert len(result.errors) == 1  # only the empty error, not cascading failures


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
        assert any(isinstance(e, DataSchemaMismatchEvent) for e in events)

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


# ── UTC timestamp enforcement ─────────────────────────────────────────────────


class TestUTCTimestampEnforcement:
    def test_naive_timestamps_rejected(self) -> None:
        df = _make_df()
        df["timestamp"] = pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        )  # naive — no tz
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("naive" in e.lower() or "timezone" in e.lower() for e in result.errors)

    def test_utc_timestamps_accepted(self) -> None:
        df = _make_df()
        assert df["timestamp"].dt.tz is not None
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid

    def test_non_utc_aware_timestamps_rejected(self) -> None:
        """America/New_York is UTC-aware but not UTC — must be rejected."""
        from zoneinfo import ZoneInfo

        dates = pd.date_range("2024-01-01", periods=5, freq="1D", tz=ZoneInfo("America/New_York"))
        df = _make_df()
        df["timestamp"] = dates
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("UTC" in e for e in result.errors)

    def test_europe_london_winter_rejected(self) -> None:
        """Europe/London has offset +0 in winter but is NOT UTC — reject by name."""
        from zoneinfo import ZoneInfo

        dates = pd.date_range("2024-01-01", periods=5, freq="1D", tz=ZoneInfo("Europe/London"))
        df = _make_df()
        df["timestamp"] = dates
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("UTC" in e for e in result.errors)

    def test_explicit_utc_datetime_accepted(self) -> None:
        df = _make_df()
        utc_dates = [
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 3, tzinfo=UTC),
            datetime(2024, 1, 4, tzinfo=UTC),
            datetime(2024, 1, 5, tzinfo=UTC),
        ]
        df["timestamp"] = pd.DatetimeIndex(utc_dates)
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid


# ── Duplicate timestamps ──────────────────────────────────────────────────────


class TestDuplicateTimestamps:
    def test_duplicate_is_invalid(self) -> None:
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


# ── Strictly increasing timestamps ────────────────────────────────────────────


class TestMonotonicTimestamps:
    def test_sorted_timestamps_pass(self) -> None:
        df = _make_df()
        assert df["timestamp"].is_monotonic_increasing
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid

    def test_unsorted_timestamps_fail(self) -> None:
        df = _make_df()
        # Swap rows 1 and 3 to create non-monotonic order
        df.loc[1, "timestamp"], df.loc[3, "timestamp"] = (
            df.loc[3, "timestamp"],
            df.loc[1, "timestamp"],
        )
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("monotonic" in e.lower() or "increasing" in e.lower() for e in result.errors)

    def test_unsorted_distinct_from_duplicate_error(self) -> None:
        """Out-of-order timestamps without duplicates should only raise monotonic error."""
        df = _make_df()
        df.loc[1, "timestamp"], df.loc[3, "timestamp"] = (
            df.loc[3, "timestamp"],
            df.loc[1, "timestamp"],
        )
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert not any("duplicate" in e for e in result.errors)
        assert any("monotonic" in e.lower() or "increasing" in e.lower() for e in result.errors)

    def test_duplicate_timestamps_also_trigger_duplicate_error(self) -> None:
        """Duplicate timestamps trigger the duplicate check, not just monotonic."""
        df = _make_df()
        df.loc[3, "timestamp"] = df.loc[0, "timestamp"]  # duplicate
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("duplicate" in e for e in result.errors)


# ── OHLCV consistency ─────────────────────────────────────────────────────────


class TestOHLCVConsistency:
    def test_high_lt_low_is_invalid(self) -> None:
        df = _make_df()
        df.loc[1, "high"] = df.loc[1, "low"] - 1.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("high < low" in e for e in result.errors)

    def test_open_above_high_is_invalid(self) -> None:
        df = _make_df()
        df.loc[2, "open"] = df.loc[2, "high"] + 5.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("open" in e for e in result.errors)

    def test_open_below_low_is_invalid(self) -> None:
        df = _make_df()
        df.loc[2, "open"] = df.loc[2, "low"] - 5.0
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("open" in e for e in result.errors)

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


# ── Metadata column validation ────────────────────────────────────────────────


class TestMetadataValidation:
    def test_empty_symbol_column_is_invalid(self) -> None:
        df = _make_df()
        df.loc[1, "symbol"] = ""
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("symbol" in e for e in result.errors)

    def test_mismatched_symbol_is_invalid(self) -> None:
        df = _make_df()
        df["symbol"] = "ETH/USDT"  # doesn't match argument
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("symbol" in e for e in result.errors)

    def test_empty_timeframe_column_is_invalid(self) -> None:
        df = _make_df()
        df.loc[0, "timeframe"] = ""
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("timeframe" in e for e in result.errors)

    def test_mismatched_timeframe_is_invalid(self) -> None:
        df = _make_df()
        df["timeframe"] = "4h"  # doesn't match argument "1d"
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("timeframe" in e for e in result.errors)

    def test_empty_exchange_column_is_invalid(self) -> None:
        df = _make_df()
        df.loc[2, "exchange"] = ""
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert not result.is_valid
        assert any("exchange" in e for e in result.errors)

    def test_valid_metadata_passes(self) -> None:
        df = _make_df()
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid


# ── Gap detection ─────────────────────────────────────────────────────────────


class TestGapDetection:
    def _make_gapped_df(self) -> pd.DataFrame:
        dates = [
            pd.Timestamp("2024-01-01", tz="UTC"),
            pd.Timestamp("2024-01-02", tz="UTC"),
            pd.Timestamp("2024-01-04", tz="UTC"),  # 2024-01-03 missing
            pd.Timestamp("2024-01-05", tz="UTC"),
        ]
        return pd.DataFrame(
            {
                "timestamp": dates,
                "open": [100.0, 101.0, 103.0, 104.0],
                "high": [110.0, 111.0, 113.0, 114.0],
                "low": [90.0, 91.0, 93.0, 94.0],
                "close": [105.0, 106.0, 108.0, 109.0],
                "volume": [1000.0, 1001.0, 1003.0, 1004.0],
                "symbol": "BTC/USDT",
                "timeframe": "1d",
                "exchange": "binance",
            }
        )

    def test_gap_produces_warning_not_error(self) -> None:
        df = self._make_gapped_df()
        result = validate_ohlcv(df, "BTC/USDT", "1d")
        assert result.is_valid
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
        df["timeframe"] = "3d"
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
        df.loc[0, "high"] = df.loc[0, "low"] - 1.0
        df.loc[1, "volume"] = -5.0
        validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)
        assert len(events) >= 2

    def test_no_events_for_valid_data(self) -> None:
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
