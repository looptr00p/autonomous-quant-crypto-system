"""LLM Oversight observer — receives OversightEvents and writes human-readable logs.

This module NEVER issues orders, modifies state, or calls external APIs.
Its sole purpose is to log and document what the quant components are doing.
"""

from __future__ import annotations

from pathlib import Path

from src.utils.events import OversightEvent
from src.utils.logging import get_logger

logger = get_logger(__name__)

_BITACORA_DIR = Path("docs/bitacora")


def observe(event: OversightEvent) -> None:
    """Log an oversight event. No side effects beyond writing logs."""
    logger.info(
        "oversight_event",
        event_id=str(event.event_id),
        category=event.category.value,
        severity=event.severity.value,
        source=event.source,
        quant_component=event.quant_component,
        message=event.message,
        payload=event.payload,
    )
