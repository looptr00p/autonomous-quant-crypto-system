"""LLM Oversight observer — subscribes to Quant Core events, may generate OversightReviewEvents.

Boundary rules (enforced architecturally):
- This module may import only from aqcs.utils.
- It NEVER modifies Quant Core state.
- It NEVER calls exchange APIs.
- It NEVER generates executable trading decisions.
- It subscribes to CORE event categories, not to OVERSIGHT events (no self-referential loop).
- It MAY generate OversightReviewEvents and publish them back to the bus.
"""

from __future__ import annotations

from uuid import UUID

from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    BaseEvent,
    EventCategory,
    EventSeverity,
    OversightReviewEvent,
)
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)

_OBSERVED_CATEGORIES = [
    EventCategory.DATA,
    EventCategory.VALIDATION,
    EventCategory.CONFIG,
    EventCategory.EXPERIMENT,
    EventCategory.PHASE_GUARD,
    EventCategory.SIGNAL,
    EventCategory.RISK,
    EventCategory.BACKTESTING,
    EventCategory.SYSTEM,
]


class OversightObserver:
    """Passive observer that subscribes to Quant Core events.

    Does not subscribe to EventCategory.OVERSIGHT to avoid self-referential loops.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def subscribe(self, source_bus: EventBus) -> None:
        """Register this observer on all core event categories."""
        for category in _OBSERVED_CATEGORIES:
            source_bus.subscribe(self._handle_core_event, category)

    def _handle_core_event(self, event: BaseEvent) -> None:
        """Log any received core event. No state mutation, no external calls."""
        logger.info(
            "oversight_observing",
            event_id=str(event.event_id),
            event_name=event.event_name.value,
            event_category=event.event_category.value,
            severity=event.severity.value,
            component=event.component,
        )

    def generate_review(
        self,
        observed_event_id: UUID,
        summary: str,
        *,
        component: str = "aqcs.llm_oversight.observer",
        severity: EventSeverity = EventSeverity.INFO,
    ) -> OversightReviewEvent:
        """Generate and publish an OversightReviewEvent.

        Called externally (e.g., by an LLM session) after reviewing a set of events.
        The review is published to the bus for storage and auditability.
        """
        review = OversightReviewEvent(
            component=component,
            severity=severity,
            observed_event_id=observed_event_id,
            summary=summary,
        )
        self._bus.publish(review)
        return review
