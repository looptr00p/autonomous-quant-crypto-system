"""Tests for the LLM Oversight observer — subscription and review generation."""

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
        observer.subscribe(bus)
        for cat in _OBSERVED_CATEGORIES:
            assert bus.handler_count(cat) == 1

    def test_does_not_subscribe_to_oversight_category(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe(bus)
        assert bus.handler_count(EventCategory.OVERSIGHT) == 0

    def test_receives_data_events(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe(bus)
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
        observer.subscribe(bus)
        bus.publish(SystemEvent(component="s", event_name=EventName.SYSTEM_STARTUP, description=""))


class TestReviewGeneration:
    def test_generate_review_returns_oversight_event(self) -> None:
        bus = EventBus()
        observer = OversightObserver(bus)
        observed_id = uuid4()
        review = observer.generate_review(observed_id, summary="Download completed normally.")
        assert isinstance(review, OversightReviewEvent)
        assert review.observed_event_id == observed_id
        assert review.event_category == EventCategory.OVERSIGHT

    def test_generate_review_publishes_to_bus(self) -> None:
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
        """Publishing an OversightReviewEvent must not re-trigger the observer."""
        bus = EventBus()
        observer = OversightObserver(bus)
        observer.subscribe(bus)
        oversight_calls: list = []
        bus.subscribe(oversight_calls.append, EventCategory.OVERSIGHT)
        observer.generate_review(uuid4(), summary="Test review.")
        assert len(oversight_calls) == 1
