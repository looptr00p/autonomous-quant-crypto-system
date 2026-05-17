"""Tests for the AQCS event schema."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest

from aqcs.utils.events import (
    ConfigLoadedEvent,
    DataDownloadedEvent,
    DataGapDetectedEvent,
    DataSchemaMismatchEvent,
    DataValidationFailedEvent,
    EventCategory,
    EventName,
    EventSeverity,
    ExperimentCompletedEvent,
    ExperimentFailedEvent,
    ExperimentStartedEvent,
    OversightReviewEvent,
    PhaseConstraintBlockedEvent,
    RiskCheckEvent,
    SignalDirection,
    SignalGeneratedEvent,
    SystemEvent,
    _VALID_CATEGORY_FOR_NAME,
)


class TestBaseEventContract:
    def test_auto_generated_id_is_uuid(self) -> None:
        ev = SystemEvent(component="aqcs.test", event_name=EventName.SYSTEM_STARTUP)
        assert isinstance(ev.event_id, UUID)

    def test_timestamp_is_utc_by_default(self) -> None:
        ev = SystemEvent(component="aqcs.test", event_name=EventName.SYSTEM_STARTUP)
        assert ev.timestamp_utc.tzinfo == timezone.utc
        assert ev.timestamp_utc.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_schema_version_default(self) -> None:
        ev = SystemEvent(component="aqcs.test", event_name=EventName.SYSTEM_STARTUP)
        assert ev.event_version == "1.0"

    def test_event_is_immutable(self) -> None:
        ev = SystemEvent(component="aqcs.test", event_name=EventName.SYSTEM_STARTUP)
        with pytest.raises(Exception):
            ev.component = "mutated"  # type: ignore[misc]

    def test_each_event_has_unique_id(self) -> None:
        e1 = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        e2 = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        assert e1.event_id != e2.event_id

    def test_correlation_id_optional_defaults_none(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        assert ev.correlation_id is None

    def test_run_id_optional_defaults_none(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        assert ev.run_id is None

    def test_default_severity_is_info(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        assert ev.severity == EventSeverity.INFO

    def test_correlation_id_propagated(self) -> None:
        cid = uuid4()
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, correlation_id=cid)
        assert ev.correlation_id == cid


class TestUTCEnforcement:
    def test_rejects_naive_datetime(self) -> None:
        naive = datetime(2024, 1, 1, 12, 0, 0)  # no tzinfo
        with pytest.raises(Exception, match="UTC-aware"):
            SystemEvent(
                component="s",
                event_name=EventName.SYSTEM_STARTUP,
                timestamp_utc=naive,
            )

    def test_rejects_non_utc_timezone(self) -> None:
        est = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
        with pytest.raises(Exception, match="UTC"):
            SystemEvent(
                component="s",
                event_name=EventName.SYSTEM_STARTUP,
                timestamp_utc=est,
            )

    def test_accepts_explicit_utc(self) -> None:
        utc_dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        ev = SystemEvent(
            component="s",
            event_name=EventName.SYSTEM_STARTUP,
            timestamp_utc=utc_dt,
        )
        assert ev.timestamp_utc == utc_dt

    def test_default_factory_produces_utc(self) -> None:
        ev = DataDownloadedEvent(
            component="aqcs.data.ohlcv",
            symbol="BTC/USDT",
            timeframe="1d",
            exchange="binance",
            candles_fetched=10,
            output_path="data/raw/x.parquet",
        )
        assert ev.timestamp_utc.tzinfo == timezone.utc


class TestCategoryNameConsistency:
    def test_valid_combination_passes(self) -> None:
        ev = DataDownloadedEvent(
            component="aqcs.data.ohlcv",
            symbol="BTC/USDT",
            timeframe="1d",
            exchange="binance",
            candles_fetched=100,
            output_path="data/raw/BTC_USDT_1d.parquet",
        )
        assert ev.event_category == EventCategory.DATA
        assert ev.event_name == EventName.DATA_DOWNLOADED

    def test_mismatched_combination_rejected(self) -> None:
        with pytest.raises(Exception, match="requires event_category"):
            DataDownloadedEvent(
                component="aqcs.data.ohlcv",
                symbol="BTC/USDT",
                timeframe="1d",
                exchange="binance",
                candles_fetched=100,
                output_path="x.parquet",
                event_category=EventCategory.RISK,  # wrong
            )

    def test_all_named_events_have_consistent_mapping(self) -> None:
        for name, category in _VALID_CATEGORY_FOR_NAME.items():
            assert isinstance(name, EventName)
            assert isinstance(category, EventCategory)

    def test_every_event_name_has_a_mapping(self) -> None:
        for name in EventName:
            assert name in _VALID_CATEGORY_FOR_NAME, (
                f"EventName.{name.name} has no entry in _VALID_CATEGORY_FOR_NAME"
            )


class TestNewEventClasses:
    def test_experiment_failed_event(self) -> None:
        ev = ExperimentFailedEvent(
            component="aqcs.backtesting",
            experiment_name="btc_momentum_v1",
            reason="Data gap in input: 2024-01-15",
            duration_seconds=3.2,
        )
        assert ev.event_category == EventCategory.EXPERIMENT
        assert ev.event_name == EventName.EXPERIMENT_FAILED
        assert ev.severity == EventSeverity.ERROR

    def test_data_schema_mismatch_event(self) -> None:
        ev = DataSchemaMismatchEvent(
            component="aqcs.monitoring",
            symbol="ETH/USDT",
            timeframe="1d",
            expected_columns=["timestamp", "open", "high", "low", "close", "volume"],
            actual_columns=["timestamp", "open", "close"],
        )
        assert ev.event_category == EventCategory.VALIDATION
        assert ev.event_name == EventName.DATA_SCHEMA_MISMATCH
        assert ev.severity == EventSeverity.ERROR

    def test_data_gap_detected_event(self) -> None:
        ev = DataGapDetectedEvent(
            component="aqcs.monitoring",
            symbol="BTC/USDT",
            timeframe="1d",
            gap_start="2024-01-15",
            gap_end="2024-01-17",
            missing_bars=2,
        )
        assert ev.event_category == EventCategory.VALIDATION
        assert ev.event_name == EventName.DATA_GAP_DETECTED
        assert ev.severity == EventSeverity.WARNING
        assert ev.missing_bars == 2


class TestSignalDirection:
    def test_valid_directions_are_enums(self) -> None:
        assert SignalDirection.LONG == "long"
        assert SignalDirection.SHORT == "short"
        assert SignalDirection.NEUTRAL == "neutral"

    def test_signal_event_accepts_enum(self) -> None:
        ev = SignalGeneratedEvent(
            component="aqcs.signals.momentum",
            symbol="BTC/USDT",
            timeframe="1d",
            direction=SignalDirection.LONG,
            strength=0.72,
        )
        assert ev.direction == SignalDirection.LONG
        assert isinstance(ev.direction, SignalDirection)

    def test_signal_event_rejects_free_string(self) -> None:
        with pytest.raises(Exception):
            SignalGeneratedEvent(
                component="aqcs.signals",
                symbol="BTC/USDT",
                timeframe="1d",
                direction="up",  # type: ignore[arg-type]
                strength=0.5,
            )


class TestPayloadAndMetadata:
    def test_payload_defaults_empty(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        assert ev.payload == {}

    def test_metadata_defaults_empty(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP)
        assert ev.metadata == {}

    def test_typed_fields_on_subclass(self) -> None:
        ev = DataDownloadedEvent(
            component="aqcs.data.ohlcv",
            symbol="SOL/USDT",
            timeframe="4h",
            exchange="binance",
            candles_fetched=500,
            output_path="data/raw/SOL_USDT_4h.parquet",
        )
        assert ev.symbol == "SOL/USDT"
        assert ev.candles_fetched == 500


class TestExperimentEvents:
    def test_started_completed_same_category(self) -> None:
        started = ExperimentStartedEvent(
            component="aqcs.backtesting",
            experiment_name="btc_momentum_v1",
            experiment_type="signal_research",
            git_commit="abc1234",
            dataset_fingerprint="deadbeef",
            dataset_paths=["data/raw/BTC_USDT_1d.parquet"],
        )
        completed = ExperimentCompletedEvent(
            component="aqcs.backtesting",
            experiment_name="btc_momentum_v1",
            duration_seconds=42.3,
            output_path="experiments/btc_momentum_v1/",
            metrics={"sharpe": 1.4, "max_drawdown": -0.12},
        )
        assert started.event_category == EventCategory.EXPERIMENT
        assert completed.event_category == EventCategory.EXPERIMENT
        assert completed.metrics["sharpe"] == 1.4
