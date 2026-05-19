"""Read-only Binance Spot OHLCV public API smoke test.

Fetches a small OHLCV sample from the Binance Spot public endpoint (no API
key required), persists it as local Parquet, validates data quality, generates
a dataset manifest, and verifies the manifest.  Prints a deterministic JSON
summary to stdout.

This script is a data-capture infrastructure check only.
It never places orders, reads private credentials, or connects to execution
or portfolio systems.

Exit codes:
  0  — all steps passed
  1  — data validation or manifest verification failed
  2  — invalid CLI arguments or configuration error

Supported symbols:   BTCUSDT  ETHUSDT  SOLUSDT
Supported timeframe: 1h
Supported exchange:  binance

Manual smoke command (run after PR review):
  PYTHONPATH=src python scripts/data/smoke_test_public_ohlcv.py \\
    --exchange binance --symbol BTCUSDT --timeframe 1h \\
    --limit 48 --output-dir data/smoke/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import pandas as pd

from aqcs.data.manifest import generate_manifest, verify_manifest
from aqcs.data.ohlcv import save_parquet
from aqcs.data.validator import validate_ohlcv
from aqcs.monitoring.data_quality import check_ohlcv_parquet_quality

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset({"1h"})
SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"binance"})

_DEFAULT_LIMIT: int = 48
_MAX_LIMIT: int = 200

# Map Binance native symbols to ccxt format (used inside the DataFrame).
_SYMBOL_TO_CCXT: dict[str, str] = {
    "BTCUSDT": "BTC/USDT",
    "ETHUSDT": "ETH/USDT",
    "SOLUSDT": "SOL/USDT",
}


# ── Fetch helper ──────────────────────────────────────────────────────────────


def _fetch_ohlcv(
    exchange: Any,
    ccxt_symbol: str,
    timeframe: str,
    limit: int,
) -> pd.DataFrame:
    """Fetch the most recent ``limit`` candles via the public API.

    Uses ccxt's single-request ``fetch_ohlcv`` with only ``limit`` specified
    (no ``since``) so the exchange returns the most recent candles.  Duplicate
    timestamp_ms rows are dropped before returning; timestamps are converted to
    UTC-aware datetime64.

    This function is intentionally separate from the CLI so that tests can
    patch it directly.

    Args:
        exchange: ccxt Exchange instance (public Binance Spot, no keys).
        ccxt_symbol: Symbol in ccxt format (e.g. ``"BTC/USDT"``).
        timeframe: Candle timeframe string (e.g. ``"1h"``).
        limit: Number of candles to fetch (≤ ``_MAX_LIMIT``).

    Returns:
        DataFrame with OHLCV schema columns and UTC-aware timestamps.
        Empty DataFrame if the exchange returns no data.
    """
    raw = exchange.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, limit=limit)
    if not raw:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "symbol",
                "timeframe",
                "exchange",
            ]
        )

    df = pd.DataFrame(raw, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="timestamp_ms")
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"])
    df["symbol"] = ccxt_symbol
    df["timeframe"] = timeframe
    df["exchange"] = exchange.id
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _build_public_exchange(exchange_name: str) -> Any:
    """Build a public-only ccxt exchange instance (no API key required).

    Uses only the public OHLCV endpoint.  No private credentials are
    read, stored, or transmitted.
    """
    import ccxt  # already a declared dependency

    if exchange_name != "binance":
        raise ValueError(f"Exchange '{exchange_name}' is not supported")
    return ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )


# ── Core smoke test ───────────────────────────────────────────────────────────


def run_smoke_test(
    symbol_code: str,
    timeframe: str,
    limit: int,
    output_dir: Path,
    exchange_name: str = "binance",
    *,
    exchange: Any | None = None,
) -> dict[str, Any]:
    """Run the full read-only OHLCV smoke test pipeline.

    Args:
        symbol_code: Binance-native symbol code (e.g. ``"BTCUSDT"``).
                     Must be in ``SUPPORTED_SYMBOLS``.
        timeframe: Candle timeframe (must be in ``SUPPORTED_TIMEFRAMES``).
        limit: Number of most-recent candles to fetch.  Capped at
               ``_MAX_LIMIT``.
        output_dir: Directory where the Parquet file is written.
        exchange_name: Exchange name (must be in ``SUPPORTED_EXCHANGES``).
        exchange: Pre-built ccxt Exchange for dependency injection (tests).
                  A public Binance Spot instance is built automatically when
                  omitted.

    Returns:
        Dict with all step results and ``"status"`` key
        (``"passed"`` or ``"failed"``).
    """
    ccxt_symbol = _SYMBOL_TO_CCXT[symbol_code]

    if exchange is None:
        exchange = _build_public_exchange(exchange_name)

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    df = _fetch_ohlcv(exchange, ccxt_symbol, timeframe, limit)

    if df.empty:
        return {
            "smoke_test": "public_ohlcv",
            "status": "failed",
            "exchange": exchange_name,
            "symbol": ccxt_symbol,
            "timeframe": timeframe,
            "limit_requested": limit,
            "rows_fetched": 0,
            "parquet_path": None,
            "error": "Exchange returned no data",
        }

    # ── 2. OHLCV validation ───────────────────────────────────────────────────
    vresult = validate_ohlcv(df, ccxt_symbol, timeframe)
    validation_summary: dict[str, Any] = {
        "is_valid": vresult.is_valid,
        "errors": list(vresult.errors),
        "warnings": list(vresult.warnings),
    }

    if not vresult.is_valid:
        return {
            "smoke_test": "public_ohlcv",
            "status": "failed",
            "exchange": exchange_name,
            "symbol": ccxt_symbol,
            "timeframe": timeframe,
            "limit_requested": limit,
            "rows_fetched": len(df),
            "parquet_path": None,
            "validation": validation_summary,
        }

    # ── 3. Persist to Parquet ─────────────────────────────────────────────────
    output_dir = Path(output_dir)
    parquet_path = save_parquet(df, output_dir, ccxt_symbol, timeframe)

    # ── 4. Data quality check (on saved parquet) ──────────────────────────────
    quality_report = check_ohlcv_parquet_quality(parquet_path, timeframe)
    quality_summary: dict[str, Any] = {
        "passed": quality_report.passed,
        "duplicate_count": quality_report.duplicate_timestamp_count,
        "missing_interval_count": quality_report.missing_interval_count,
        "nan_count_by_column": dict(quality_report.nan_count_by_column),
        "errors": list(quality_report.errors),
        "warnings": list(quality_report.warnings),
    }

    # ── 5. Dataset manifest ───────────────────────────────────────────────────
    try:
        manifest = generate_manifest(parquet_path, ccxt_symbol, timeframe)
    except ValueError as exc:
        return {
            "smoke_test": "public_ohlcv",
            "status": "failed",
            "exchange": exchange_name,
            "symbol": ccxt_symbol,
            "timeframe": timeframe,
            "limit_requested": limit,
            "rows_fetched": len(df),
            "parquet_path": str(parquet_path),
            "validation": validation_summary,
            "data_quality": quality_summary,
            "error": f"Manifest generation failed: {exc}",
        }

    manifest_summary: dict[str, Any] = {
        "content_hash": manifest.content_hash,
        "schema_hash": manifest.schema_hash,
        "row_count": manifest.row_count,
        "start_timestamp_utc": manifest.start_timestamp_utc,
        "end_timestamp_utc": manifest.end_timestamp_utc,
        "missing_interval_summary": dict(manifest.missing_interval_summary),
    }

    # ── 6. Manifest verification ──────────────────────────────────────────────
    verification = verify_manifest(parquet_path, manifest)
    manifest_verified = verification.verified

    # ── 7. Build summary ──────────────────────────────────────────────────────
    all_passed = vresult.is_valid and quality_report.passed and manifest_verified

    return {
        "smoke_test": "public_ohlcv",
        "status": "passed" if all_passed else "failed",
        "exchange": exchange_name,
        "symbol": ccxt_symbol,
        "timeframe": timeframe,
        "limit_requested": limit,
        "rows_fetched": len(df),
        "parquet_path": str(parquet_path),
        "validation": validation_summary,
        "data_quality": quality_summary,
        "manifest": manifest_summary,
        "manifest_verified": manifest_verified,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--symbol",
    required=True,
    type=click.Choice(sorted(SUPPORTED_SYMBOLS)),
    help="Binance symbol code (BTCUSDT, ETHUSDT, SOLUSDT).",
)
@click.option(
    "--timeframe",
    required=True,
    type=click.Choice(sorted(SUPPORTED_TIMEFRAMES)),
    help="Candle timeframe. Currently only 1h is supported.",
)
@click.option(
    "--limit",
    default=_DEFAULT_LIMIT,
    show_default=True,
    type=int,
    help=f"Number of most-recent candles to fetch (max {_MAX_LIMIT}).",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory for Parquet output.",
)
@click.option(
    "--exchange",
    "exchange_name",
    default="binance",
    show_default=True,
    type=click.Choice(sorted(SUPPORTED_EXCHANGES)),
    help="Exchange (only binance is currently supported).",
)
def main(
    symbol: str,
    timeframe: str,
    limit: int,
    output_dir: Path,
    exchange_name: str,
) -> None:
    """Read-only Binance Spot OHLCV public API smoke test.

    Fetches recent candles, validates data quality, generates and verifies
    a dataset manifest, and prints a deterministic JSON summary to stdout.

    No API key is required. No orders are placed.
    """
    # Redirect all log output to stderr so stdout carries only the JSON summary.
    import logging

    import structlog

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.WARNING, force=True)
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )

    if limit <= 0:
        click.echo(f"ERROR: --limit must be positive, got {limit}", err=True)
        sys.exit(2)
    if limit > _MAX_LIMIT:
        click.echo(f"ERROR: --limit {limit} exceeds maximum of {_MAX_LIMIT}", err=True)
        sys.exit(2)

    try:
        result = run_smoke_test(
            symbol,
            timeframe,
            limit,
            output_dir,
            exchange_name,
        )
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    click.echo(json.dumps(result, indent=2, sort_keys=True))

    if result.get("status") != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
