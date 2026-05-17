"""ExperimentTracker — creates, transitions, and persists experiment records.

Design constraints:
- Synchronous only
- Local file storage only
- No global singleton (dependency injection)
- EventBus is optional
- Deterministic: same inputs always produce same structure
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from aqcs.experiments.fingerprint import fingerprint_dataset, get_git_commit_hash
from aqcs.experiments.models import ExperimentRecord, ExperimentStatus
from aqcs.experiments.storage import save_experiment_json
from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    ExperimentCompletedEvent,
    ExperimentFailedEvent,
    ExperimentStartedEvent,
)
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)

_UTC = timezone.utc

# Statuses from which an experiment can be completed or failed
_ACTIVE_STATUSES = frozenset({ExperimentStatus.CREATED, ExperimentStatus.RUNNING})


class ExperimentTracker:
    """Creates and manages experiment lifecycle with local JSON persistence.

    Usage:
        tracker = ExperimentTracker(storage_dir=Path("experiments"))
        record = tracker.create_experiment("btc_momentum_v1", parameters={...})
        tracker.complete_experiment(record.experiment_id, metrics={"sharpe": 1.4})
    """

    def __init__(
        self,
        storage_dir: Path,
        *,
        bus: EventBus | None = None,
        component: str = "aqcs.experiments.tracker",
    ) -> None:
        self._storage_dir = storage_dir
        self._bus = bus
        self._component = component
        self._records: dict[UUID, ExperimentRecord] = {}

    def create_experiment(
        self,
        name: str,
        experiment_type: str = "research",
        *,
        parameters: dict[str, Any] | None = None,
        config_path: str = "",
        dataset_paths: list[str] | None = None,
        dataset_root: Path | None = None,
        tags: list[str] | None = None,
        notes: str = "",
        capture_git: bool = True,
        repo_root: Path | None = None,
        fingerprint_data: bool = True,
    ) -> ExperimentRecord:
        """Create a new experiment record in RUNNING state, save it, and emit a start event.

        Args:
            dataset_root: If provided, dataset fingerprints use paths relative
                          to this root for portability across machines.
            repo_root: Working directory for git hash capture. Defaults to cwd.
        """
        paths = dataset_paths or []
        git_hash = get_git_commit_hash(repo_root=repo_root) if capture_git else ""
        ds_fingerprint = (
            fingerprint_dataset([Path(p) for p in paths], dataset_root=dataset_root)
            if fingerprint_data and paths
            else ""
        )

        record = ExperimentRecord(
            experiment_name=name,
            experiment_type=experiment_type,
            status=ExperimentStatus.RUNNING,
            timestamp_started_utc=datetime.now(_UTC),
            git_commit_hash=git_hash,
            config_path=config_path,
            dataset_fingerprint=ds_fingerprint,
            dataset_paths=paths,
            parameters=parameters or {},
            tags=tags or [],
            notes=notes,
        )
        self._records[record.experiment_id] = record
        path = save_experiment_json(record, self._storage_dir)

        logger.info(
            "experiment_started",
            experiment_id=str(record.experiment_id),
            name=record.experiment_name,
            path=str(path),
        )
        if self._bus is not None:
            self._bus.publish(ExperimentStartedEvent(
                component=self._component,
                experiment_name=record.experiment_name,
                experiment_type=record.experiment_type,
                git_commit=record.git_commit_hash,
                dataset_fingerprint=record.dataset_fingerprint,
                dataset_paths=record.dataset_paths,
            ))

        return record

    def complete_experiment(
        self,
        experiment_id: UUID,
        *,
        metrics: dict[str, float] | None = None,
        artifacts: list[str] | None = None,
        notes: str = "",
    ) -> ExperimentRecord:
        """Transition experiment to COMPLETED, update metrics, save, and emit event."""
        record = self._require_active(experiment_id)

        now = datetime.now(_UTC)
        record.status = ExperimentStatus.COMPLETED
        record.timestamp_completed_utc = now
        record.duration_seconds = (now - record.timestamp_started_utc).total_seconds()
        if metrics:
            record.metrics.update(metrics)
        if artifacts:
            record.artifacts.extend(artifacts)
        if notes:
            record.notes = notes if not record.notes else f"{record.notes}\n{notes}"

        path = save_experiment_json(record, self._storage_dir)

        logger.info(
            "experiment_completed",
            experiment_id=str(record.experiment_id),
            name=record.experiment_name,
            duration_seconds=record.duration_seconds,
            path=str(path),
        )
        if self._bus is not None:
            self._bus.publish(ExperimentCompletedEvent(
                component=self._component,
                experiment_name=record.experiment_name,
                duration_seconds=record.duration_seconds or 0.0,
                output_path=str(path),
                metrics=record.metrics,
            ))

        return record

    def fail_experiment(
        self,
        experiment_id: UUID,
        *,
        reason: str = "",
    ) -> ExperimentRecord:
        """Transition experiment to FAILED, record reason, save, and emit event."""
        record = self._require_active(experiment_id)

        now = datetime.now(_UTC)
        record.status = ExperimentStatus.FAILED
        record.timestamp_completed_utc = now
        record.duration_seconds = (now - record.timestamp_started_utc).total_seconds()
        if reason:
            record.notes = (
                f"FAILED: {reason}" if not record.notes
                else f"{record.notes}\nFAILED: {reason}"
            )

        path = save_experiment_json(record, self._storage_dir)

        logger.error(
            "experiment_failed",
            experiment_id=str(record.experiment_id),
            name=record.experiment_name,
            reason=reason,
            path=str(path),
        )
        if self._bus is not None:
            self._bus.publish(ExperimentFailedEvent(
                component=self._component,
                experiment_name=record.experiment_name,
                reason=reason,
                duration_seconds=record.duration_seconds or 0.0,
            ))

        return record

    def save_experiment(self, record: ExperimentRecord) -> Path:
        """Explicitly persist an experiment record to disk and return its path."""
        return save_experiment_json(record, self._storage_dir)

    def get_experiment(self, experiment_id: UUID) -> ExperimentRecord | None:
        """Return an in-memory record by ID, or None if not tracked."""
        return self._records.get(experiment_id)

    def _require_active(self, experiment_id: UUID) -> ExperimentRecord:
        record = self._records.get(experiment_id)
        if record is None:
            raise KeyError(f"Experiment {experiment_id} not found in this tracker")
        if record.status not in _ACTIVE_STATUSES:
            raise ValueError(
                f"Cannot transition experiment '{record.experiment_name}' "
                f"from status '{record.status}' — only {sorted(s.value for s in _ACTIVE_STATUSES)} "
                f"experiments can be completed or failed."
            )
        return record
