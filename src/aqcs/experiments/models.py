"""Experiment record models — typed, serializable, UTC-enforced."""

from __future__ import annotations

import platform as _platform
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

_UTC_NAMES: frozenset[str] = frozenset({"UTC", "UTC+00:00", "UTC-00:00", "+00:00"})


def _require_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError(
            "Experiment timestamps must be UTC-aware. "
            "Use datetime.now(timezone.utc) or attach tzinfo=timezone.utc."
        )
    if not (v.tzinfo is timezone.utc or str(v.tzinfo).upper() in _UTC_NAMES):
        raise ValueError(
            f"Experiment timestamps must be UTC. Got timezone '{v.tzinfo}'."
        )
    return v


class ExperimentStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExperimentRecord(BaseModel):
    """Complete metadata record for a single experiment run.

    Designed for reproducibility and auditability — every field is
    JSON-serializable and captures enough context to reconstruct a run.

    Timestamps are always UTC. The record is mutable during the run
    (status transitions from RUNNING to COMPLETED/FAILED); identity
    fields (experiment_id, name, started_utc, git_commit_hash) never change.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    experiment_id: UUID = Field(default_factory=uuid4)
    experiment_name: str
    experiment_type: str = "research"
    status: ExperimentStatus = ExperimentStatus.CREATED

    # ── Timing (UTC enforced) ──────────────────────────────────────────────────
    timestamp_started_utc: datetime
    timestamp_completed_utc: datetime | None = None
    duration_seconds: float | None = None

    # ── Environment reproducibility ───────────────────────────────────────────
    git_commit_hash: str = ""
    python_version: str = Field(default_factory=lambda: sys.version)
    platform: str = Field(default_factory=_platform.platform)

    # ── Data provenance ───────────────────────────────────────────────────────
    config_path: str = ""
    dataset_fingerprint: str = ""
    dataset_paths: list[str] = Field(default_factory=list)

    # ── Research metadata ─────────────────────────────────────────────────────
    parameters: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    artifacts: list[str] = Field(default_factory=list)

    model_config = {"frozen": False}

    @field_validator("timestamp_started_utc", mode="before")
    @classmethod
    def validate_started_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime):
            return _require_utc(v)
        return v

    @field_validator("timestamp_completed_utc", mode="before")
    @classmethod
    def validate_completed_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime):
            return _require_utc(v)
        return v
