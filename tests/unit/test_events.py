"""Tests for the event schema."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.utils.events import DataEvent, EventCategory, EventSeverity, OversightEvent, SystemEvent


class TestBaseEvent:
    def test_data_event_defaults(self) -> None:
        ev = DataEvent(
            source="test",
            message="fetched candles",
            symbol="BTC/USDT",
            timeframe="1d",
            candles_fetched=100,
        )
        assert ev.category == EventCategory.DATA
        assert ev.severity == EventSeverity.INFO
        assert isinstance(ev.timestamp, datetime)
        assert ev.timestamp.tzinfo == timezone.utc

    def test_event_is_immutable(self) -> None:
        ev = SystemEvent(source="test", message="startup")
        with pytest.raises(Exception):
            ev.message = "mutated"  # type: ignore[misc]

    def test_oversight_event_has_component(self) -> None:
        ev = OversightEvent(
            source="data_pipeline",
            message="OHLCV download complete",
            quant_component="ohlcv_downloader",
        )
        assert ev.quant_component == "ohlcv_downloader"
        assert ev.category == EventCategory.OVERSIGHT


class TestEventIds:
    def test_each_event_gets_unique_id(self) -> None:
        e1 = SystemEvent(source="s", message="m")
        e2 = SystemEvent(source="s", message="m")
        assert e1.event_id != e2.event_id
