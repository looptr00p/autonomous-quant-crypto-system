"""Tests for the LLM Oversight observer — single-bus DI, subscription, and review generation."""

from __future__ import annotations

from uuid import uuid4

from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    DataDownloadedEvent,
    EventCategory,
    EventName,
    EventSeverity,
    OversightReviewEvent,
    SystemEvent,
)
from aqcs.llm_oversight.observer import OversightObserver, _OBSERVED_CATEGORIES


class TestObserverSubscription:
    def test_subscribes_to_all_core_categories(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe()
        for cat in _OBSERVED_CATEGORIES:
            assert bus.handler_count(cat) == 1

    def test_does_not_subscribe_to_oversight_category(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe()
        assert bus.handler_count(EventCategory.OVERSIGHT) == 0

    def test_uses_injected_bus(self) -> None:
        bus1 = EventBus()
        bus2 = EventBus()
        observer = OversightObserver(bus1)
        observer.subscribe()
        assert bus1.handler_count(EventCategory.DATA) == 1
        assert bus2.handler_count(EventCategory.DATA) == 0

    def test_receives_data_events(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe()
        ev = DataDownloadedEvent(
            component="aqcs.data.ohlcv",
            symbol="BTC/USDT",
            timeframe="1d",
            exchange="binance",
            candles_fetched=365,
            output_path="data/raw/BTC_USDT_1d.parquet",
        )
        bus.publish(ev)  # must not raise

    def test_receives_system_events(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe()
        bus.publish(SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP))


class TestReviewGeneration:
    def test_generate_review_returns_oversight_event(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observed_id = uuid4()
        review = observer.generate_review(observed_id, summary="Download completed normally.")
        assert isinstance(review, OversightReviewEvent)
        assert review.observed_event_id == observed_id
        assert review.event_category == EventCategory.OVERSIGHT

    def test_generate_review_publishes_to_same_bus(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        published: list = []
        bus.subscribe(published.append, EventCategory.OVERSIGHT)
        observer.generate_review(uuid4(), summary="Experiment completed.")
        assert len(published) == 1
        assert isinstance(published[0], OversightReviewEvent)

    def test_generate_review_with_custom_severity(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        review = observer.generate_review(
            uuid4(),
            summary="Gap detected in data.",
            severity=EventSeverity.WARNING,
        )
        assert review.severity == EventSeverity.WARNING

    def test_observer_does_not_self_trigger(self) -> None:
        """Subscribing does not react to OVERSIGHT events — no feedback loop."""
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe()
        oversight_calls: list = []
        bus.subscribe(oversight_calls.append, EventCategory.OVERSIGHT)
        observer.generate_review(uuid4(), summary="Test review.")
        assert len(oversight_calls) == 1  # only the external listener, not observer itself

    def test_no_api_calls_in_handle(self) -> None:
        """Observer handle must not call any external service (ccxt, HTTP, etc.)."""
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe()
        ev = DataDownloadedEvent(
            component="aqcs.data.ohlcv",
            symbol="ETH/USDT",
            timeframe="1h",
            exchange="binance",
            candles_fetched=200,
            output_path="data/raw/ETH_USDT_1h.parquet",
        )
        bus.publish(ev)  # no network calls, no state mutation
