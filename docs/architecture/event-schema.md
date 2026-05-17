# AQCS Event Schema — Phase 1

**Version:** 1.0  
**Date:** 2026-05-17  
**Status:** Active  
**Implementation:** `src/aqcs/utils/events.py`, `src/aqcs/utils/event_bus.py`

---

## Purpose

The AQCS event schema provides a structured, auditable record of everything that happens inside the system. Events are immutable data records — not RPC calls, not commands, not side-effecting messages.

Events exist for three reasons:

1. **Auditability** — every significant system action leaves a typed, timestamped record.
2. **Observability** — the LLM Oversight layer reads events passively without modifying system state.
3. **Reproducibility** — events capture enough context to reconstruct what happened during a run.

This is an **event-logged** architecture, not an event-driven one. There is no Kafka, no Redis streams, no Celery, no distributed broker, no replay framework, no schema registry, and no async processing.

---

## Event taxonomy

### Categories and names

Each `EventName` maps to exactly one `EventCategory`. This mapping is enforced at construction time — an invalid combination raises `ValueError`.

| Category | EventName | Typed class | Phase |
|----------|-----------|-------------|-------|
| `data` | `data.downloaded` | `DataDownloadedEvent` | 1 |
| `validation` | `data.validation_failed` | `DataValidationFailedEvent` | 1 |
| `validation` | `data.schema_mismatch` | `DataSchemaMismatchEvent` | 1 |
| `validation` | `data.gap_detected` | `DataGapDetectedEvent` | 1 |
| `config` | `config.loaded` | `ConfigLoadedEvent` | 1 |
| `phase_guard` | `phase_guard.constraint_blocked` | `PhaseConstraintBlockedEvent` | 1 |
| `architecture` | `architecture.boundary_violation` | *(BaseEvent + payload)* | 1 |
| `experiment` | `experiment.started` | `ExperimentStartedEvent` | 1 |
| `experiment` | `experiment.completed` | `ExperimentCompletedEvent` | 1 |
| `experiment` | `experiment.failed` | `ExperimentFailedEvent` | 1 |
| `signal` | `signal.generated` | `SignalGeneratedEvent` | 2+ |
| `portfolio` | `portfolio.weights_computed` | *(placeholder)* | 3+ |
| `risk` | `risk.check_passed` | `RiskCheckEvent` | 3+ |
| `risk` | `risk.check_failed` | `RiskCheckEvent` | 3+ |
| `backtesting` | `backtest.started` | *(placeholder)* | 2+ |
| `backtesting` | `backtest.completed` | *(placeholder)* | 2+ |
| `backtesting` | `backtest.failed` | *(placeholder)* | 2+ |
| `oversight` | `oversight.review_generated` | `OversightReviewEvent` | 1 |
| `system` | `system.startup` | `SystemEvent` | 1 |
| `system` | `system.shutdown` | `SystemEvent` | 1 |

Events marked **2+** or **3+** have typed classes as placeholders. Their fields may change when the corresponding component is implemented.

---

## BaseEvent contract

All events inherit from `BaseEvent`. Fields are immutable after construction (`frozen=True`).

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `event_id` | `UUID` | auto | `uuid4()` | — |
| `event_version` | `str` | auto | `"1.0"` | — |
| `event_category` | `EventCategory` | yes | — | Must match `event_name` mapping |
| `event_name` | `EventName` | yes | — | Must match `event_category` mapping |
| `timestamp_utc` | `datetime` | auto | `datetime.now(timezone.utc)` | Must be UTC-aware; naive datetimes rejected |
| `component` | `str` | yes | — | Dotted module path of emitter |
| `severity` | `EventSeverity` | no | `INFO` | One of: `debug`, `info`, `warning`, `error`, `critical` |
| `correlation_id` | `UUID \| None` | no | `None` | Shared across a pipeline run |
| `run_id` | `UUID \| None` | no | `None` | Shared across an experiment or backtest |
| `payload` | `dict[str, Any]` | no | `{}` | Ad-hoc structured data |
| `metadata` | `dict[str, Any]` | no | `{}` | Implementation context (git commit, env, etc.) |

**No human-readable message field.** Subclasses use typed fields; ad-hoc data goes in `payload`.

### UTC enforcement

```python
# Correct
from datetime import datetime, timezone
DataDownloadedEvent(timestamp_utc=datetime.now(timezone.utc), ...)

# Rejected — naive datetime
DataDownloadedEvent(timestamp_utc=datetime(2024, 1, 1), ...)  # ValueError

# Rejected — non-UTC offset
from datetime import timedelta
ts = datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=-5)))
DataDownloadedEvent(timestamp_utc=ts, ...)  # ValueError
```

### Category/name consistency

```python
# Correct
DataDownloadedEvent(event_category=EventCategory.DATA, ...)

# Rejected — wrong category for event_name
DataDownloadedEvent(event_category=EventCategory.RISK, ...)  # ValueError
```

---

## EventBus

```
src/aqcs/utils/event_bus.py
```

### Design

- **Synchronous only.** No threads, no async, no background execution.
- **No global singleton.** Components receive an `EventBus` instance via dependency injection.
- **Exception isolation.** One failing handler does not prevent remaining handlers from running. Failures are logged with full traceback via structlog (`exc_info=True`).
- **No persistence.** Events are dispatched in memory. For durable storage, connect a logging handler.

### API

```python
bus = EventBus()

# Subscribe to all events
bus.subscribe(my_handler)

# Subscribe to a specific category
bus.subscribe(my_handler, EventCategory.DATA)

# Publish
bus.publish(my_event)

# Query
bus.handler_count()                    # total handlers
bus.handler_count(EventCategory.DATA)  # handlers for a specific category
```

### Exception isolation example

```python
def bad_handler(event: BaseEvent) -> None:
    raise RuntimeError("broken")

def good_handler(event: BaseEvent) -> None:
    process(event)  # still runs even if bad_handler raises

bus.subscribe(bad_handler)
bus.subscribe(good_handler)
bus.publish(event)  # good_handler runs; bad_handler failure is logged
```

---

## LLM Oversight boundary

### What the observer does

`OversightObserver` subscribes to **core event categories** and may generate `OversightReviewEvent` records. It uses a single injected `EventBus` for both subscribing and publishing.

```python
bus = EventBus()
observer = OversightObserver(bus)
observer.subscribe()  # registers on the injected bus
```

### Subscribed categories

`DATA`, `VALIDATION`, `CONFIG`, `EXPERIMENT`, `PHASE_GUARD`, `SIGNAL`, `RISK`, `BACKTESTING`, `SYSTEM`.

### Not subscribed

`OVERSIGHT` — the observer does not react to its own output. This eliminates the possibility of a feedback loop where an `OversightReviewEvent` triggers another review.

### What the observer may do

- Read any event it receives.
- Log event fields via structlog.
- Call `generate_review(observed_event_id, summary)` to publish an `OversightReviewEvent`.

### What the observer must not do

- Modify any Quant Core state.
- Call exchange APIs (`ccxt` is not imported in `aqcs.llm_oversight`).
- Generate trading signals, weight adjustments, or risk overrides.
- Import from any `aqcs.*` package except `aqcs.utils`.

These constraints are enforced by `tests/architecture/test_dependency_boundaries.py` on every CI run.

---

## Event examples (valid JSON)

### `data.downloaded`

```json
{
  "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "event_version": "1.0",
  "event_category": "data",
  "event_name": "data.downloaded",
  "timestamp_utc": "2026-05-17T14:32:00.000000+00:00",
  "component": "aqcs.data.ohlcv",
  "severity": "info",
  "correlation_id": null,
  "run_id": null,
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "exchange": "binance",
  "candles_fetched": 365,
  "output_path": "data/raw/BTC_USDT_1d.parquet",
  "payload": {},
  "metadata": {}
}
```

### `data.gap_detected`

```json
{
  "event_category": "validation",
  "event_name": "data.gap_detected",
  "severity": "warning",
  "component": "aqcs.monitoring",
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "gap_start": "2024-01-15",
  "gap_end": "2024-01-17",
  "missing_bars": 2
}
```

### `phase_guard.constraint_blocked`

```json
{
  "event_category": "phase_guard",
  "event_name": "phase_guard.constraint_blocked",
  "severity": "warning",
  "component": "aqcs.utils.phase_guard",
  "feature": "machine_learning",
  "current_phase": 1
}
```

### `experiment.started`

```json
{
  "event_category": "experiment",
  "event_name": "experiment.started",
  "severity": "info",
  "component": "aqcs.experiments.tracker",
  "experiment_name": "btc_momentum_baseline_v1",
  "experiment_type": "signal_research",
  "git_commit": "abc1234def5678abc1234def5678abc1234def56",
  "dataset_fingerprint": "e3b0c44298fc1c149afbf4c8996fb924...",
  "dataset_paths": ["data/raw/BTC_USDT_1d.parquet"]
}
```

Note: `ExperimentStartedEvent` uses generic experiment metadata, not trading-specific
fields. For backtesting experiments, `dataset_paths` contains the data file list.

### `experiment.failed`

```json
{
  "event_category": "experiment",
  "event_name": "experiment.failed",
  "severity": "error",
  "component": "aqcs.experiments.tracker",
  "experiment_name": "btc_momentum_v1",
  "reason": "Data gap: 3 missing bars at 2024-01-15",
  "duration_seconds": 3.2
}
```

### `oversight.review_generated`

```json
{
  "event_category": "oversight",
  "event_name": "oversight.review_generated",
  "severity": "info",
  "component": "aqcs.llm_oversight.observer",
  "observed_event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "summary": "OHLCV download for BTC/USDT completed. 365 daily candles written to Parquet. No anomalies detected."
}
```

---

## Storage approach (Phase 1)

Events are dispatched in-memory via `EventBus`. To persist them, attach a handler that writes to a JSONL file or passes events to structlog:

```python
import json

def jsonl_writer(event: BaseEvent) -> None:
    with open("logs/events.jsonl", "a") as f:
        f.write(event.model_dump_json() + "\n")

bus.subscribe(jsonl_writer)
```

No database, no message broker, and no streaming infrastructure are required in Phase 1.

---

## Versioning

`event_version` follows semantic versioning (`"1.0"`, `"1.1"`, `"2.0"`). Rules:

- **Patch** (e.g., `"1.0"` → `"1.1"`): add optional fields, clarify documentation.
- **Minor** (e.g., `"1.0"` → `"1.1"`): add required fields with backward-compatible defaults.
- **Major** (e.g., `"1.0"` → `"2.0"`): rename fields, change field types, remove fields. Requires migration plan.

When `event_version` changes, the schema version constant in `events.py` (`EVENT_SCHEMA_VERSION`) is updated and all existing event classes are verified against the new contract.

---

## Phase 1 limitations

The following are explicitly out of scope for Phase 1:

- **No event replay** — events are fire-and-forget in-memory dispatches.
- **No durable event store** — JSONL logging is optional and not required.
- **No schema registry** — versioning is managed manually.
- **No distributed delivery** — all handlers run in the same process.
- **No async handlers** — `publish()` is synchronous and blocking.
- **No event sourcing** — the system is not rebuilt from events; Parquet files are the source of truth for data.

---

## Anti-patterns (explicitly rejected)

| Pattern | Why rejected |
|---------|-------------|
| Global singleton `bus = EventBus()` | Prevents testing; creates hidden coupling |
| Free-form direction strings `"up"`, `"down"` | Not type-safe; use `SignalDirection` enum |
| `message: str` on BaseEvent | Free text is not auditable; use typed fields |
| Kafka / Redis streams | Unnecessary complexity for a single-process research lab |
| Celery tasks | Async job queue has no value before Phase 3 live execution |
| Event sourcing | Parquet files are the source of truth; event sourcing adds reconstruction complexity |
| Distributed tracing | No distributed services exist in Phase 1 |
| Schema registry | Manual versioning is sufficient until event schema stabilises |
