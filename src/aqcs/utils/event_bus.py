"""Synchronous, in-process event bus — dependency-injected, no global singleton.

Design constraints:
- Synchronous only. No async, no threading.
- No global bus instance. Components receive a bus via dependency injection.
- One failing handler does not crash the remaining handlers.
- No persistence, no replay, no distributed delivery.
"""

from __future__ import annotations

from collections.abc import Callable

from aqcs.utils.events import BaseEvent, EventCategory
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[BaseEvent], None]


class EventBus:
    """In-process synchronous event dispatcher.

    Usage:
        bus = EventBus()

        def my_handler(event: BaseEvent) -> None:
            print(event.event_name)

        bus.subscribe(my_handler, EventCategory.DATA)
        bus.publish(some_data_event)
    """

    def __init__(self) -> None:
        self._category_handlers: dict[EventCategory, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []

    def subscribe(
        self,
        handler: EventHandler,
        category: EventCategory | None = None,
    ) -> None:
        """Register a handler for a specific category, or for all events if category is None."""
        if category is None:
            self._global_handlers.append(handler)
        else:
            self._category_handlers.setdefault(category, []).append(handler)

    def publish(self, event: BaseEvent) -> None:
        """Dispatch event to all registered handlers.

        Exceptions from individual handlers are caught and logged.
        A failing handler does not prevent remaining handlers from running.
        """
        handlers = list(self._global_handlers) + list(
            self._category_handlers.get(event.event_category, [])
        )
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.error(
                    "event_handler_failed",
                    handler=getattr(handler, "__qualname__", repr(handler)),
                    event_id=str(event.event_id),
                    event_name=event.event_name.value,
                    event_category=event.event_category.value,
                    error=str(exc),
                )

    def handler_count(self, category: EventCategory | None = None) -> int:
        """Return the number of registered handlers (useful for testing)."""
        if category is None:
            total = len(self._global_handlers)
            for handlers in self._category_handlers.values():
                total += len(handlers)
            return total
        return len(self._category_handlers.get(category, []))
