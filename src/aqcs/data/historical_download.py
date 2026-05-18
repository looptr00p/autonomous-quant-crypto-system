"""Deterministic, resumable historical OHLCV downloader for local Parquet expansion.

Extends existing depth for BTC/USDT, ETH/USDT, SOL/USDT on 1h timeframe using
read-only Binance Spot public OHLCV data.  Duplicate-safe: merges with any
existing Parquet file and deduplicates on timestamp before saving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import ccxt
import pandas as pd

from aqcs.data.ohlcv import (
    _build_exchange,
    _timeframe_to_milliseconds,
    fetch_ohlcv,
    save_parquet,
)
from aqcs.data.validator import validate_ohlcv
from aqcs.utils.logging import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_SYMBOLS: frozenset[str] = frozenset({"BTC/USDT", "ETH/USDT", "SOL/USDT"})
SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset({"1h"})

_UTC_NAMES: frozenset[str] = frozenset({"UTC", "UTC+00:00", "UTC-00:00", "+00:00"})


# ── Result model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DownloadResult:
    """Summary of a single deterministic historical download run.

    ``rows_fetched`` is the count from the exchange in this run only.
    ``rows_total`` is the total count persisted (including prior data).
    ``resumed_from`` is ``None`` on a fresh download.
    """

    symbol: str
    timeframe: str
    parquet_path: Path
    rows_fetched: int
    rows_total: int
    resumed_from: datetime | None
    start_timestamp: datetime
    end_timestamp: datetime


# ── Public API ─────────────────────────────────────────────────────────────────


def download_historical_ohlcv(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    output_dir: Path,
    *,
    exchange: ccxt.Exchange | None = None,
    pagination_sleep_ms: int = 500,
    max_candles: int = 1000,
) -> DownloadResult:
    """Download and persist historical OHLCV candles with resumable behavior.

    If a Parquet file already exists for (symbol, timeframe), this function reads
    the file, determines the last persisted timestamp, and fetches only the missing
    candles.  Existing and new candles are merged, deduplicated on timestamp, and
    sorted before saving — making repeated runs idempotent.

    Args:
        symbol: Market symbol (must be in ``SUPPORTED_SYMBOLS``).
        timeframe: Candle timeframe (must be in ``SUPPORTED_TIMEFRAMES``).
        start: Inclusive UTC start of the desired date range.
        end: Exclusive UTC end of the desired date range.
        output_dir: Directory where the Parquet file is written.
        exchange: Optional pre-built ccxt Exchange.  A public Binance Spot
                  instance is created automatically when omitted.
        pagination_sleep_ms: Sleep between paginated requests (passed through
                             to ``fetch_ohlcv``).
        max_candles: Maximum candles per request (passed through to
                     ``fetch_ohlcv``).

    Returns:
        ``DownloadResult`` with counts and path of the persisted file.

    Raises:
        ValueError: Invalid symbol, timeframe, or date range; or if the
                    merged dataset fails structural validation.
        RuntimeError: No data was returned and there is no existing dataset.
    """
    _validate_inputs(symbol, timeframe, start, end)

    if exchange is None:
        exchange = _build_exchange(sandbox=False)

    safe_symbol = symbol.replace("/", "_")
    parquet_path = output_dir / f"{safe_symbol}_{timeframe}.parquet"

    existing_df = _load_existing(parquet_path)
    is_fresh = existing_df is None or existing_df.empty

    if is_fresh:
        cursor = start
        resumed_from: datetime | None = None
        logger.info(
            "historical_download_fresh",
            symbol=symbol,
            timeframe=timeframe,
            start=start.isoformat(),
            end=end.isoformat(),
        )
    else:
        assert existing_df is not None
        cursor = _resume_cursor(existing_df, timeframe)
        resumed_from = cursor
        logger.info(
            "historical_download_resuming",
            symbol=symbol,
            timeframe=timeframe,
            cursor=cursor.isoformat(),
            end=end.isoformat(),
            existing_rows=len(existing_df),
        )

    # Already fully up-to-date — nothing to fetch.
    if cursor >= end:
        assert existing_df is not None
        logger.info(
            "historical_download_already_current",
            symbol=symbol,
            timeframe=timeframe,
            last_ts=cursor.isoformat(),
        )
        return DownloadResult(
            symbol=symbol,
            timeframe=timeframe,
            parquet_path=parquet_path,
            rows_fetched=0,
            rows_total=len(existing_df),
            resumed_from=resumed_from,
            start_timestamp=existing_df["timestamp"].min().to_pydatetime(),
            end_timestamp=existing_df["timestamp"].max().to_pydatetime(),
        )

    fetched_df = fetch_ohlcv(
        symbol,
        timeframe,
        cursor,
        end,
        exchange=exchange,
        pagination_sleep_ms=pagination_sleep_ms,
        max_candles=max_candles,
    )
    rows_fetched = len(fetched_df)

    if fetched_df.empty and is_fresh:
        raise RuntimeError(
            f"No data returned from exchange for {symbol} {timeframe} "
            f"from {cursor.isoformat()} to {end.isoformat()}"
        )

    if not is_fresh:
        assert existing_df is not None
        merged_df = _merge_deduplicate(existing_df, fetched_df)
    else:
        merged_df = _normalize(fetched_df)

    validation = validate_ohlcv(
        merged_df, symbol, timeframe, component="aqcs.data.historical_download"
    )
    if not validation.is_valid:
        raise ValueError(
            f"Merged dataset for {symbol} {timeframe} failed validation: " f"{validation.errors}"
        )
    if validation.has_warnings:
        logger.warning(
            "historical_download_validation_warnings",
            symbol=symbol,
            timeframe=timeframe,
            warnings=validation.warnings,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    saved_path = save_parquet(merged_df, output_dir, symbol, timeframe)

    logger.info(
        "historical_download_complete",
        symbol=symbol,
        timeframe=timeframe,
        rows_fetched=rows_fetched,
        rows_total=len(merged_df),
        parquet_path=str(saved_path),
    )

    return DownloadResult(
        symbol=symbol,
        timeframe=timeframe,
        parquet_path=saved_path,
        rows_fetched=rows_fetched,
        rows_total=len(merged_df),
        resumed_from=resumed_from,
        start_timestamp=merged_df["timestamp"].min().to_pydatetime(),
        end_timestamp=merged_df["timestamp"].max().to_pydatetime(),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validate_inputs(symbol: str, timeframe: str, start: datetime, end: datetime) -> None:
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Unsupported symbol '{symbol}'. Supported: {sorted(SUPPORTED_SYMBOLS)}")
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. Supported: {sorted(SUPPORTED_TIMEFRAMES)}"
        )
    if start.tzinfo is None or not _is_utc(start.tzinfo):
        raise ValueError(f"start must be UTC-aware. Got tzinfo={start.tzinfo!r}")
    if end.tzinfo is None or not _is_utc(end.tzinfo):
        raise ValueError(f"end must be UTC-aware. Got tzinfo={end.tzinfo!r}")
    if start >= end:
        raise ValueError(f"start ({start.isoformat()}) must be before end ({end.isoformat()})")


def _is_utc(tz: object) -> bool:
    if tz is UTC:
        return True
    return str(tz).upper() in _UTC_NAMES


def _load_existing(path: Path) -> pd.DataFrame | None:
    """Read a Parquet file and return its DataFrame, or None if absent/unreadable."""
    if not path.exists():
        return None
    try:
        df: pd.DataFrame = pd.read_parquet(path)
        return df
    except Exception as exc:
        logger.warning("historical_download_existing_unreadable", path=str(path), error=str(exc))
        return None


def _resume_cursor(df: pd.DataFrame, timeframe: str) -> datetime:
    """Return the next fetch start: last persisted timestamp + one period."""
    last_ts_ms = int(df["timestamp"].max().timestamp() * 1000)
    period_ms = _timeframe_to_milliseconds(timeframe)
    return datetime.fromtimestamp((last_ts_ms + period_ms) / 1000, tz=UTC)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate on timestamp and sort ascending — makes output deterministic."""
    df = df.drop_duplicates(subset=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _merge_deduplicate(existing: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    """Merge two OHLCV DataFrames, deduplicate on timestamp, sort ascending."""
    if fetched.empty:
        return existing.copy()
    merged = pd.concat([existing, fetched], ignore_index=True)
    return _normalize(merged)
