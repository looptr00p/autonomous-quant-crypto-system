# OBJ-002: Data Validation Layer

**Objective ID:** OBJ-002  
**Status:** Complete  
**Phase:** 1  
**Date completed:** 2026-05-17  
**Parent:** OBJ-001

---

## Purpose

Create a complete, institutionally sound validation layer that prevents invalid OHLCV data from being persisted to Parquet and emits typed events for observability.

The validator is the quality gate between market data acquisition and storage. No invalid data may reach `data/raw/`.

---

## Scope

- Schema validation (required columns)
- Null checking
- UTC timestamp enforcement (naive and non-UTC rejected)
- Duplicate timestamp rejection
- Monotonically increasing timestamp enforcement
- OHLCV price consistency (high ≥ low, prices > 0, open/close within [low, high], volume ≥ 0)
- Metadata consistency (symbol/timeframe match arguments; exchange non-empty)
- Gap detection for known timeframes (advisory warning only)
- Integration into the CLI download pipeline
- Optional EventBus emission of typed events
- `ValidationResult` with metadata fields

Not in scope: cross-symbol consistency, statistical outlier detection, volume profile analysis.

---

## Completed deliverables

| Deliverable | Files | Tests |
|-------------|-------|-------|
| Validator module | `src/aqcs/data/validator.py` | `tests/unit/test_validator.py` |
| CLI integration | `src/aqcs/data/ohlcv.py` (validate before save) | `tests/unit/test_ohlcv.py::TestCLIPipelineValidation` |
| Validation documentation | `docs/architecture/data-validation.md` | — |
| ValidationResult metadata fields | `validator.py::ValidationResult` | `test_validator.py::TestValidationResultMetadata` |

---

## Acceptance criteria

- [x] Empty DataFrames rejected
- [x] Missing columns emit `DataSchemaMismatchEvent` and abort
- [x] Null values in OHLCV columns rejected
- [x] Naive timestamps rejected with clear error message
- [x] Non-UTC timezone-aware timestamps rejected (including Europe/London winter)
- [x] Duplicate timestamps rejected (separate error from monotonic check)
- [x] Non-monotonic timestamps rejected (separate error from duplicate check)
- [x] Prices ≤ 0 rejected
- [x] High < Low rejected
- [x] Open outside [Low, High] rejected
- [x] Close outside [Low, High] rejected
- [x] Negative volume rejected
- [x] Symbol/timeframe mismatch rejected
- [x] Empty exchange column rejected
- [x] Gaps produce warning, not error
- [x] CLI aborts with SystemExit(1) on validation failure
- [x] CLI saves Parquet when validation passes
- [x] Validation warnings do not block save
- [x] ValidationResult contains row_count, symbol, timeframe, exchange, start/end timestamps
- [x] 53+ tests in `test_validator.py`
- [x] 5+ CLI pipeline tests in `test_ohlcv.py`

---

## Related ADRs

- ADR-002: Quant Core determinism (validates that the Quant Core never processes invalid data)
- ADR-003: Event-logged architecture (EventBus used for validation events)
