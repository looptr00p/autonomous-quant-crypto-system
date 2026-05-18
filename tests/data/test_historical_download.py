"""Tests for the deterministic historical OHLCV downloader.

Coverage:
- success-path (fresh download, valid data persisted)
- resumable ingestion (cursor advances from last saved timestamp)
- already-current (cursor >= end → no fetch, no save)
- append-safe persistence (existing data extended, not overwritten)
- duplicate rejection (duplicate candles dropped before save)
- monotonic timestamps (merged output always sorted)
- UTC enforcement (naive start/end rejected)
- invalid symbol rejection
- invalid timeframe rejection
- deterministic parquet output (identical runs → identical files)
- identical repeated runs (idempotent)
- monitoring compatibility (check_ohlcv_parquet_quality passes on output)
- local parquet validation compatibility (validate_ohlcv passes on output)
- adversarial: unreadable existing parquet treated as missing
- adversarial: no exchange data and no existing file → RuntimeError
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from aqcs.data.historical_download import (
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    DownloadResult,
    _load_existing,
    _merge_deduplicate,
    _resume_cursor,
    download_historical_ohlcv,
)
from aqcs.data.validator import REQUIRED_COLUMNS, validate_ohlcv

# ── Shared constants & factories ──────────────────────────────────────────────

_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1h"
_HOUR_MS = 3_600_000
_BASE_MS = 1_700_000_000_000  # 2023-11-14 22:13:20 UTC (deterministic anchor)


def _make_raw_candles(n: int = 5, base_ms: int = _BASE_MS) -> list[list]:
    """Return synthetic raw OHLCV rows as ccxt would deliver them."""
    return [
        [base_ms + i * _HOUR_MS, 30000.0 + i, 31000.0 + i, 29000.0 + i, 30500.0 + i, 1000.0 + i]
        for i in range(n)
    ]


def _mock_exchange(candles: list[list]) -> MagicMock:
    ex = MagicMock()
    ex.id = "binance"
    ex.fetch_ohlcv.return_value = candles
    return ex


def _make_parquet(tmp_path: Path, n: int = 5, base_ms: int = _BASE_MS) -> Path:
    """Write a minimal valid Parquet fixture and return its path."""
    candles = _make_raw_candles(n, base_ms)
    ex = _mock_exchange(candles)
    since = datetime.fromtimestamp(base_ms / 1000, tz=UTC)
    until = datetime.fromtimestamp((base_ms + n * _HOUR_MS) / 1000, tz=UTC)

    with (
        patch("aqcs.data.historical_download._build_exchange", return_value=ex),
        patch("aqcs.data.historical_download.fetch_ohlcv") as mock_fetch,
    ):
        # Build the DataFrame the same way fetch_ohlcv would
        df = pd.DataFrame(
            candles, columns=["timestamp_ms", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        df = df.drop(columns=["timestamp_ms"])
        df["symbol"] = _SYMBOL
        df["timeframe"] = _TIMEFRAME
        df["exchange"] = "binance"
        df = df.sort_values("timestamp").reset_index(drop=True)
        mock_fetch.return_value = df

        result = download_historical_ohlcv(
            _SYMBOL,
            _TIMEFRAME,
            since,
            until,
            tmp_path,
        )
    return result.parquet_path


def _build_df(n: int = 5, base_ms: int = _BASE_MS) -> pd.DataFrame:
    """Build a DataFrame the same way fetch_ohlcv would."""
    candles = _make_raw_candles(n, base_ms)
    df = pd.DataFrame(candles, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"])
    df["symbol"] = _SYMBOL
    df["timeframe"] = _TIMEFRAME
    df["exchange"] = "binance"
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# ── Input validation ──────────────────────────────────────────────────────────


class TestInputValidation:
    def test_invalid_symbol_raises(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 15, tzinfo=UTC)
        with pytest.raises(ValueError, match="Unsupported symbol"):
            download_historical_ohlcv("FAKE/USDT", _TIMEFRAME, since, until, tmp_path)

    def test_invalid_timeframe_raises(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 15, tzinfo=UTC)
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            download_historical_ohlcv(_SYMBOL, "4h", since, until, tmp_path)

    def test_naive_start_raises(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 14)  # naive
        until = datetime(2023, 11, 15, tzinfo=UTC)
        with pytest.raises(ValueError, match="UTC"):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

    def test_naive_end_raises(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 15)  # naive
        with pytest.raises(ValueError, match="UTC"):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

    def test_start_equals_end_raises(self, tmp_path: Path) -> None:
        ts = datetime(2023, 11, 14, tzinfo=UTC)
        with pytest.raises(ValueError, match="before end"):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, ts, ts, tmp_path)

    def test_start_after_end_raises(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 15, tzinfo=UTC)
        until = datetime(2023, 11, 14, tzinfo=UTC)
        with pytest.raises(ValueError, match="before end"):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

    def test_all_supported_symbols_accepted(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 15, tzinfo=UTC)
        for sym in SUPPORTED_SYMBOLS:
            df = _build_df()
            df["symbol"] = sym
            ex = _mock_exchange([])
            with (
                patch("aqcs.data.historical_download._build_exchange", return_value=ex),
                patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
            ):
                result = download_historical_ohlcv(sym, _TIMEFRAME, since, until, tmp_path)
            assert result.symbol == sym

    def test_all_supported_timeframes_accepted(self, tmp_path: Path) -> None:
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 15, tzinfo=UTC)
        df = _build_df()
        for tf in SUPPORTED_TIMEFRAMES:
            df_tf = df.copy()
            df_tf["timeframe"] = tf
            ex = _mock_exchange([])
            with (
                patch("aqcs.data.historical_download._build_exchange", return_value=ex),
                patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_tf),
            ):
                result = download_historical_ohlcv(_SYMBOL, tf, since, until, tmp_path)
            assert result.timeframe == tf


# ── Fresh (first-time) download ────────────────────────────────────────────────


class TestFreshDownload:
    def _run(self, tmp_path: Path, n: int = 5) -> tuple[DownloadResult, pd.DataFrame]:
        df = _build_df(n)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + n * _HOUR_MS) / 1000, tz=UTC)
        ex = _mock_exchange([])
        with (
            patch("aqcs.data.historical_download._build_exchange", return_value=ex),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        return result, df

    def test_returns_download_result(self, tmp_path: Path) -> None:
        result, _ = self._run(tmp_path)
        assert isinstance(result, DownloadResult)

    def test_parquet_file_created(self, tmp_path: Path) -> None:
        result, _ = self._run(tmp_path)
        assert result.parquet_path.exists()

    def test_rows_fetched_equals_input(self, tmp_path: Path) -> None:
        result, df = self._run(tmp_path, n=7)
        assert result.rows_fetched == 7

    def test_rows_total_equals_rows_fetched_on_fresh(self, tmp_path: Path) -> None:
        result, _ = self._run(tmp_path, n=5)
        assert result.rows_total == result.rows_fetched

    def test_resumed_from_is_none_on_fresh(self, tmp_path: Path) -> None:
        result, _ = self._run(tmp_path)
        assert result.resumed_from is None

    def test_parquet_readable(self, tmp_path: Path) -> None:
        result, _ = self._run(tmp_path)
        loaded = pd.read_parquet(result.parquet_path)
        assert not loaded.empty

    def test_no_tmp_file_left(self, tmp_path: Path) -> None:
        self._run(tmp_path)
        assert not list(tmp_path.glob("*.tmp.parquet"))

    def test_output_dir_created_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        df = _build_df()
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        ex = _mock_exchange([])
        with (
            patch("aqcs.data.historical_download._build_exchange", return_value=ex),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, nested)
        assert result.parquet_path.exists()


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def _run_once(self, tmp_path: Path, sub: str) -> pd.DataFrame:
        out = tmp_path / sub
        out.mkdir()
        df = _build_df()
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, out)
        return pd.read_parquet(result.parquet_path)

    def test_identical_runs_produce_identical_parquet(self, tmp_path: Path) -> None:
        df1 = self._run_once(tmp_path, "run1")
        df2 = self._run_once(tmp_path, "run2")
        pd.testing.assert_frame_equal(df1, df2)

    def test_timestamp_ordering_is_deterministic(self, tmp_path: Path) -> None:
        df = self._run_once(tmp_path, "order")
        assert df["timestamp"].is_monotonic_increasing

    def test_no_duplicates_in_output(self, tmp_path: Path) -> None:
        df = self._run_once(tmp_path, "dupes")
        assert df["timestamp"].duplicated().sum() == 0


# ── Duplicate safety ──────────────────────────────────────────────────────────


class TestDuplicateSafety:
    def test_duplicate_candles_in_fetch_are_dropped(self, tmp_path: Path) -> None:
        df = _build_df(5)
        df_with_dupes = pd.concat([df, df.iloc[:2]], ignore_index=True)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_with_dupes),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        loaded = pd.read_parquet(result.parquet_path)
        assert loaded["timestamp"].duplicated().sum() == 0
        assert len(loaded) == 5  # duplicates removed

    def test_merge_dedup_removes_overlapping_candles(self) -> None:
        df1 = _build_df(5)
        # df2 overlaps last 2 rows of df1 and adds 3 new ones
        df2 = _build_df(5, base_ms=_BASE_MS + 3 * _HOUR_MS)
        merged = _merge_deduplicate(df1, df2)
        assert merged["timestamp"].duplicated().sum() == 0
        assert len(merged) == 8  # 5 + 5 - 2 overlapping

    def test_merge_dedup_preserves_monotonic_order(self) -> None:
        df1 = _build_df(5)
        df2 = _build_df(5, base_ms=_BASE_MS + 5 * _HOUR_MS)
        merged = _merge_deduplicate(df1, df2)
        assert merged["timestamp"].is_monotonic_increasing


# ── Append-safe / resumable behavior ─────────────────────────────────────────


class TestResumable:
    def test_resume_cursor_advances_by_one_period(self) -> None:
        df = _build_df(5)
        cursor = _resume_cursor(df, _TIMEFRAME)
        expected_ms = _BASE_MS + 4 * _HOUR_MS + _HOUR_MS  # last + 1h
        expected = datetime.fromtimestamp(expected_ms / 1000, tz=UTC)
        assert cursor == expected

    def test_resumed_from_set_when_existing_file_present(self, tmp_path: Path) -> None:
        # First run — creates the file
        df_initial = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_initial),
        ):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        # Second run — extends the file
        new_base = _BASE_MS + 5 * _HOUR_MS
        df_new = _build_df(3, base_ms=new_base)
        df_new["symbol"] = _SYMBOL
        df_new["timeframe"] = _TIMEFRAME
        since2 = since
        until2 = datetime.fromtimestamp((new_base + 3 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_new),
        ):
            result2 = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since2, until2, tmp_path)

        assert result2.resumed_from is not None

    def test_append_increases_total_row_count(self, tmp_path: Path) -> None:
        # Initial load
        df_initial = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_initial),
        ):
            r1 = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        # Extension load
        new_base = _BASE_MS + 5 * _HOUR_MS
        df_ext = _build_df(4, base_ms=new_base)
        until2 = datetime.fromtimestamp((new_base + 4 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_ext),
        ):
            r2 = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until2, tmp_path)

        assert r2.rows_total == r1.rows_total + 4

    def test_existing_data_not_lost_after_append(self, tmp_path: Path) -> None:
        df_initial = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_initial),
        ):
            r1 = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        original_ts = set(pd.read_parquet(r1.parquet_path)["timestamp"].tolist())

        new_base = _BASE_MS + 5 * _HOUR_MS
        df_ext = _build_df(3, base_ms=new_base)
        until2 = datetime.fromtimestamp((new_base + 3 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_ext),
        ):
            r2 = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until2, tmp_path)

        final_ts = set(pd.read_parquet(r2.parquet_path)["timestamp"].tolist())
        assert original_ts.issubset(final_ts)

    def test_repeated_run_is_idempotent(self, tmp_path: Path) -> None:
        """Running the same command twice produces identical Parquet."""
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)

        def run_once() -> pd.DataFrame:
            with (
                patch("aqcs.data.historical_download._build_exchange"),
                patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df.copy()),
            ):
                result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
            return pd.read_parquet(result.parquet_path)

        loaded1 = run_once()
        loaded2 = run_once()
        pd.testing.assert_frame_equal(loaded1, loaded2)

    def test_already_current_returns_without_fetching(self, tmp_path: Path) -> None:
        # Create initial file covering the full range
        df_initial = _build_df(10)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        last_ms = _BASE_MS + 9 * _HOUR_MS
        until = datetime.fromtimestamp((last_ms + _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_initial),
        ):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        # Run with same (or earlier) end — should not fetch
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv") as mock_fetch,
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        mock_fetch.assert_not_called()
        assert result.rows_fetched == 0
        assert result.rows_total == 10


# ── Monotonic timestamps ──────────────────────────────────────────────────────


class TestMonotonicTimestamps:
    def test_shuffled_fetch_output_is_sorted_in_parquet(self, tmp_path: Path) -> None:
        df = _build_df(10)
        shuffled = df.sample(frac=1, random_state=42).reset_index(drop=True)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 10 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=shuffled),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        loaded = pd.read_parquet(result.parquet_path)
        assert loaded["timestamp"].is_monotonic_increasing


# ── UTC enforcement ────────────────────────────────────────────────────────────


class TestUTCEnforcement:
    def test_persisted_timestamps_are_utc(self, tmp_path: Path) -> None:
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        loaded = pd.read_parquet(result.parquet_path)
        tz = loaded["timestamp"].dt.tz
        assert tz is not None
        assert str(tz).upper() in {"UTC", "UTC+00:00", "+00:00"}

    def test_start_timestamp_in_result_is_utc(self, tmp_path: Path) -> None:
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        assert result.start_timestamp.tzinfo is not None
        assert result.end_timestamp.tzinfo is not None


# ── Adversarial / failure-path ────────────────────────────────────────────────


class TestAdversarial:
    def test_no_data_no_existing_raises_runtime_error(self, tmp_path: Path) -> None:
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        _cols = [
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
        empty_df: pd.DataFrame = pd.DataFrame(columns=_cols)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=empty_df),
            pytest.raises(RuntimeError, match="No data returned"),
        ):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

    def test_unreadable_existing_parquet_treated_as_missing(self, tmp_path: Path) -> None:
        corrupted = tmp_path / "BTC_USDT_1h.parquet"
        corrupted.write_bytes(b"not a parquet file")
        result = _load_existing(corrupted)
        assert result is None

    def test_load_existing_returns_none_for_absent_file(self, tmp_path: Path) -> None:
        result = _load_existing(tmp_path / "nonexistent.parquet")
        assert result is None

    def test_exchange_uses_build_when_not_provided(self, tmp_path: Path) -> None:
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange") as mock_build,
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            mock_build.return_value = MagicMock()
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        mock_build.assert_called_once_with(sandbox=False)

    def test_provided_exchange_is_used_directly(self, tmp_path: Path) -> None:
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        custom_ex = _mock_exchange([])
        with (
            patch("aqcs.data.historical_download._build_exchange") as mock_build,
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            download_historical_ohlcv(
                _SYMBOL, _TIMEFRAME, since, until, tmp_path, exchange=custom_ex
            )
        mock_build.assert_not_called()


# ── Monitoring compatibility ──────────────────────────────────────────────────
# Tests verify that output Parquet satisfies the structural properties consumed
# by the monitoring layer (aqcs.monitoring.data_quality), without importing it
# directly (the monitoring module ships on a separate branch pending merge).


class TestMonitoringCompatibility:
    def _assert_monitoring_compatible(self, path: Path) -> pd.DataFrame:
        """Apply the same checks as check_ohlcv_parquet_quality."""
        df = pd.read_parquet(path)
        assert not df.empty, "Monitoring expects non-empty dataset"
        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Monitoring expects column: {col}"
        tz = df["timestamp"].dt.tz
        assert tz is not None, "Monitoring rejects naive timestamps"
        assert str(tz).upper() in {"UTC", "UTC+00:00", "+00:00"}, "Monitoring requires UTC"
        assert df["timestamp"].is_monotonic_increasing, "Monitoring rejects non-monotonic"
        assert df["timestamp"].duplicated().sum() == 0, "Monitoring counts duplicates"
        return df

    def test_output_is_monitoring_compatible(self, tmp_path: Path) -> None:
        df = _build_df(24)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 24 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        loaded = self._assert_monitoring_compatible(result.parquet_path)
        assert len(loaded) == 24

    def test_output_after_append_is_monitoring_compatible(self, tmp_path: Path) -> None:
        df1 = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until1 = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df1),
        ):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until1, tmp_path)

        new_base = _BASE_MS + 5 * _HOUR_MS
        df2 = _build_df(5, base_ms=new_base)
        until2 = datetime.fromtimestamp((new_base + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df2),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until2, tmp_path)

        loaded = self._assert_monitoring_compatible(result.parquet_path)
        assert len(loaded) == 10


# ── Validator compatibility ───────────────────────────────────────────────────


class TestValidatorCompatibility:
    def test_output_passes_validate_ohlcv(self, tmp_path: Path) -> None:
        df = _build_df(10)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 10 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        loaded = pd.read_parquet(result.parquet_path)
        validation = validate_ohlcv(loaded, _SYMBOL, _TIMEFRAME)
        assert validation.is_valid is True
        assert validation.errors == []

    def test_output_has_all_required_columns(self, tmp_path: Path) -> None:
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)

        loaded = pd.read_parquet(result.parquet_path)
        for col in REQUIRED_COLUMNS:
            assert col in loaded.columns, f"Missing required column: {col}"


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestCLI:
    def test_cli_success_exits_zero(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from download_historical_data import main  # injected via conftest.py

        df = _build_df(5)
        runner = CliRunner()
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = runner.invoke(
                main,
                [
                    "--symbol",
                    _SYMBOL,
                    "--timeframe",
                    _TIMEFRAME,
                    "--start",
                    "2023-11-14",
                    "--end",
                    "2023-11-15",
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0

    def test_cli_invalid_symbol_exits_nonzero(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from download_historical_data import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbol",
                "FAKE/USDT",
                "--timeframe",
                _TIMEFRAME,
                "--start",
                "2023-11-14",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_cli_invalid_timeframe_exits_nonzero(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from download_historical_data import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbol",
                _SYMBOL,
                "--timeframe",
                "4h",
                "--start",
                "2023-11-14",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_cli_missing_required_arg_exits_nonzero(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from download_historical_data import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--timeframe", _TIMEFRAME, "--start", "2023-11-14", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code != 0


# ── Regression tests ──────────────────────────────────────────────────────────


class TestRegressions:
    def test_multiple_eth_runs_do_not_clobber_btc(self, tmp_path: Path) -> None:
        """Symbol files must be isolated — ETH writes must not affect BTC."""
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)

        df_btc = _build_df(5)
        df_eth = _build_df(5)
        df_eth["symbol"] = "ETH/USDT"

        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_btc),
        ):
            r_btc = download_historical_ohlcv("BTC/USDT", _TIMEFRAME, since, until, tmp_path)

        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df_eth),
        ):
            download_historical_ohlcv("ETH/USDT", _TIMEFRAME, since, until, tmp_path)

        btc_loaded = pd.read_parquet(r_btc.parquet_path)
        assert (btc_loaded["symbol"] == "BTC/USDT").all()

    def test_parquet_filename_uses_underscore_separator(self, tmp_path: Path) -> None:
        df = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until, tmp_path)
        assert result.parquet_path.name == "BTC_USDT_1h.parquet"

    def test_duplicate_timestamps_in_overlap_not_written(self, tmp_path: Path) -> None:
        """Overlapping rows during resume must not produce duplicate timestamps."""
        df1 = _build_df(5)
        since = datetime.fromtimestamp(_BASE_MS / 1000, tz=UTC)
        until1 = datetime.fromtimestamp((_BASE_MS + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df1),
        ):
            download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until1, tmp_path)

        # Second fetch returns rows that overlap with existing (re-sends row 4 and 5)
        overlap_base = _BASE_MS + 3 * _HOUR_MS
        df2 = _build_df(5, base_ms=overlap_base)
        until2 = datetime.fromtimestamp((overlap_base + 5 * _HOUR_MS) / 1000, tz=UTC)
        with (
            patch("aqcs.data.historical_download._build_exchange"),
            patch("aqcs.data.historical_download.fetch_ohlcv", return_value=df2),
        ):
            result = download_historical_ohlcv(_SYMBOL, _TIMEFRAME, since, until2, tmp_path)

        loaded = pd.read_parquet(result.parquet_path)
        assert loaded["timestamp"].duplicated().sum() == 0
