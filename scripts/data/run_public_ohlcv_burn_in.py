"""Manual read-only OHLCV data capture burn-in for AQCS.

Collects public Binance Spot OHLCV candles for multiple symbols, validates
each dataset, generates and verifies a dataset manifest per symbol, and
produces a deterministic JSON burn-in summary.

This script is data-capture infrastructure only.
No API key is required. No orders are placed. No trading signals are produced.
No execution, portfolio, risk, or LLM systems are touched.

Exit codes:
  0  — all symbols passed
  1  — at least one symbol failed validation or manifest verification
  2  — invalid CLI arguments or configuration error

Supported symbols:   BTCUSDT  ETHUSDT  SOLUSDT
Supported timeframe: 1h
Supported exchange:  binance

Manual burn-in command:
  PYTHONPATH=src python scripts/data/run_public_ohlcv_burn_in.py \\
    --exchange binance \\
    --symbols BTCUSDT,ETHUSDT,SOLUSDT \\
    --timeframe 1h \\
    --limit 200 \\
    --output-dir data/burn_in/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import pandas as pd

from aqcs.data.manifest import (
    generate_manifest,
    save_manifest,
    verify_manifest,
)
from aqcs.data.ohlcv import save_parquet
from aqcs.data.validator import validate_ohlcv
from aqcs.monitoring.data_quality import check_ohlcv_parquet_quality

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
SUPPORTED_TIMEFRAMES: frozenset[str] = frozenset({"1h"})
SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"binance"})

_DEFAULT_LIMIT: int = 200
_MAX_LIMIT: int = 500

# Map Binance native symbols to ccxt format (used inside DataFrames).
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
    so the exchange returns the most recent candles.  Duplicate timestamp rows
    are dropped; timestamps are UTC-aware.  This function is intentionally
    top-level so tests can patch it.

    Returns an empty DataFrame if the exchange returns no data.
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
    """Build a public-only ccxt exchange instance (no API key required)."""
    import ccxt

    if exchange_name != "binance":
        raise ValueError(f"Exchange '{exchange_name}' is not supported")
    return ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})


# ── Per-symbol capture ────────────────────────────────────────────────────────


def run_symbol_capture(
    symbol_code: str,
    timeframe: str,
    limit: int,
    output_dir: Path,
    exchange_name: str = "binance",
    *,
    exchange: Any | None = None,
) -> dict[str, Any]:
    """Fetch, validate, persist, and manifest-certify one symbol.

    Args:
        symbol_code: Binance-native code (``"BTCUSDT"``).
        timeframe: Candle timeframe (``"1h"``).
        limit: Number of most-recent candles.  Capped at ``_MAX_LIMIT``.
        output_dir: Directory for Parquet and manifest JSON output.
        exchange_name: Exchange (``"binance"``).
        exchange: Pre-built ccxt Exchange for testing.  A public Binance Spot
                  instance is built automatically when omitted.

    Returns:
        Per-symbol result dict with ``"status"`` key (``"passed"``/``"failed"``).
    """
    ccxt_symbol = _SYMBOL_TO_CCXT[symbol_code]

    if exchange is None:
        exchange = _build_public_exchange(exchange_name)

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    df = _fetch_ohlcv(exchange, ccxt_symbol, timeframe, limit)

    if df.empty:
        return {
            "status": "failed",
            "symbol_code": symbol_code,
            "symbol": ccxt_symbol,
            "rows_fetched": 0,
            "parquet_path": None,
            "manifest_path": None,
            "error": "Exchange returned no data",
        }

    # ── 2. Structural validation ───────────────────────────────────────────────
    vresult = validate_ohlcv(df, ccxt_symbol, timeframe)
    validation_summary: dict[str, Any] = {
        "is_valid": vresult.is_valid,
        "errors": list(vresult.errors),
        "warnings": list(vresult.warnings),
    }

    if not vresult.is_valid:
        return {
            "status": "failed",
            "symbol_code": symbol_code,
            "symbol": ccxt_symbol,
            "rows_fetched": len(df),
            "parquet_path": None,
            "manifest_path": None,
            "validation": validation_summary,
        }

    # ── 3. Persist to Parquet ─────────────────────────────────────────────────
    output_dir = Path(output_dir)
    parquet_path = save_parquet(df, output_dir, ccxt_symbol, timeframe)

    # ── 4. Data quality check ─────────────────────────────────────────────────
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
            "status": "failed",
            "symbol_code": symbol_code,
            "symbol": ccxt_symbol,
            "rows_fetched": len(df),
            "parquet_path": str(parquet_path),
            "manifest_path": None,
            "validation": validation_summary,
            "data_quality": quality_summary,
            "error": f"Manifest generation failed: {exc}",
        }

    safe_sym = ccxt_symbol.replace("/", "_")
    manifest_path = output_dir / f"{safe_sym}_{timeframe}_manifest.json"
    save_manifest(manifest, manifest_path)

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

    all_passed = vresult.is_valid and quality_report.passed and manifest_verified

    return {
        "status": "passed" if all_passed else "failed",
        "symbol_code": symbol_code,
        "symbol": ccxt_symbol,
        "rows_fetched": len(df),
        "parquet_path": str(parquet_path),
        "manifest_path": str(manifest_path),
        "validation": validation_summary,
        "data_quality": quality_summary,
        "manifest": manifest_summary,
        "manifest_verified": manifest_verified,
    }


# ── Multi-symbol burn-in ──────────────────────────────────────────────────────


def run_burn_in(
    symbol_codes: list[str],
    timeframe: str,
    limit: int,
    output_dir: Path,
    exchange_name: str = "binance",
    *,
    exchange: Any | None = None,
) -> dict[str, Any]:
    """Run the full multi-symbol OHLCV burn-in.

    Captures each symbol independently.  A single symbol failure does not
    abort the remaining symbols — all are attempted regardless.

    Args:
        symbol_codes: List of Binance-native symbol codes (``["BTCUSDT", ...]``).
        timeframe: Candle timeframe (``"1h"``).
        limit: Number of most-recent candles per symbol.
        output_dir: Root output directory for all parquet and manifest files.
        exchange_name: Exchange (``"binance"``).
        exchange: Pre-built ccxt Exchange for testing.  A single instance is
                  shared across all symbols when provided.

    Returns:
        Burn-in summary dict with per-symbol results and ``"status"`` key.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if exchange is None:
        exchange = _build_public_exchange(exchange_name)

    per_symbol: dict[str, dict[str, Any]] = {}
    for code in symbol_codes:
        per_symbol[code] = run_symbol_capture(
            code,
            timeframe,
            limit,
            output_dir,
            exchange_name,
            exchange=exchange,
        )

    passed = [c for c, r in per_symbol.items() if r["status"] == "passed"]
    failed = [c for c, r in per_symbol.items() if r["status"] != "passed"]
    overall = "passed" if not failed else "failed"

    return {
        "burn_in": "public_ohlcv",
        "status": overall,
        "exchange": exchange_name,
        "timeframe": timeframe,
        "limit_per_symbol": limit,
        "symbols_requested": list(symbol_codes),
        "symbols_passed": passed,
        "symbols_failed": failed,
        "output_dir": str(output_dir),
        "results": per_symbol,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--symbols",
    required=True,
    help="Comma-separated Binance symbol codes (e.g. BTCUSDT,ETHUSDT,SOLUSDT).",
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
    help=f"Most-recent candles per symbol (max {_MAX_LIMIT}).",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory for Parquet and manifest output.",
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
    symbols: str,
    timeframe: str,
    limit: int,
    output_dir: Path,
    exchange_name: str,
) -> None:
    """Manual read-only OHLCV data capture burn-in.

    Fetches public Binance Spot candles for each symbol, validates data quality,
    generates and verifies a dataset manifest per symbol, and prints a
    deterministic JSON summary to stdout.

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

    # ── Validate limit ────────────────────────────────────────────────────────
    if limit <= 0:
        click.echo(f"ERROR: --limit must be positive, got {limit}", err=True)
        sys.exit(2)
    if limit > _MAX_LIMIT:
        click.echo(f"ERROR: --limit {limit} exceeds maximum of {_MAX_LIMIT}", err=True)
        sys.exit(2)

    # ── Parse and validate symbol list ────────────────────────────────────────
    symbol_codes = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_codes:
        click.echo("ERROR: --symbols must contain at least one symbol", err=True)
        sys.exit(2)

    unsupported = [s for s in symbol_codes if s not in SUPPORTED_SYMBOLS]
    if unsupported:
        click.echo(
            f"ERROR: Unsupported symbol(s): {unsupported}. "
            f"Supported: {sorted(SUPPORTED_SYMBOLS)}",
            err=True,
        )
        sys.exit(2)

    # ── Run burn-in ───────────────────────────────────────────────────────────
    try:
        result = run_burn_in(symbol_codes, timeframe, limit, output_dir, exchange_name)
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    click.echo(json.dumps(result, indent=2, sort_keys=True))

    if result.get("status") != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
