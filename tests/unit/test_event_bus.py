"""Tests for the synchronous EventBus — dependency injection, exception isolation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    DataDownloadedEvent,
    EventCategory,
    EventName,
    SystemEvent,
)


def _make_system_event() -> SystemEvent:
    return SystemEvent(component="test", event_name=EventName.SYSTEM_STARTUP, description="")


def _make_data_event() -> DataDownloadedEvent:
    return DataDownloadedEvent(
        component="aqcs.data.ohlcv",
        symbol="BTC/USDT",
        timeframe="1d",
        exchange="binance",
        candles_fetched=100,
        output_path="data/raw/BTC_USDT_1d.parquet",
    )


class TestEventBusSubscribeAndPublish:
    def test_handler_receives_event(self) -> None:
        bus = EventBus()
        received: list[SystemEvent] = []
        bus.subscribe(received.append)
        bus.publish(_make_system_event())
        assert len(received) == 1

    def test_category_handler_receives_matching_event(self) -> None:
        bus = EventBus()
        received: list = []
        bus.subscribe(received.append, EventCategory.DATA)
        bus.publish(_make_data_event())
        assert len(received) == 1

    def test_category_handler_does_not_receive_other_category(self) -> None:
        bus = EventBus()
        received: list = []
        bus.subscribe(received.append, EventCategory.DATA)
        bus.publish(_make_system_event())
        assert len(received) == 0

    def test_global_handler_receives_all_categories(self) -> None:
        bus = EventBus()
        received: list = []
        bus.subscribe(received.append)
        bus.publish(_make_system_event())
        bus.publish(_make_data_event())
        assert len(received) == 2

    def test_multiple_handlers_all_called(self) -> None:
        bus = EventBus()
        h1 = MagicMock()
        h2 = MagicMock()
        bus.subscribe(h1)
        bus.subscribe(h2)
        ev = _make_system_event()
        bus.publish(ev)
        h1.assert_called_once_with(ev)
        h2.assert_called_once_with(ev)

    def test_no_global_singleton(self) -> None:
        bus1 = EventBus()
        bus2 = EventBus()
        received1: list = []
        received2: list = []
        bus1.subscribe(received1.append)
        bus2.subscribe(received2.append)
        bus1.publish(_make_system_event())
        assert len(received1) == 1
        assert len(received2) == 0


class TestExceptionIsolation:
    def test_failing_handler_does_not_crash_publish(self) -> None:
        bus = EventBus()

        def bad_handler(_: SystemEvent) -> None:
            raise RuntimeError("handler failure")

        bus.subscribe(bad_handler)
        bus.publish(_make_system_event())  # must not raise

    def test_failing_handler_does_not_prevent_other_handlers(self) -> None:
        bus = EventBus()
        received: list = []

        def bad_handler(_: SystemEvent) -> None:
            raise ValueError("broken")

        bus.subscribe(bad_handler)
        bus.subscribe(received.append)
        bus.publish(_make_system_event())
        assert len(received) == 1

    def test_multiple_failing_handlers_all_others_still_run(self) -> None:
        bus = EventBus()
        received: list = []

        def bad1(_: SystemEvent) -> None:
            raise RuntimeError("bad1")

        def bad2(_: SystemEvent) -> None:
            raise ValueError("bad2")

        bus.subscribe(bad1)
        bus.subscribe(received.append)
        bus.subscribe(bad2)
        bus.subscribe(received.append)
        bus.publish(_make_system_event())
        assert len(received) == 2


class TestHandlerCount:
    def test_no_handlers_initially(self) -> None:
        bus = EventBus()
        assert bus.handler_count() == 0

    def test_global_handler_counted(self) -> None:
        bus = EventBus()
        bus.subscribe(lambda _: None)
        assert bus.handler_count() == 1

    def test_category_handler_counted_by_category(self) -> None:
        bus = EventBus()
        bus.subscribe(lambda _: None, EventCategory.DATA)
        assert bus.handler_count(EventCategory.DATA) == 1
        assert bus.handler_count(EventCategory.SYSTEM) == 0
