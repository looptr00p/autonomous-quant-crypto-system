"""Experiment record models — typed, serializable, UTC-enforced."""

from __future__ import annotations

import json
import platform as _platform
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

_UTC_NAMES: frozenset[str] = frozenset({"UTC", "UTC+00:00", "UTC-00:00", "+00:00"})

# Allowed metric value types: JSON scalars only.
# bool must be listed before int — in Python, bool is a subclass of int.
MetricValue = Union[bool, int, float, str, None]


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

    All fields are JSON-serializable. Timestamps are always UTC.
    The record is mutable during the run (status transitions); identity
    fields (experiment_id, name, started_utc, git_commit_hash) never change.

    parameters: Must be JSON-serializable. Rejected at construction time if not.
    metrics: JSON scalars only (bool, int, float, str, None). No nested objects.
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
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
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

    @field_validator("parameters", mode="after")
    @classmethod
    def validate_parameters_json_serializable(cls, v: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"parameters must be JSON-serializable. "
                f"Remove Python objects that cannot be converted to JSON. Error: {exc}"
            ) from exc
        return v

    @field_validator("metrics", mode="before")
    @classmethod
    def validate_metrics_scalar_values(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        for key, value in v.items():
            if not isinstance(value, (bool, int, float, str, type(None))):
                raise ValueError(
                    f"metrics['{key}'] must be a JSON scalar "
                    f"(bool, int, float, str, or None). "
                    f"Got '{type(value).__name__}'. "
                    f"Nested objects are not allowed in metrics."
                )
        return v
