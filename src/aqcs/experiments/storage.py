"""Local JSON storage for experiment records.

Storage layout:
  <storage_dir>/
    YYYY-MM-DD/
      experiment_<uuid>.json

Rules:
- Atomic writes via tmp-then-rename (no partial files on failure)
- UTF-8 encoding throughout
- Stable 2-space indented JSON (deterministic output)
- Date directory from timestamp_started_utc
"""

from __future__ import annotations

import json
from pathlib import Path

from aqcs.experiments.models import ExperimentRecord


def save_experiment_json(record: ExperimentRecord, storage_dir: Path) -> Path:
    """Persist an experiment record to a date-partitioned JSON file.

    Uses tmp-then-rename to prevent partial writes on failure.
    Overwrites if the file already exists (for status updates).
    """
    date_str = record.timestamp_started_utc.strftime("%Y-%m-%d")
    dest_dir = storage_dir / date_str
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / f"experiment_{record.experiment_id}.json"
    tmp = dest.with_suffix(".tmp.json")

    data = record.model_dump(mode="json")
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(dest)

    return dest


def load_experiment_json(path: Path) -> ExperimentRecord:
    """Load and validate an experiment record from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentRecord.model_validate(data)


def list_experiments(storage_dir: Path) -> list[Path]:
    """Return all experiment JSON files sorted by date directory and filename."""
    if not storage_dir.is_dir():
        return []
    return sorted(storage_dir.rglob("experiment_*.json"))
