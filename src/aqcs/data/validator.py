"""OHLCV data validation — schema, consistency, and quality checks.

Validates a DataFrame before it is persisted to Parquet.
Emits typed events to an optional EventBus; callers decide whether to abort.

Checks performed (in order):
 1. Non-empty dataset
 2. Required columns present (schema)
 3. Nulls in OHLCV columns
 4. UTC-aware timestamp (naive and non-UTC timezones rejected)
 5. Duplicate timestamps
 6. Strictly increasing timestamps
 7. Price positivity (open, high, low, close > 0)
 8. High >= Low
 9. Open within [low, high]
10. Close within [low, high]
11. Non-negative volume
12. Metadata consistency (symbol, timeframe match function arguments)
13. Gap detection (warning only — crypto trades 24/7)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _stdlib_tz

import pandas as pd

from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    DataGapDetectedEvent,
    DataSchemaMismatchEvent,
    DataValidationFailedEvent,
)
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS: list[str] = [
    "timestamp", "open", "high", "low", "close", "volume",
    "symbol", "timeframe", "exchange",
]

_PRICE_COLUMNS: list[str] = ["open", "high", "low", "close"]
_NUMERIC_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]

# Timezone name aliases that represent UTC (zero offset, no DST)
_UTC_NAMES: frozenset[str] = frozenset({"UTC", "UTC+00:00", "UTC-00:00", "+00:00"})

# Maps ccxt-style timeframe strings to pandas date_range freq aliases (pandas 2.x)
_TIMEFRAME_TO_FREQ: dict[str, str] = {
    "1d":  "1D",
    "4h":  "4h",
    "2h":  "2h",
    "1h":  "1h",
    "30m": "30min",
    "15m": "15min",
    "5m":  "5min",
    "1m":  "1min",
}


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a single validate_ohlcv call.

    Metadata fields (row_count, symbol, timeframe, exchange, start/end timestamps)
    are populated from what the validator can safely infer. For invalid datasets,
    fields that could not be determined are left as empty string or None.
    """

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_count: int = 0
    symbol: str = ""
    timeframe: str = ""
    exchange: str = ""
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_ohlcv(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    bus: EventBus | None = None,
    component: str = "aqcs.data.validator",
) -> ValidationResult:
    """Validate an OHLCV DataFrame before persistence.

    Args:
        df: DataFrame returned by fetch_ohlcv.
        symbol: Market symbol expected in the data, e.g. "BTC/USDT".
        timeframe: Candle timeframe expected in the data, e.g. "1d".
        bus: Optional EventBus — validation failures emit typed events if provided.
        component: Dotted module path for event attribution.

    Returns:
        ValidationResult with is_valid, errors (blocking), warnings (advisory),
        and dataset metadata populated from what can be safely inferred.

    Notes:
        The EventBus is optional in Phase 1. The CLI (ohlcv.py main()) does not
        wire a bus because there are no downstream event consumers yet. All errors
        and warnings are already logged via structlog regardless of the bus.
    """
    errors: list[str] = []
    warnings: list[str] = []

    def _fail(msg: str, event: object | None = None) -> None:
        errors.append(msg)
        if event is not None:
            _publish(bus, event)

    def _warn(msg: str, event: object | None = None) -> None:
        warnings.append(msg)
        if event is not None:
            _publish(bus, event)

    # ── 1. Non-empty dataset ──────────────────────────────────────────────────
    if df.empty:
        _fail(
            "DataFrame is empty",
            DataValidationFailedEvent(
                component=component,
                symbol=symbol,
                timeframe=timeframe,
                reason="DataFrame is empty",
                row_count=0,
            ),
        )
        logger.error("ohlcv_empty_dataframe", symbol=symbol, timeframe=timeframe)
        return ValidationResult(
            is_valid=False, errors=errors, warnings=warnings,
            symbol=symbol, timeframe=timeframe,
        )

    # ── 2. Schema: required columns ───────────────────────────────────────────
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        _fail(
            f"Missing columns: {missing}",
            DataSchemaMismatchEvent(
                component=component,
                symbol=symbol,
                timeframe=timeframe,
                expected_columns=REQUIRED_COLUMNS,
                actual_columns=list(df.columns),
            ),
        )
        logger.error("ohlcv_schema_mismatch", symbol=symbol, missing=missing)
        return ValidationResult(
            is_valid=False, errors=errors, warnings=warnings,
            row_count=len(df), symbol=symbol, timeframe=timeframe,
        )

    # ── 3. Nulls in numeric columns ───────────────────────────────────────────
    null_counts = df[_NUMERIC_COLUMNS].isnull().sum()
    null_cols = {col: int(cnt) for col, cnt in null_counts.items() if cnt > 0}
    if null_cols:
        msg = f"Null values in columns: {null_cols}"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_null_values", symbol=symbol, null_cols=null_cols)

    # ── 4. UTC-aware timestamp ────────────────────────────────────────────────
    ts_col = df["timestamp"]
    tz = ts_col.dt.tz
    if tz is None:
        msg = "timestamp column is naive (no timezone). Must be UTC."
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_naive_timestamps", symbol=symbol)
    elif not _is_utc(tz):
        msg = f"timestamp column must be UTC. Found timezone '{tz}'."
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_non_utc_timestamps", symbol=symbol, tz=str(tz))

    # ── 5. Duplicate timestamps ───────────────────────────────────────────────
    dupes = int(ts_col.duplicated().sum())
    if dupes > 0:
        msg = f"{dupes} duplicate timestamp(s)"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_duplicate_timestamps", symbol=symbol, count=dupes)

    # ── 6. Strictly increasing timestamps ────────────────────────────────────
    if not ts_col.is_monotonic_increasing:
        msg = "timestamps are not strictly increasing (non-monotonic order)"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_non_monotonic_timestamps", symbol=symbol)

    # Halt structural checks — consistency comparisons would be misleading
    if errors:
        return ValidationResult(
            is_valid=False, errors=errors, warnings=warnings,
            row_count=len(df), symbol=symbol, timeframe=timeframe,
        )

    # ── 7. Price positivity ───────────────────────────────────────────────────
    non_positive = int((df[_PRICE_COLUMNS] <= 0).any(axis=1).sum())
    if non_positive > 0:
        msg = f"{non_positive} row(s) with non-positive price(s)"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_non_positive_prices", symbol=symbol, rows=non_positive)

    # ── 8. High >= Low ────────────────────────────────────────────────────────
    high_lt_low = int((df["high"] < df["low"]).sum())
    if high_lt_low > 0:
        msg = f"{high_lt_low} row(s) where high < low"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_high_lt_low", symbol=symbol, rows=high_lt_low)

    # ── 9. Open within [low, high] ────────────────────────────────────────────
    open_oob = int(((df["open"] < df["low"]) | (df["open"] > df["high"])).sum())
    if open_oob > 0:
        msg = f"{open_oob} row(s) where open is outside [low, high]"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_open_out_of_range", symbol=symbol, rows=open_oob)

    # ── 10. Close within [low, high] ──────────────────────────────────────────
    close_oob = int(((df["close"] < df["low"]) | (df["close"] > df["high"])).sum())
    if close_oob > 0:
        msg = f"{close_oob} row(s) where close is outside [low, high]"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_close_out_of_range", symbol=symbol, rows=close_oob)

    # ── 11. Non-negative volume ───────────────────────────────────────────────
    neg_volume = int((df["volume"] < 0).sum())
    if neg_volume > 0:
        msg = f"{neg_volume} row(s) with negative volume"
        _fail(msg, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_negative_volume", symbol=symbol, rows=neg_volume)

    # ── 12. Metadata consistency ──────────────────────────────────────────────
    _check_metadata(df, symbol, timeframe, errors, bus, component)

    # ── 13. Gap detection (warning only) ──────────────────────────────────────
    if len(df) >= 2:
        _check_gaps(df, symbol, timeframe, warnings, bus, component)

    # ── Build result with metadata ─────────────────────────────────────────────
    is_valid = not errors
    exchange = str(df["exchange"].iloc[0]) if "exchange" in df.columns else ""
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    if "timestamp" in df.columns and not df["timestamp"].empty:
        try:
            start_ts = df["timestamp"].min().to_pydatetime()
            end_ts = df["timestamp"].max().to_pydatetime()
        except Exception:
            pass

    if is_valid:
        logger.info(
            "ohlcv_validation_passed",
            symbol=symbol, timeframe=timeframe,
            rows=len(df), warnings=len(warnings),
        )

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        row_count=len(df),
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _publish(bus: EventBus | None, event: object) -> None:
    if bus is not None:
        bus.publish(event)  # type: ignore[arg-type]


def _is_utc(tz: object) -> bool:
    """Return True only if tz is unambiguously UTC with zero offset.

    Checks both the timezone name (against known UTC aliases) and the stdlib
    identity to avoid false positives from DST-shifting timezones like
    Europe/London (which has offset +0 in winter but +1 in summer).
    """
    if tz is _stdlib_tz.utc:
        return True
    return str(tz).upper() in _UTC_NAMES


def _check_metadata(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    errors: list[str],
    bus: EventBus | None,
    component: str,
) -> None:
    for col in ("symbol", "timeframe", "exchange"):
        if df[col].isnull().any() or (df[col] == "").any():
            msg = f"'{col}' column contains empty or null values"
            errors.append(msg)
            _publish(bus, DataValidationFailedEvent(
                component=component, symbol=symbol, timeframe=timeframe,
                reason=msg, row_count=len(df),
            ))
            logger.error("ohlcv_empty_metadata", col=col, symbol=symbol)

    # Cross-check against function arguments
    mismatched_symbols = (df["symbol"] != symbol).sum()
    if mismatched_symbols > 0:
        msg = f"{mismatched_symbols} row(s) have symbol != '{symbol}'"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_symbol_mismatch", expected=symbol, rows=mismatched_symbols)

    mismatched_tf = (df["timeframe"] != timeframe).sum()
    if mismatched_tf > 0:
        msg = f"{mismatched_tf} row(s) have timeframe != '{timeframe}'"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component, symbol=symbol, timeframe=timeframe,
            reason=msg, row_count=len(df),
        ))
        logger.error("ohlcv_timeframe_mismatch", expected=timeframe, rows=mismatched_tf)


def _check_gaps(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    warnings: list[str],
    bus: EventBus | None,
    component: str,
) -> None:
    freq = _TIMEFRAME_TO_FREQ.get(timeframe)
    if freq is None:
        return

    df_sorted = df.sort_values("timestamp")
    first = df_sorted["timestamp"].iloc[0]
    last = df_sorted["timestamp"].iloc[-1]
    expected = pd.date_range(start=first, end=last, freq=freq, tz="UTC")
    actual = set(df_sorted["timestamp"].tolist())
    missing_ts = sorted(t for t in expected if t not in actual)

    if not missing_ts:
        return

    missing_bars = len(missing_ts)
    gap_start = missing_ts[0].strftime("%Y-%m-%dT%H:%M:%SZ")
    gap_end = missing_ts[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = f"{missing_bars} missing bar(s): {gap_start} to {gap_end}"
    warnings.append(msg)
    _publish(bus, DataGapDetectedEvent(
        component=component,
        symbol=symbol,
        timeframe=timeframe,
        gap_start=gap_start,
        gap_end=gap_end,
        missing_bars=missing_bars,
    ))
    logger.warning(
        "ohlcv_gaps_detected",
        symbol=symbol, timeframe=timeframe,
        missing_bars=missing_bars, gap_start=gap_start, gap_end=gap_end,
    )
