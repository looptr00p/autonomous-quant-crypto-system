"""OHLCV data validation — schema, consistency, and quality checks.

Validates a DataFrame before it is persisted to Parquet.
Emits typed events to an optional EventBus; callers decide whether to abort.

Checks performed (in order):
1. Required columns present (schema)
2. No nulls in OHLCV price/volume columns
3. UTC-aware timestamp column
4. No duplicate timestamps
5. OHLCV price consistency (high >= low, prices > 0, volume >= 0)
6. Close and open within [low, high]
7. Gap detection (warning only — crypto trades 24/7)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from aqcs.utils.event_bus import EventBus
from aqcs.utils.events import (
    DataGapDetectedEvent,
    DataSchemaMismatchEvent,
    DataValidationFailedEvent,
    EventSeverity,
)
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS: list[str] = [
    "timestamp", "open", "high", "low", "close", "volume",
    "symbol", "timeframe", "exchange",
]

_PRICE_COLUMNS: list[str] = ["open", "high", "low", "close"]
_NUMERIC_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]

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


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a single validate_ohlcv call."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


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
        symbol: Market symbol, e.g. "BTC/USDT".
        timeframe: Candle timeframe, e.g. "1d".
        bus: Optional EventBus — if provided, validation failures emit typed events.
        component: Dotted module path for event attribution.

    Returns:
        ValidationResult with is_valid, errors (blocking), and warnings (advisory).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── 1. Schema: required columns ───────────────────────────────────────────
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        msg = f"Missing columns: {missing}"
        errors.append(msg)
        _publish(bus, DataSchemaMismatchEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            expected_columns=REQUIRED_COLUMNS,
            actual_columns=list(df.columns),
        ))
        logger.error("ohlcv_schema_mismatch", symbol=symbol, missing=missing)
        # Cannot continue further checks without required columns
        return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

    # ── 2. Nulls in numeric columns ───────────────────────────────────────────
    null_counts = df[_NUMERIC_COLUMNS].isnull().sum()
    null_cols = {col: int(cnt) for col, cnt in null_counts.items() if cnt > 0}
    if null_cols:
        msg = f"Null values in columns: {null_cols}"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_null_values", symbol=symbol, null_cols=null_cols)

    # ── 3. UTC-aware timestamp ────────────────────────────────────────────────
    ts_col = df["timestamp"]
    if not hasattr(ts_col.dtype, "tz") or ts_col.dt.tz is None:
        msg = "timestamp column is not UTC-aware (naive datetime)"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_naive_timestamps", symbol=symbol)

    # ── 4. Duplicate timestamps ───────────────────────────────────────────────
    dupes = int(df["timestamp"].duplicated().sum())
    if dupes > 0:
        msg = f"{dupes} duplicate timestamp(s)"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_duplicate_timestamps", symbol=symbol, count=dupes)

    # Stop here if structural errors found — consistency checks would be misleading
    if errors:
        return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

    # ── 5. Price positivity ───────────────────────────────────────────────────
    non_positive = int((df[_PRICE_COLUMNS] <= 0).any(axis=1).sum())
    if non_positive > 0:
        msg = f"{non_positive} row(s) with non-positive price(s)"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_non_positive_prices", symbol=symbol, rows=non_positive)

    # ── 6. High >= Low ────────────────────────────────────────────────────────
    high_lt_low = int((df["high"] < df["low"]).sum())
    if high_lt_low > 0:
        msg = f"{high_lt_low} row(s) where high < low"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_high_lt_low", symbol=symbol, rows=high_lt_low)

    # ── 7. Close within [low, high] ───────────────────────────────────────────
    close_oob = int(((df["close"] < df["low"]) | (df["close"] > df["high"])).sum())
    if close_oob > 0:
        msg = f"{close_oob} row(s) where close is outside [low, high]"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_close_out_of_range", symbol=symbol, rows=close_oob)

    # ── 8. Non-negative volume ────────────────────────────────────────────────
    neg_volume = int((df["volume"] < 0).sum())
    if neg_volume > 0:
        msg = f"{neg_volume} row(s) with negative volume"
        errors.append(msg)
        _publish(bus, DataValidationFailedEvent(
            component=component,
            symbol=symbol,
            timeframe=timeframe,
            reason=msg,
            row_count=len(df),
        ))
        logger.error("ohlcv_negative_volume", symbol=symbol, rows=neg_volume)

    # ── 9. Gap detection (advisory) ───────────────────────────────────────────
    if len(df) >= 2:
        _check_gaps(df, symbol, timeframe, warnings, bus, component)

    is_valid = not errors
    if is_valid:
        logger.info(
            "ohlcv_validation_passed",
            symbol=symbol,
            timeframe=timeframe,
            rows=len(df),
            warnings=len(warnings),
        )

    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _publish(bus: EventBus | None, event: object) -> None:
    if bus is not None:
        bus.publish(event)  # type: ignore[arg-type]


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
        return  # unknown timeframe — skip gap check

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
        symbol=symbol,
        timeframe=timeframe,
        missing_bars=missing_bars,
        gap_start=gap_start,
        gap_end=gap_end,
    )
