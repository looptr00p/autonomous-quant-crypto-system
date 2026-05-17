"""AQCS institutional event schema — typed, immutable, structured-payload records.

Design principles:
- No free-form message fields on BaseEvent (use typed payload fields instead).
- event_category and event_name are separated and validated for consistency.
- All events are immutable (Pydantic frozen=True).
- Timestamps are always UTC-aware; naive datetimes are rejected at construction time.
- SignalDirection is an Enum, not a free-form string.
- Events are data records, not RPC calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Enumerations ──────────────────────────────────────────────────────────────


class EventCategory(StrEnum):
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


class EventName(StrEnum):
    # data — acquisition events
    DATA_DOWNLOADED = "data.downloaded"
    # validation — data quality events
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


class EventSeverity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SignalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


# ── Category / name consistency contract ──────────────────────────────────────
# Each EventName has exactly one valid EventCategory. This mapping is the
# authoritative source; BaseEvent validates against it at construction time.

_VALID_CATEGORY_FOR_NAME: dict[EventName, EventCategory] = {
    EventName.DATA_DOWNLOADED: EventCategory.DATA,
    EventName.DATA_VALIDATION_FAILED: EventCategory.VALIDATION,
    EventName.DATA_SCHEMA_MISMATCH: EventCategory.VALIDATION,
    EventName.DATA_GAP_DETECTED: EventCategory.VALIDATION,
    EventName.CONFIG_LOADED: EventCategory.CONFIG,
    EventName.PHASE_CONSTRAINT_BLOCKED: EventCategory.PHASE_GUARD,
    EventName.ARCHITECTURE_BOUNDARY_VIOLATION: EventCategory.ARCHITECTURE,
    EventName.EXPERIMENT_STARTED: EventCategory.EXPERIMENT,
    EventName.EXPERIMENT_COMPLETED: EventCategory.EXPERIMENT,
    EventName.EXPERIMENT_FAILED: EventCategory.EXPERIMENT,
    EventName.SIGNAL_GENERATED: EventCategory.SIGNAL,
    EventName.PORTFOLIO_WEIGHTS_COMPUTED: EventCategory.PORTFOLIO,
    EventName.RISK_CHECK_PASSED: EventCategory.RISK,
    EventName.RISK_CHECK_FAILED: EventCategory.RISK,
    EventName.BACKTEST_STARTED: EventCategory.BACKTESTING,
    EventName.BACKTEST_COMPLETED: EventCategory.BACKTESTING,
    EventName.BACKTEST_FAILED: EventCategory.BACKTESTING,
    EventName.OVERSIGHT_REVIEW_GENERATED: EventCategory.OVERSIGHT,
    EventName.SYSTEM_STARTUP: EventCategory.SYSTEM,
    EventName.SYSTEM_SHUTDOWN: EventCategory.SYSTEM,
}


# ── Base event contract ───────────────────────────────────────────────────────

EVENT_SCHEMA_VERSION = "1.0"


class BaseEvent(BaseModel):
    """Immutable base for all AQCS system events.

    Invariants enforced at construction time:
    - timestamp_utc must be UTC-aware (naive datetimes are rejected).
    - event_category must match the canonical category for event_name.
    """

    event_id: UUID = Field(default_factory=uuid4)
    event_version: str = EVENT_SCHEMA_VERSION
    event_category: EventCategory
    event_name: EventName
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    component: str
    severity: EventSeverity = EventSeverity.INFO
    correlation_id: UUID | None = None
    run_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @field_validator("timestamp_utc", mode="before")
    @classmethod
    def require_utc_aware(cls, v: object) -> object:
        if not isinstance(v, datetime):
            return v
        if v.tzinfo is None:
            raise ValueError(
                "timestamp_utc must be UTC-aware. "
                "Use datetime.now(timezone.utc) or attach tzinfo=timezone.utc."
            )
        offset = v.utcoffset()
        if offset is not None and offset.total_seconds() != 0:
            raise ValueError(
                f"timestamp_utc must be UTC (offset 0). Got offset {v.utcoffset()}. "
                "Convert to UTC before constructing an event."
            )
        return v

    @model_validator(mode="after")
    def require_consistent_category(self) -> BaseEvent:
        expected = _VALID_CATEGORY_FOR_NAME.get(self.event_name)
        if expected is not None and self.event_category != expected:
            raise ValueError(
                f"event_name '{self.event_name.value}' requires "
                f"event_category '{expected.value}', "
                f"got '{self.event_category.value}'."
            )
        return self


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
    severity: EventSeverity = EventSeverity.WARNING
    symbol: str
    timeframe: str
    reason: str
    row_count: int = 0


class DataSchemaMismatchEvent(BaseEvent):
    event_category: EventCategory = EventCategory.VALIDATION
    event_name: EventName = EventName.DATA_SCHEMA_MISMATCH
    severity: EventSeverity = EventSeverity.ERROR
    symbol: str
    timeframe: str
    expected_columns: list[str]
    actual_columns: list[str]


class DataGapDetectedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.VALIDATION
    event_name: EventName = EventName.DATA_GAP_DETECTED
    severity: EventSeverity = EventSeverity.WARNING
    symbol: str
    timeframe: str
    gap_start: str
    gap_end: str
    missing_bars: int


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
    experiment_type: str = "research"
    git_commit: str = ""
    dataset_fingerprint: str = ""
    dataset_paths: list[str] = Field(default_factory=list)


class ExperimentCompletedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.EXPERIMENT
    event_name: EventName = EventName.EXPERIMENT_COMPLETED
    experiment_name: str
    duration_seconds: float
    output_path: str
    metrics: dict[str, float] = Field(default_factory=dict)


class ExperimentFailedEvent(BaseEvent):
    event_category: EventCategory = EventCategory.EXPERIMENT
    event_name: EventName = EventName.EXPERIMENT_FAILED
    severity: EventSeverity = EventSeverity.ERROR
    experiment_name: str
    reason: str
    duration_seconds: float = 0.0


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
