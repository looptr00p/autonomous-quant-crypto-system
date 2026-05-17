"""OHLCV downloader — fetches daily candlestick data from Binance Spot and persists as Parquet."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ccxt
import click
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aqcs.utils.config import get_settings, load_config
from aqcs.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────

OHLCV_SCHEMA = pa.schema(
    [
        pa.field("timestamp", pa.timestamp("ms", tz="UTC")),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("volume", pa.float64()),
        pa.field("symbol", pa.string()),
        pa.field("timeframe", pa.string()),
        pa.field("exchange", pa.string()),
    ]
)


# ── Exchange factory ──────────────────────────────────────────────────────────

def _build_exchange(sandbox: bool = True) -> ccxt.Exchange:
    """Build a read-only ccxt Binance Spot instance."""
    settings = get_settings()
    params: dict[str, Any] = {
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    }
    if settings.binance_api_key:
        params["apiKey"] = settings.binance_api_key
        params["secret"] = settings.binance_api_secret

    exchange = ccxt.binance(params)
    if sandbox:
        exchange.set_sandbox_mode(True)
    return exchange


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime,
    exchange: ccxt.Exchange | None = None,
    pagination_sleep_ms: int = 500,
    max_candles: int = 1000,
) -> pd.DataFrame:
    """Fetch OHLCV candles for a single symbol and return a typed DataFrame."""
    if exchange is None:
        exchange = _build_exchange(sandbox=False)

    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000)

    rows: list[list[Any]] = []
    cursor = since_ms

    while cursor < until_ms:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=max_candles)
        if not raw:
            break

        for candle in raw:
            ts_ms = candle[0]
            if ts_ms >= until_ms:
                break
            rows.append(candle)
            cursor = ts_ms

        if len(raw) < max_candles:
            break

        cursor += 1
        time.sleep(pagination_sleep_ms / 1000)

        logger.info(
            "ohlcv_page_fetched",
            symbol=symbol,
            candles=len(raw),
            cursor=cursor,
        )

    if not rows:
        logger.warning("no_data_returned", symbol=symbol, since=since.isoformat())
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="timestamp_ms")
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"])
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df["exchange"] = exchange.id
    df = df.sort_values("timestamp").reset_index(drop=True)

    logger.info("ohlcv_fetched", symbol=symbol, rows=len(df))
    return df


# ── Storage ───────────────────────────────────────────────────────────────────

def save_parquet(df: pd.DataFrame, output_dir: Path, symbol: str, timeframe: str) -> Path:
    """Write DataFrame to Parquet using tmp-then-rename to prevent partial writes."""
    safe_symbol = symbol.replace("/", "_")
    dest = output_dir / f"{safe_symbol}_{timeframe}.parquet"
    tmp = dest.with_suffix(".tmp.parquet")
    dest.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, schema=OHLCV_SCHEMA, preserve_index=False)
    pq.write_table(table, tmp, compression="snappy")
    tmp.rename(dest)

    logger.info("parquet_saved", path=str(dest), rows=len(df))
    return dest


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option("--symbol", "-s", default="BTC/USDT", show_default=True, help="Market symbol (e.g. BTC/USDT)")
@click.option("--timeframe", "-t", default="1d", show_default=True, help="Candle timeframe (1d, 4h, 1h …)")
@click.option("--start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]), help="Start date YYYY-MM-DD")
@click.option("--end", default=None, type=click.DateTime(formats=["%Y-%m-%d"]), help="End date YYYY-MM-DD (default: today)")
@click.option("--output-dir", default=None, help="Output directory (default: data/raw)")
@click.option("--log-level", default="INFO", show_default=True, type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
def main(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime | None,
    output_dir: str | None,
    log_level: str,
) -> None:
    """Download OHLCV candles from Binance Spot and save to Parquet."""
    configure_logging(level=log_level, fmt="json")
    cfg = load_config()

    since = start.replace(tzinfo=timezone.utc)
    until = (end or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
    out = Path(output_dir or cfg["data"]["raw_dir"])

    logger.info(
        "download_started",
        symbol=symbol,
        timeframe=timeframe,
        since=since.isoformat(),
        until=until.isoformat(),
        output_dir=str(out),
    )

    exchange = _build_exchange(sandbox=False)
    df = fetch_ohlcv(symbol, timeframe, since, until, exchange=exchange)

    if df.empty:
        logger.error("download_failed_empty_result", symbol=symbol)
        raise SystemExit(1)

    dest = save_parquet(df, out, symbol, timeframe)
    logger.info("download_complete", file=str(dest), rows=len(df))


if __name__ == "__main__":
    main()
