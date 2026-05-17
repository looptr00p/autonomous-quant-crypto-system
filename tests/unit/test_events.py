"""Tests for the AQCS event schema."""

from __future__ import annotations

from datetime import timezone
from uuid import UUID, uuid4

import pytest

from aqcs.utils.events import (
    ConfigLoadedEvent,
    DataDownloadedEvent,
    DataValidationFailedEvent,
    EventCategory,
    EventName,
    EventSeverity,
    ExperimentCompletedEvent,
    ExperimentStartedEvent,
    OversightReviewEvent,
    PhaseConstraintBlockedEvent,
    RiskCheckEvent,
    SignalDirection,
    SignalGeneratedEvent,
    SystemEvent,
)


class TestBaseEventContract:
    def test_auto_generated_id_is_uuid(self) -> None:
        ev = SystemEvent(
            component="aqcs.test",
            event_name=EventName.SYSTEM_STARTUP,
            description="up",
        )
        assert isinstance(ev.event_id, UUID)

    def test_timestamp_is_utc(self) -> None:
        ev = SystemEvent(
            component="aqcs.test",
            event_name=EventName.SYSTEM_STARTUP,
            description="up",
        )
        assert ev.timestamp_utc.tzinfo == timezone.utc

    def test_schema_version_default(self) -> None:
        ev = SystemEvent(
            component="aqcs.test",
            event_name=EventName.SYSTEM_STARTUP,
            description="up",
        )
        assert ev.event_version == "1.0"

    def test_event_is_immutable(self) -> None:
        ev = SystemEvent(
            component="aqcs.test",
            event_name=EventName.SYSTEM_STARTUP,
            description="up",
        )
        with pytest.raises(Exception):
            ev.component = "mutated"  # type: ignore[misc]

    def test_each_event_has_unique_id(self) -> None:
        e1 = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        e2 = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        assert e1.event_id != e2.event_id

    def test_correlation_id_optional(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        assert ev.correlation_id is None

    def test_correlation_id_set(self) -> None:
        cid = uuid4()
        ev = SystemEvent(
            component="s",
            event_name=EventName.SYSTEM_STARTUP,
            description="",
            correlation_id=cid,
        )
        assert ev.correlation_id == cid

    def test_run_id_optional(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        assert ev.run_id is None

    def test_default_severity_is_info(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        assert ev.severity == EventSeverity.INFO


class TestEventCategoryAndName:
    def test_data_downloaded_category(self) -> None:
        ev = DataDownloadedEvent(
            component="aqcs.data.ohlcv",
            symbol="BTC/USDT",
            timeframe="1d",
            exchange="binance",
            candles_fetched=365,
            output_path="data/raw/BTC_USDT_1d.parquet",
        )
        assert ev.event_category == EventCategory.DATA
        assert ev.event_name == EventName.DATA_DOWNLOADED

    def test_validation_failed_category(self) -> None:
        ev = DataValidationFailedEvent(
            component="aqcs.monitoring",
            symbol="ETH/USDT",
            timeframe="1d",
            reason="gap detected: 3 missing bars",
        )
        assert ev.event_category == EventCategory.VALIDATION
        assert ev.event_name == EventName.DATA_VALIDATION_FAILED

    def test_phase_constraint_category(self) -> None:
        ev = PhaseConstraintBlockedEvent(
            component="aqcs.utils.phase_guard",
            feature="machine_learning",
            current_phase=1,
        )
        assert ev.event_category == EventCategory.PHASE_GUARD
        assert ev.severity == EventSeverity.WARNING

    def test_oversight_category(self) -> None:
        ev = OversightReviewEvent(
            component="aqcs.llm_oversight.observer",
            observed_event_id=uuid4(),
            summary="Data download completed normally.",
        )
        assert ev.event_category == EventCategory.OVERSIGHT
        assert ev.event_name == EventName.OVERSIGHT_REVIEW_GENERATED


class TestSignalDirection:
    def test_valid_directions(self) -> None:
        assert SignalDirection.LONG == "long"
        assert SignalDirection.SHORT == "short"
        assert SignalDirection.NEUTRAL == "neutral"

    def test_signal_event_requires_direction_enum(self) -> None:
        ev = SignalGeneratedEvent(
            component="aqcs.signals.momentum",
            symbol="BTC/USDT",
            timeframe="1d",
            direction=SignalDirection.LONG,
            strength=0.72,
        )
        assert ev.direction == SignalDirection.LONG
        assert isinstance(ev.direction, SignalDirection)

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(Exception):
            SignalGeneratedEvent(
                component="aqcs.signals",
                symbol="BTC/USDT",
                timeframe="1d",
                direction="up",  # type: ignore[arg-type]
                strength=0.5,
            )


class TestPayloadAndMetadata:
    def test_payload_defaults_to_empty_dict(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        assert ev.payload == {}

    def test_metadata_defaults_to_empty_dict(self) -> None:
        ev = SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description="")
        assert ev.metadata == {}

    def test_arbitrary_payload_accepted(self) -> None:
        ev = ConfigLoadedEvent(
            component="aqcs.utils.config",
            env="development",
            config_files=["configs/base.yaml"],
            payload={"extra_key": "extra_value"},
        )
        assert ev.payload["extra_key"] == "extra_value"

    def test_typed_fields_preferred_over_payload(self) -> None:
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
    def test_started_and_completed_share_name(self) -> None:
        started = ExperimentStartedEvent(
            component="aqcs.backtesting",
            experiment_name="btc_momentum_v1",
            git_commit="abc1234",
            symbols=["BTC/USDT"],
            timeframe="1d",
            start_date="2023-01-01",
            end_date="2023-12-31",
        )
        completed = ExperimentCompletedEvent(
            component="aqcs.backtesting",
            experiment_name="btc_momentum_v1",
            duration_seconds=42.3,
            output_path="experiments/btc_momentum_v1/",
            metrics={"sharpe": 1.4, "max_drawdown": -0.12},
            run_id=started.run_id,
        )
        assert started.event_category == EventCategory.EXPERIMENT
        assert completed.event_category == EventCategory.EXPERIMENT
        assert completed.metrics["sharpe"] == 1.4
