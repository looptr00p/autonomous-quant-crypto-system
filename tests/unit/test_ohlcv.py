"""Tests for the OHLCV downloader — uses mocked exchange, no network calls."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pyarrow.parquet as pq
from click.testing import CliRunner

from aqcs.data.ohlcv import OHLCV_SCHEMA, _build_exchange, fetch_ohlcv, main, save_parquet
from aqcs.data.validator import ValidationResult


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
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 17, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "timestamp" in df.columns
        assert "symbol" in df.columns

    def test_symbol_and_exchange_columns(self) -> None:
        candles = _make_candles(2)
        ex = self._mock_exchange(candles)
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 17, tzinfo=UTC)

        df = fetch_ohlcv("ETH/USDT", "1d", since, until, exchange=ex)

        assert df["symbol"].unique()[0] == "ETH/USDT"
        assert df["exchange"].unique()[0] == "binance"

    def test_empty_response_returns_empty_df(self) -> None:
        ex = self._mock_exchange([])
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 17, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)

        assert df.empty

    def test_no_duplicates(self) -> None:
        candles = _make_candles(3)
        candles_with_dup = candles + [candles[0]]
        ex = self._mock_exchange(candles_with_dup)
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 18, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)

        assert df["timestamp"].duplicated().sum() == 0

    def test_stops_when_page_reaches_until(self) -> None:
        candles = _make_candles(3)
        ex = self._mock_exchange(candles)
        since = datetime.fromtimestamp(candles[0][0] / 1000, tz=UTC)
        until = datetime.fromtimestamp(candles[1][0] / 1000, tz=UTC)

        df = fetch_ohlcv(
            "BTC/USDT",
            "1d",
            since,
            until,
            exchange=ex,
            pagination_sleep_ms=0,
            max_candles=3,
        )

        assert len(df) == 1
        assert ex.fetch_ohlcv.call_count == 1


class TestSaveParquet:
    def test_creates_file(self, tmp_path: Path) -> None:
        candles = _make_candles(5)
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 20, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)
        dest = save_parquet(df, tmp_path, "BTC/USDT", "1d")

        assert dest.exists()
        assert dest.suffix == ".parquet"

    def test_parquet_readable(self, tmp_path: Path) -> None:
        candles = _make_candles(5)
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 20, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)
        dest = save_parquet(df, tmp_path, "BTC/USDT", "1d")

        loaded = pd.read_parquet(dest)
        assert len(loaded) == len(df)
        assert set(loaded.columns) == set(df.columns)

    def test_no_tmp_file_left_after_save(self, tmp_path: Path) -> None:
        candles = _make_candles(3)
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 18, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)
        save_parquet(df, tmp_path, "BTC/USDT", "1d")

        tmp_files = list(tmp_path.glob("*.tmp.parquet"))
        assert tmp_files == [], "Temporary file must be cleaned up after successful write"


class TestBuildExchange:
    """Verify _build_exchange always produces a Spot-type exchange in Phase 1."""

    def test_succeeds_in_phase1_without_mocking(self) -> None:
        """_build_exchange must not raise in Phase 1 — the spot factory is always allowed."""
        with (
            patch("aqcs.data.ohlcv.ccxt.binance") as mock_binance,
            patch("aqcs.data.ohlcv.get_settings") as mock_settings,
        ):
            mock_settings.return_value.binance_api_key = ""
            mock_binance.return_value = MagicMock()
            _build_exchange(sandbox=True)  # must not raise

    def test_default_type_is_spot(self) -> None:
        with (
            patch("aqcs.data.ohlcv.ccxt.binance") as mock_binance,
            patch("aqcs.data.ohlcv.get_settings") as mock_settings,
        ):
            mock_settings.return_value.binance_api_key = ""
            mock_binance.return_value = MagicMock()

            _build_exchange(sandbox=True)

            call_params = mock_binance.call_args[0][0]
            assert (
                call_params["options"]["defaultType"] == "spot"
            ), "_build_exchange must always use defaultType='spot' in Phase 1"

    def test_sandbox_mode_set_when_requested(self) -> None:
        with (
            patch("aqcs.data.ohlcv.ccxt.binance") as mock_binance,
            patch("aqcs.data.ohlcv.get_settings") as mock_settings,
        ):
            mock_settings.return_value.binance_api_key = ""
            mock_ex = MagicMock()
            mock_binance.return_value = mock_ex

            _build_exchange(sandbox=True)

            mock_ex.set_sandbox_mode.assert_called_once_with(True)

    def test_parquet_schema_matches_ohlcv_columns(self, tmp_path: Path) -> None:
        candles = _make_candles(2)
        ex = MagicMock()
        ex.id = "binance"
        ex.fetch_ohlcv.return_value = candles
        since = datetime(2023, 11, 14, tzinfo=UTC)
        until = datetime(2023, 11, 16, tzinfo=UTC)

        df = fetch_ohlcv("BTC/USDT", "1d", since, until, exchange=ex)
        dest = save_parquet(df, tmp_path, "BTC/USDT", "1d")

        file_schema = pq.read_schema(dest)
        declared_names = {f.name for f in OHLCV_SCHEMA}
        file_names = set(file_schema.names)
        assert declared_names == file_names


# ── CLI pipeline validation wiring ───────────────────────────────────────────


def _valid_df() -> pd.DataFrame:
    """Minimal valid OHLCV DataFrame for pipeline tests."""
    import pandas as pd

    dates = pd.date_range("2023-11-14", periods=3, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [30000.0, 30001.0, 30002.0],
            "high": [31000.0, 31001.0, 31002.0],
            "low": [29000.0, 29001.0, 29002.0],
            "close": [30500.0, 30501.0, 30502.0],
            "volume": [1000.0, 1001.0, 1002.0],
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "exchange": "binance",
        }
    )


class TestCLIPipelineValidation:
    """Verify that the CLI pipeline gates on validation before saving Parquet."""

    def _run_cli(
        self, tmp_path: Path, fetch_return: pd.DataFrame, validation_result: ValidationResult
    ) -> object:
        """Invoke the CLI with all network, IO, and logging mocked."""
        runner = CliRunner()
        with (
            patch("aqcs.data.ohlcv.configure_logging"),
            patch("aqcs.data.ohlcv._build_exchange") as mock_build,
            patch("aqcs.data.ohlcv.fetch_ohlcv", return_value=fetch_return),
            patch("aqcs.data.ohlcv.validate_ohlcv", return_value=validation_result),
            patch("aqcs.data.ohlcv.save_parquet") as mock_save,
        ):
            mock_build.return_value = MagicMock()
            result = runner.invoke(
                main,
                [
                    "--symbol",
                    "BTC/USDT",
                    "--timeframe",
                    "1d",
                    "--start",
                    "2023-11-14",
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        return result, mock_save

    def test_valid_data_is_saved(self, tmp_path: Path) -> None:
        df = _valid_df()
        ok = ValidationResult(is_valid=True, row_count=3, symbol="BTC/USDT", timeframe="1d")
        result, mock_save = self._run_cli(tmp_path, df, ok)
        assert result.exit_code == 0
        mock_save.assert_called_once()

    def test_invalid_data_is_not_saved(self, tmp_path: Path) -> None:
        df = _valid_df()
        fail = ValidationResult(
            is_valid=False,
            errors=["1 row(s) where high < low"],
            row_count=3,
            symbol="BTC/USDT",
            timeframe="1d",
        )
        result, mock_save = self._run_cli(tmp_path, df, fail)
        assert result.exit_code != 0
        mock_save.assert_not_called()

    def test_warnings_do_not_block_save(self, tmp_path: Path) -> None:
        df = _valid_df()
        warned = ValidationResult(
            is_valid=True,
            warnings=["1 missing bar(s): 2023-11-15T00:00:00Z to 2023-11-15T00:00:00Z"],
            row_count=3,
            symbol="BTC/USDT",
            timeframe="1d",
        )
        result, mock_save = self._run_cli(tmp_path, df, warned)
        assert result.exit_code == 0
        mock_save.assert_called_once()

    def test_multiple_validation_errors_all_logged(self, tmp_path: Path) -> None:
        df = _valid_df()
        fail = ValidationResult(
            is_valid=False,
            errors=["1 row(s) where high < low", "2 row(s) with negative volume"],
            row_count=3,
            symbol="BTC/USDT",
            timeframe="1d",
        )
        result, mock_save = self._run_cli(tmp_path, df, fail)
        assert result.exit_code != 0
        mock_save.assert_not_called()

    def test_validation_called_with_correct_args(self, tmp_path: Path) -> None:
        """validate_ohlcv must receive the symbol and timeframe from CLI args."""
        df = _valid_df()
        ok = ValidationResult(is_valid=True, row_count=3, symbol="BTC/USDT", timeframe="1d")
        runner = CliRunner()
        with (
            patch("aqcs.data.ohlcv.configure_logging"),
            patch("aqcs.data.ohlcv._build_exchange") as mock_build,
            patch("aqcs.data.ohlcv.fetch_ohlcv", return_value=df),
            patch("aqcs.data.ohlcv.validate_ohlcv", return_value=ok) as mock_validate,
            patch("aqcs.data.ohlcv.save_parquet"),
        ):
            mock_build.return_value = MagicMock()
            runner.invoke(
                main,
                [
                    "--symbol",
                    "ETH/USDT",
                    "--timeframe",
                    "4h",
                    "--start",
                    "2023-11-14",
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        assert mock_validate.called
        call_args = mock_validate.call_args[0]
        assert call_args[1] == "ETH/USDT"  # positional symbol
        assert call_args[2] == "4h"  # positional timeframe
