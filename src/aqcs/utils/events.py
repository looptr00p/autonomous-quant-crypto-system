"""AQCS institutional event schema — typed, immutable, structured-payload records.

Design principles:
- No free-form message fields on BaseEvent (use typed payload fields instead).
- event_category and event_name are separated.
- All events are immutable (Pydantic frozen=True).
- SignalDirection is an Enum, not a free-form string.
- Events are data records, not RPC calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class EventCategory(str, Enum):
    DATA = "data"
    VALIDATION = "validation"
    CONFIG = "config"
    EXPERIMENT = "experiment"
    ARCHITECTURE = "architecture"
    PHASE_GUARD = "phase_guard"
    SIGNAL = "signal"
    PORTFOLIO = "portfolio"
    RISK = "risk"
    BACKTESTING = "backtesting"
    OVERSIGHT = "oversight"
    SYSTEM = "system"


class EventName(str, Enum):
    # data
    DATA_DOWNLOADED = "data.downloaded"
    DATA_VALIDATION_FAILED = "data.validation_failed"
    DATA_SCHEMA_MISMATCH = "data.schema_mismatch"
    DATA_GAP_DETECTED = "data.gap_detected"
    # config
    CONFIG_LOADED = "config.loaded"
    # phase guard
    PHASE_CONSTRAINT_BLOCKED = "phase_guard.constraint_blocked"
    # architecture enforcement
    ARCHITECTURE_BOUNDARY_VIOLATION = "architecture.boundary_violation"
    # experiment
    EXPERIMENT_STARTED = "experiment.started"
    EXPERIMENT_COMPLETED = "experiment.completed"
    EXPERIMENT_FAILED = "experiment.failed"
    # signal (placeholder — Phase 2+)
    SIGNAL_GENERATED = "signal.generated"
    # portfolio (placeholder — Phase 3+)
    PORTFOLIO_WEIGHTS_COMPUTED = "portfolio.weights_computed"
    # risk (placeholder — Phase 3+)
    RISK_CHECK_PASSED = "risk.check_passed"
    RISK_CHECK_FAILED = "risk.check_failed"
    # backtesting (placeholder — Phase 2+)
    BACKTEST_STARTED = "backtest.started"
    BACKTEST_COMPLETED = "backtest.completed"
    BACKTEST_FAILED = "backtest.failed"
    # oversight
    OVERSIGHT_REVIEW_GENERATED = "oversight.review_generated"
    # system
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"


class EventSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


# ── Base event contract ───────────────────────────────────────────────────────

EVENT_SCHEMA_VERSION = "1.0"


class BaseEvent(BaseModel):
    """Immutable base for all AQCS system events.

    No human-readable message field — use typed payload fields on subclasses
    or the payload dict for ad-hoc structured data.
    """

    event_id: UUID = Field(default_factory=uuid4)
    event_version: str = EVENT_SCHEMA_VERSION
    event_category: EventCategory
    event_name: EventName
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    component: str
    severity: EventSeverity = EventSeverity.INFO
    correlation_id: UUID | None = None
    run_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


# ── Typed event classes ───────────────────────────────────────────────────────

class DataDownloadedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.DATA
    event_name: EventName = EventName.DATA_DOWNLOADED
    symbol: str
    timeframe: str
    exchange: str
    candles_fetched: int
    output_path: str


class DataValidationFailedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.VALIDATION
    event_name: EventName = EventName.DATA_VALIDATION_FAILED
    symbol: str
    timeframe: str
    reason: str
    row_count: int = 0


class ConfigLoadedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.CONFIG
    event_name: EventName = EventName.CONFIG_LOADED
    env: str
    config_files: list[str] = Field(default_factory=list)


class PhaseConstraintBlockedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.PHASE_GUARD
    event_name: EventName = EventName.PHASE_CONSTRAINT_BLOCKED
    severity: EventSeverity = EventSeverity.WARNING
    feature: str
    current_phase: int


class ExperimentStartedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.EXPERIMENT
    event_name: EventName = EventName.EXPERIMENT_STARTED
    experiment_name: str
    git_commit: str
    symbols: list[str]
    timeframe: str
    start_date: str
    end_date: str


class ExperimentCompletedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.EXPERIMENT
    event_name: EventName = EventName.EXPERIMENT_COMPLETED
    experiment_name: str
    duration_seconds: float
    output_path: str
    metrics: dict[str, float] = Field(default_factory=dict)


class SignalGeneratedEvent(BaseEvent):
    """Placeholder — Phase 2+."""

    event_category: EventCategory = EventCategory.SIGNAL
    event_name: EventName = EventName.SIGNAL_GENERATED
    symbol: str
    timeframe: str
    direction: SignalDirection
    strength: float


class RiskCheckEvent(BaseEvent):
    """Placeholder — Phase 3+."""

    event_category: EventCategory = EventCategory.RISK
    event_name: EventName = EventName.RISK_CHECK_PASSED
    symbol: str
    original_weight: float
    adjusted_weight: float
    constraint_applied: str | None = None


class OversightReviewEvent(BaseEvent):
    """Generated by LLM Oversight when it summarises observed events."""

    event_category: EventCategory = EventCategory.OVERSIGHT
    event_name: EventName = EventName.OVERSIGHT_REVIEW_GENERATED
    observed_event_id: UUID
    summary: str


class SystemEvent(BaseEvent):
    event_category: EventCategory = EventCategory.SYSTEM
    description: str = ""
