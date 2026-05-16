"""System event schema — typed, immutable records for the event bus."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventCategory(str, Enum):
    DATA = "data"
    FEATURE = "feature"
    SIGNAL = "signal"
    PORTFOLIO = "portfolio"
    RISK = "risk"
    SYSTEM = "system"
    OVERSIGHT = "oversight"


class BaseEvent(BaseModel):
    """Immutable base for all AQCS system events."""

    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: EventCategory
    severity: EventSeverity = EventSeverity.INFO
    source: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class DataEvent(BaseEvent):
    category: EventCategory = EventCategory.DATA
    symbol: str
    timeframe: str
    candles_fetched: int = 0


class SystemEvent(BaseEvent):
    category: EventCategory = EventCategory.SYSTEM


class OversightEvent(BaseEvent):
    """Events emitted to the LLM Oversight layer — read-only observations."""

    category: EventCategory = EventCategory.OVERSIGHT
    quant_component: str
