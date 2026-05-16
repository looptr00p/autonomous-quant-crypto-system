"""Tests for the OHLCV downloader — uses mocked exchange, no network calls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.ohlcv import fetch_ohlcv, save_parquet


def _make_candles(n: int = 5) -> list[list]:
    """Generate synthetic OHLCV rows (timestamp_ms, O, H, L, C, V)."""
    base_ms = 1_700_000_000_000
    day_ms = 86_400_000
    rows = []
    for i in range(n):
        ts = base_ms + i * day_ms
        rows.append([ts, 30000.0 + i, 31000.0 + i, 29000.0 + i, 30500.0 + i, 1000.0 + i])
    return rows


class TestFetchOHLCV:
    def _mock_exchange(self, candles: list[list]) -> MagicMock:
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        return ex

    def test_returns_dataframe(self) -> None:
        candles = _make_candles(3)
        ex = self._mock_exchange(candles)
        since = datetime(2023, 11, 14, tzinfo=timezone.utc)
        until = datetime(2023, 11, 17, tzinfo=timezone.utc)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "timestamp" in df.columns
        assert "symbol" in df.columns

    def test_symbol_and_exchange_columns(self) -> None:
        candles = _make_candles(2)
        ex = self._mock_exchange(candles)
        since = datetime(2023, 11, 14, tzinfo=timezone.utc)
        until = datetime(2023, 11, 17, tzinfo=timezone.utc)

        df = fetch_ohlcv("ETH/USDT", "1d", since, until, exchange=ex)

        assert df["symbol"].unique()[0] == "ETH/USDT"
        assert df["exchange"].unique()[0] == "binance"

    def test_empty_response_returns_empty_df(self) -> None:
        ex = self._mock_exchange([])
        since = datetime(2023, 11, 14, tzinfo=timezone.utc)
        until = datetime(2023, 11, 17, tzinfo=timezone.utc)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)

        assert df.empty

    def test_no_duplicates(self) -> None:
        candles = _make_candles(3)
        # Inject duplicate
        candles_with_dup = candles + [candles[0]]
        ex = self._mock_exchange(candles_with_dup)
        since = datetime(2023, 11, 14, tzinfo=timezone.utc)
        until = datetime(2023, 11, 18, tzinfo=timezone.utc)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)

        assert df["timestamp"].duplicated().sum() == 0


class TestSaveParquet:
    def test_creates_file(self, tmp_path: Path) -> None:
        candles = _make_candles(5)
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        since = datetime(2023, 11, 14, tzinfo=timezone.utc)
        until = datetime(2023, 11, 20, tzinfo=timezone.utc)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)
        dest = save_parquet(df, tmp_path, "BTC/USDT", "1d")

        assert dest.exists()
        assert dest.suffix == ".parquet"

    def test_parquet_readable(self, tmp_path: Path) -> None:
        candles = _make_candles(5)
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        since = datetime(2023, 11, 14, tzinfo=timezone.utc)
        until = datetime(2023, 11, 20, tzinfo=timezone.utc)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)
        dest = save_parquet(df, tmp_path, "BTC/USDT", "1d")

        loaded = pd.read_parquet(dest)
        assert len(loaded) == len(df)
        assert set(loaded.columns) == set(df.columns)
