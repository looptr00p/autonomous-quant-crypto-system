"""CLI for deterministic historical OHLCV expansion.

Downloads multi-year 1h candle history from Binance Spot public data and
persists to local Parquet.  Existing files are extended (not overwritten):
the downloader resumes from the last persisted timestamp.

Usage:
    python scripts/data/download_historical_data.py \\
        --symbol BTC/USDT \\
        --timeframe 1h \\
        --start 2023-01-01 \\
        --end 2025-01-01 \\
        --output-dir data/raw
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import click

# Allow running as a script without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aqcs.data.historical_download import (  # noqa: E402
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    download_historical_ohlcv,
)
from aqcs.utils.logging import configure_logging, get_logger  # noqa: E402

logger = get_logger(__name__)


@click.command()
@click.option(
    "--symbol",
    "-s",
    required=True,
    type=click.Choice(sorted(SUPPORTED_SYMBOLS)),
    help="Market symbol (BTC/USDT, ETH/USDT, SOL/USDT)",
)
@click.option(
    "--timeframe",
    "-t",
    required=True,
    type=click.Choice(sorted(SUPPORTED_TIMEFRAMES)),
    help="Candle timeframe (1h)",
)
@click.option(
    "--start",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Start date YYYY-MM-DD (inclusive, UTC)",
)
@click.option(
    "--end",
    default=None,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="End date YYYY-MM-DD (exclusive, UTC; default: today)",
)
@click.option(
    "--output-dir",
    required=True,
    help="Output directory for Parquet files",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Log level",
)
def main(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime | None,
    output_dir: str,
    log_level: str,
) -> None:
    """Download historical OHLCV from Binance Spot and save to Parquet.

    Existing Parquet files are extended from the last persisted candle —
    running the same command twice is safe and idempotent.
    """
    configure_logging(level=log_level, fmt="json")

    since = start.replace(tzinfo=UTC)
    until = (end or datetime.now(UTC)).replace(tzinfo=UTC)
    out = Path(output_dir)

    logger.info(
        "cli_historical_download_started",
        symbol=symbol,
        timeframe=timeframe,
        since=since.isoformat(),
        until=until.isoformat(),
        output_dir=str(out),
    )

    try:
        result = download_historical_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            start=since,
            end=until,
            output_dir=out,
        )
    except (ValueError, RuntimeError) as exc:
        logger.error("cli_historical_download_failed", symbol=symbol, error=str(exc))
        raise SystemExit(1) from exc

    logger.info(
        "cli_historical_download_complete",
        symbol=symbol,
        timeframe=timeframe,
        rows_fetched=result.rows_fetched,
        rows_total=result.rows_total,
        parquet_path=str(result.parquet_path),
        start_timestamp=result.start_timestamp.isoformat(),
        end_timestamp=result.end_timestamp.isoformat(),
        resumed_from=result.resumed_from.isoformat() if result.resumed_from else None,
    )


if __name__ == "__main__":
    main()
