# AQCS Data Validation Layer — Phase 1

**Version:** 1.1.0  
**Date:** 2026-05-17  
**Status:** Active  
**Implementation:** `src/aqcs/data/validator.py`

---

## Purpose

The data validation layer is the quality gate between market data acquisition and Parquet persistence. It runs on every DataFrame returned by `fetch_ohlcv` before it is written to disk.

Validation is explicit and caller-controlled: `validate_ohlcv()` returns a `ValidationResult`; the caller decides whether to abort. The CLI (`ohlcv.py main()`) aborts on errors. Library users (notebooks, backtesting) may choose to continue with warnings.

---

## Validation rules

### Blocking errors (prevent persistence)

Checks run in order. Structural errors (schema, empty, UTC) halt further checks to avoid cascading false positives.

| # | Check | Error message pattern |
|---|-------|-----------------------|
| 1 | Non-empty dataset | `"DataFrame is empty"` |
| 2 | Required columns present | `"Missing columns: [...]"` |
| 3 | No nulls in open/high/low/close/volume | `"Null values in columns: {...}"` |
| 4 | Timestamp column is UTC-aware | `"timestamp column is naive"` or `"must be UTC"` |
| 5 | No duplicate timestamps | `"N duplicate timestamp(s)"` |
| 6 | Timestamps strictly increasing | `"timestamps are not strictly increasing"` |
| 7 | All prices > 0 | `"N row(s) with non-positive price(s)"` |
| 8 | High >= Low | `"N row(s) where high < low"` |
| 9 | Open within [Low, High] | `"N row(s) where open is outside [low, high]"` |
| 10 | Close within [Low, High] | `"N row(s) where close is outside [low, high]"` |
| 11 | Volume >= 0 | `"N row(s) with negative volume"` |
| 12 | symbol column non-empty and matches argument | `"'symbol' column contains empty..."` |
| 12 | timeframe column non-empty and matches argument | `"'timeframe' column contains empty..."` |
| 12 | exchange column non-empty | `"'exchange' column contains empty..."` |

### Warnings (advisory — data may still be used)

| Check | Warning message pattern |
|-------|------------------------|
| Gap detection (known timeframes) | `"N missing bar(s): start to end"` |

Gap detection is only performed for known timeframes: `1d`, `4h`, `2h`, `1h`, `30m`, `15m`, `5m`, `1m`. Unknown timeframe strings skip the check silently.

---

## UTC requirement

All timestamps must be UTC-aware with zero offset. Two categories of timestamps are rejected:

**Naive datetimes** — no timezone information:
```python
pd.to_datetime("2024-01-01")  # naive — rejected
```

**Non-UTC timezone-aware datetimes** — even if offset is +0 at validation time:
```python
# America/New_York: offset -5h/-4h — rejected
pd.date_range(..., tz="America/New_York")

# Europe/London: offset +0 in winter, +1 in summer — rejected by name
pd.date_range(..., tz="Europe/London")

# UTC — accepted
pd.date_range(..., tz="UTC")
```

The check uses both the timezone name (compared against a known UTC alias set) and stdlib identity (`datetime.timezone.utc`). A timezone named "Europe/London" with a winter offset of +0 is correctly rejected because it is not semantically UTC.

---

## Gap detection assumptions

- Crypto markets trade 24/7 with no weekends or holidays.
- Every expected bar within the date range should be present.
- Gap detection compares the actual timestamp set against a `pd.date_range` at the declared frequency.
- Gaps are a warning, not an error — downloaded data from an exchange may legitimately have missing bars during outages.
- The gap event (`DataGapDetectedEvent`) records `gap_start`, `gap_end`, and `missing_bars` for downstream analysis.

---

## ValidationResult fields

`ValidationResult` is an immutable frozen dataclass.

| Field | Type | Description |
|-------|------|-------------|
| `is_valid` | `bool` | True if no blocking errors were found |
| `errors` | `list[str]` | Blocking validation failures |
| `warnings` | `list[str]` | Advisory issues (e.g., gaps) |
| `row_count` | `int` | Number of rows in the DataFrame (0 for empty) |
| `symbol` | `str` | Symbol from function argument |
| `timeframe` | `str` | Timeframe from function argument |
| `exchange` | `str` | Exchange read from `df["exchange"]`, or `""` on schema failure |
| `start_timestamp` | `datetime \| None` | Earliest timestamp, or None if unavailable |
| `end_timestamp` | `datetime \| None` | Latest timestamp, or None if unavailable |

For invalid datasets, metadata fields are populated from what can be safely inferred. `start_timestamp` and `end_timestamp` are `None` if the timestamp column failed its own validation.

---

## EventBus behavior

`validate_ohlcv()` accepts an optional `bus: EventBus | None`. When provided, validation failures and warnings emit typed events:

| Condition | Event type |
|-----------|-----------|
| Missing columns | `DataSchemaMismatchEvent` |
| All other blocking errors | `DataValidationFailedEvent` |
| Gap detected | `DataGapDetectedEvent` |

All three events are in `EventCategory.VALIDATION`.

**Phase 1 note:** The CLI (`ohlcv.py main()`) does not wire a bus because there are no downstream event consumers in Phase 1. All errors and warnings are already logged via structlog regardless of bus presence. When a monitoring or oversight subscriber is added in Phase 2, a bus can be created in `main()` and passed through without any global state.

---

## API

```python
from aqcs.data.validator import validate_ohlcv, ValidationResult

# Basic usage — no bus
result = validate_ohlcv(df, symbol="BTC/USDT", timeframe="1d")
if not result.is_valid:
    raise ValueError(f"Validation failed: {result.errors}")

# With EventBus
from aqcs.utils.event_bus import EventBus
bus = EventBus()
bus.subscribe(my_handler)
result = validate_ohlcv(df, "BTC/USDT", "1d", bus=bus)

# Access metadata
print(result.row_count)        # 365
print(result.start_timestamp)  # 2023-01-01 00:00:00+00:00
print(result.exchange)         # "binance"
print(result.has_warnings)     # True if gaps detected
```

---

## Phase 1 limitations

- **No cross-symbol validation.** The validator processes one symbol at a time. Consistency between symbols (e.g., BTC/USDT and ETH/USDT correlations) is out of scope.
- **No historical baseline comparison.** The validator checks internal consistency of a single DataFrame. It does not compare against previously stored data.
- **Gap detection is heuristic.** Exchange outages, token launches, and low-liquidity periods may cause legitimate gaps. The gap warning is advisory.
- **No volume profile validation.** Zero volume is permitted. Suspiciously uniform volume across bars is not checked.
- **No outlier detection.** Price spikes or flash crashes are not filtered. Checks only enforce structural rules, not statistical plausibility.
- **No async.** Validation is synchronous and blocking. For large datasets, this is acceptable for Phase 1 batch downloads.
