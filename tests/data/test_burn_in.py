"""Tests for the read-only OHLCV data capture burn-in.

All tests use mocked API responses. No live network calls are made.

Coverage:
- CLI: unsupported symbol, timeframe, exchange, zero limit, above-max limit,
       empty symbols list, missing output-dir, mixed valid/invalid symbols
- Successful multi-symbol burn-in (all symbols pass)
- Partial symbol failure (one symbol fails, others continue)
- All-symbol failure
- Validation failure for one symbol (duplicate timestamps)
- Validation failure for one symbol (non-monotonic timestamps)
- Manifest generated and saved to disk
- Manifest verification verified in result
- Manifest verification failure detected (corrupted parquet)
- Deterministic JSON summary (two runs with identical mock data)
- Status "passed" only when ALL symbols pass
- Status "failed" when ANY symbol fails
- Results dict contains all requested symbols
- No API key usage (public exchange only)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner
from run_public_ohlcv_burn_in import (
    _DEFAULT_LIMIT,
    _MAX_LIMIT,
    _SYMBOL_TO_CCXT,
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    main,
    run_burn_in,
    run_symbol_capture,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_TIMEFRAME = "1h"
_EXCHANGE = "binance"
_HOUR_MS = 3_600_000
_BASE_MS = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC

_ALL_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_raw_candles(
    n: int = _DEFAULT_LIMIT,
    base_ms: int = _BASE_MS,
    price_offset: float = 0.0,
) -> list[list]:
    """Return synthetic ccxt-format OHLCV rows."""
    return [
        [
            base_ms + i * _HOUR_MS,
            45_000.0 + price_offset + i * 10,
            45_100.0 + price_offset + i * 10,
            44_900.0 + price_offset + i * 10,
            45_050.0 + price_offset + i * 10,
            100.0 + i,
        ]
        for i in range(n)
    ]


def _make_mock_exchange(
    candles_map: dict[str, list[list]],
    exchange_id: str = "binance",
) -> MagicMock:
    """Return a mock exchange where fetch_ohlcv returns per-ccxt-symbol data."""
    ex = MagicMock()
    ex.id = exchange_id

    def _fetch(symbol, timeframe, limit):
        return candles_map.get(symbol, _make_raw_candles(limit))

    ex.fetch_ohlcv.side_effect = lambda symbol, **kw: candles_map.get(
        symbol, _make_raw_candles(kw.get("limit", _DEFAULT_LIMIT))
    )
    return ex


def _make_valid_df(ccxt_symbol: str, n: int = _DEFAULT_LIMIT) -> pd.DataFrame:
    """Return a valid schema-complete OHLCV DataFrame (UTC timestamps)."""
    base_ts = datetime(2024, 1, 1, tzinfo=UTC)
    timestamps = [base_ts + timedelta(hours=i) for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(timestamps, tz="UTC"),
            "open": [45_000.0 + i for i in range(n)],
            "high": [45_100.0 + i for i in range(n)],
            "low": [44_900.0 + i for i in range(n)],
            "close": [45_050.0 + i for i in range(n)],
            "volume": [100.0 + i for i in range(n)],
            "symbol": ccxt_symbol,
            "timeframe": _TIMEFRAME,
            "exchange": _EXCHANGE,
        }
    )


def _all_candles_map(n: int = _DEFAULT_LIMIT) -> dict[str, list[list]]:
    """Return a candles map with valid data for all supported symbols."""
    return {
        "BTC/USDT": _make_raw_candles(n, price_offset=0.0),
        "ETH/USDT": _make_raw_candles(n, price_offset=3000.0),
        "SOL/USDT": _make_raw_candles(n, price_offset=100.0),
    }


# ── CLI argument validation ───────────────────────────────────────────────────


class TestCLIArgumentValidation:
    def test_rejects_unsupported_symbol(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--symbols", "XRPUSDT", "--timeframe", "1h", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "Unsupported" in result.output or "unsupported" in result.output

    def test_rejects_mixed_valid_and_invalid_symbols(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbols",
                "BTCUSDT,XRPUSDT",
                "--timeframe",
                "1h",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_rejects_unsupported_timeframe(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbols",
                "BTCUSDT",
                "--timeframe",
                "1d",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_rejects_unsupported_exchange(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbols",
                "BTCUSDT",
                "--timeframe",
                "1h",
                "--exchange",
                "kraken",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_rejects_zero_limit(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbols",
                "BTCUSDT",
                "--timeframe",
                "1h",
                "--limit",
                "0",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_rejects_limit_above_max(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbols",
                "BTCUSDT",
                "--timeframe",
                "1h",
                "--limit",
                str(_MAX_LIMIT + 1),
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_rejects_missing_output_dir(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--symbols", "BTCUSDT", "--timeframe", "1h"])
        assert result.exit_code != 0


# ── Successful multi-symbol burn-in ──────────────────────────────────────────


class TestSuccessfulBurnIn:
    def test_all_symbols_pass(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "passed"
        assert result["symbols_failed"] == []
        assert set(result["symbols_passed"]) == set(_ALL_SYMBOLS)

    def test_results_dict_contains_all_symbols(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert set(result["results"].keys()) == set(_ALL_SYMBOLS)

    def test_all_symbol_statuses_passed(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        for code in _ALL_SYMBOLS:
            assert result["results"][code]["status"] == "passed", f"{code} failed"

    def test_parquet_files_created(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        parquet_files = list(tmp_path.glob("*.parquet"))
        assert len(parquet_files) == len(_ALL_SYMBOLS)

    def test_manifest_files_created(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        manifest_files = list(tmp_path.glob("*_manifest.json"))
        assert len(manifest_files) == len(_ALL_SYMBOLS)

    def test_manifest_verified_for_each_symbol(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        for code in _ALL_SYMBOLS:
            assert result["results"][code]["manifest_verified"] is True

    def test_rows_fetched_matches_limit(self, tmp_path: Path) -> None:
        n = 48
        mock_ex = _make_mock_exchange(_all_candles_map(n))
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, n, tmp_path, exchange=mock_ex)
        for code in _ALL_SYMBOLS:
            assert result["results"][code]["rows_fetched"] == n

    def test_manifest_content_hash_present(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(["BTCUSDT"], _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        h = result["results"]["BTCUSDT"]["manifest"]["content_hash"]
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_single_symbol_burn_in(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange({"BTC/USDT": _make_raw_candles()})
        result = run_burn_in(["BTCUSDT"], _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "passed"
        assert result["symbols_requested"] == ["BTCUSDT"]

    def test_output_dir_created_if_not_exists(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "nested" / "output"
        mock_ex = _make_mock_exchange(_all_candles_map())
        run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, new_dir, exchange=mock_ex)
        assert new_dir.exists()

    def test_symbols_requested_preserved_in_result(self, tmp_path: Path) -> None:
        subset = ["BTCUSDT", "ETHUSDT"]
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(subset, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["symbols_requested"] == subset

    def test_cli_exit_0_on_success(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        runner = CliRunner()
        with patch("run_public_ohlcv_burn_in._build_public_exchange", return_value=mock_ex):
            result = runner.invoke(
                main,
                [
                    "--symbols",
                    "BTCUSDT,ETHUSDT,SOLUSDT",
                    "--timeframe",
                    _TIMEFRAME,
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0
        # Extract the JSON block from mixed output
        json_text = result.output[result.output.index("{") :]
        data = json.loads(json_text)
        assert data["status"] == "passed"


# ── Partial symbol failure ────────────────────────────────────────────────────


class TestPartialSymbolFailure:
    def test_one_symbol_fails_others_continue(self, tmp_path: Path) -> None:
        """BTC returns no data → fails; ETH and SOL proceed normally."""
        candles_map = {
            "BTC/USDT": [],  # empty → fail
            "ETH/USDT": _make_raw_candles(),
            "SOL/USDT": _make_raw_candles(),
        }
        mock_ex = _make_mock_exchange(candles_map)
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "failed"
        assert "BTCUSDT" in result["symbols_failed"]
        assert "ETHUSDT" in result["symbols_passed"]
        assert "SOLUSDT" in result["symbols_passed"]

    def test_all_symbols_fail(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange({"BTC/USDT": [], "ETH/USDT": [], "SOL/USDT": []})
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "failed"
        assert set(result["symbols_failed"]) == set(_ALL_SYMBOLS)
        assert result["symbols_passed"] == []

    def test_status_failed_when_any_symbol_fails(self, tmp_path: Path) -> None:
        candles_map = {
            "BTC/USDT": _make_raw_candles(),
            "ETH/USDT": [],
            "SOL/USDT": _make_raw_candles(),
        }
        mock_ex = _make_mock_exchange(candles_map)
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "failed"


# ── Validation failures ───────────────────────────────────────────────────────


class TestValidationFailures:
    def test_duplicate_timestamps_fail(self, tmp_path: Path) -> None:
        df_btc = _make_valid_df("BTC/USDT")
        dup = pd.concat([df_btc, df_btc.iloc[[0]]], ignore_index=True)

        def _side(exchange, ccxt_sym, tf, limit):
            if ccxt_sym == "BTC/USDT":
                return dup
            return _make_valid_df(ccxt_sym)

        with patch("run_public_ohlcv_burn_in._fetch_ohlcv", side_effect=_side):
            mock_ex = MagicMock()
            mock_ex.id = "binance"
            result = run_burn_in(
                _ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
            )
        assert result["results"]["BTCUSDT"]["status"] == "failed"
        btc_errors = result["results"]["BTCUSDT"]["validation"]["errors"]
        assert any("duplicate" in e.lower() for e in btc_errors)

    def test_non_monotonic_timestamps_fail(self, tmp_path: Path) -> None:
        df_eth = _make_valid_df("ETH/USDT").iloc[::-1].reset_index(drop=True)

        def _side(exchange, ccxt_sym, tf, limit):
            if ccxt_sym == "ETH/USDT":
                return df_eth
            return _make_valid_df(ccxt_sym)

        with patch("run_public_ohlcv_burn_in._fetch_ohlcv", side_effect=_side):
            mock_ex = MagicMock()
            mock_ex.id = "binance"
            result = run_burn_in(
                _ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
            )
        assert result["results"]["ETHUSDT"]["status"] == "failed"
        eth_errors = result["results"]["ETHUSDT"]["validation"]["errors"]
        assert any("monoton" in e.lower() or "increasing" in e.lower() for e in eth_errors)

    def test_failed_symbol_has_no_parquet(self, tmp_path: Path) -> None:
        candles_map = {
            "BTC/USDT": [],
            "ETH/USDT": _make_raw_candles(),
            "SOL/USDT": _make_raw_candles(),
        }
        mock_ex = _make_mock_exchange(candles_map)
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["results"]["BTCUSDT"]["parquet_path"] is None

    def test_failed_symbol_has_no_manifest(self, tmp_path: Path) -> None:
        candles_map = {
            "BTC/USDT": [],
            "ETH/USDT": _make_raw_candles(),
            "SOL/USDT": _make_raw_candles(),
        }
        mock_ex = _make_mock_exchange(candles_map)
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["results"]["BTCUSDT"]["manifest_path"] is None


# ── Manifest integration ──────────────────────────────────────────────────────


class TestManifestIntegration:
    def test_manifest_saved_to_disk(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange({"BTC/USDT": _make_raw_candles()})
        result = run_symbol_capture(
            "BTCUSDT", _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["manifest_path"] is not None
        assert Path(result["manifest_path"]).exists()

    def test_manifest_json_is_loadable(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange({"BTC/USDT": _make_raw_candles()})
        result = run_symbol_capture(
            "BTCUSDT", _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        manifest_data = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        assert "content_hash" in manifest_data
        assert manifest_data["row_count"] == _DEFAULT_LIMIT

    def test_manifest_verified_true_on_untampered_data(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange({"BTC/USDT": _make_raw_candles()})
        result = run_symbol_capture(
            "BTCUSDT", _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["manifest_verified"] is True

    def test_manifest_row_count_matches_rows_fetched(self, tmp_path: Path) -> None:
        n = 24
        mock_ex = _make_mock_exchange({"BTC/USDT": _make_raw_candles(n)})
        result = run_symbol_capture("BTCUSDT", _TIMEFRAME, n, tmp_path, exchange=mock_ex)
        assert result["manifest"]["row_count"] == result["rows_fetched"]

    def test_manifest_verification_failure_on_corrupted_parquet(self, tmp_path: Path) -> None:
        """Corrupting a parquet after manifest generation must be detectable."""
        mock_ex = _make_mock_exchange({"BTC/USDT": _make_raw_candles()})
        result = run_symbol_capture(
            "BTCUSDT", _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["status"] == "passed"

        from aqcs.data.manifest import load_manifest, verify_manifest

        parquet_path = Path(result["parquet_path"])
        manifest_path = Path(result["manifest_path"])

        loaded = load_manifest(manifest_path)
        # Corrupt the parquet by overwriting with garbage
        parquet_path.write_bytes(b"corrupted content")

        with pytest.raises(ValueError):
            verify_manifest(parquet_path, loaded)


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_json_output_deterministic_across_runs(self, tmp_path: Path) -> None:
        candles = _all_candles_map()
        mock1 = _make_mock_exchange(candles)
        mock2 = _make_mock_exchange(candles)

        r1 = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path / "r1", exchange=mock1)
        r2 = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path / "r2", exchange=mock2)

        # Status, counts, and manifest hashes must be identical
        assert r1["status"] == r2["status"]
        assert r1["symbols_passed"] == r2["symbols_passed"]
        for code in _ALL_SYMBOLS:
            m1 = r1["results"][code]["manifest"]
            m2 = r2["results"][code]["manifest"]
            assert m1["content_hash"] == m2["content_hash"]
            assert m1["schema_hash"] == m2["schema_hash"]
            assert m1["row_count"] == m2["row_count"]

    def test_result_is_json_serializable(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        serialized = json.dumps(result, sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["status"] == "passed"

    def test_status_passed_only_when_all_pass(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "passed"

    def test_status_failed_when_any_fail(self, tmp_path: Path) -> None:
        candles_map = {
            "BTC/USDT": [],
            "ETH/USDT": _make_raw_candles(),
            "SOL/USDT": _make_raw_candles(),
        }
        mock_ex = _make_mock_exchange(candles_map)
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        assert result["status"] == "failed"

    def test_cli_exit_1_on_any_failure(self, tmp_path: Path) -> None:
        candles_map = {
            "BTC/USDT": [],
            "ETH/USDT": _make_raw_candles(),
            "SOL/USDT": _make_raw_candles(),
        }
        mock_ex = _make_mock_exchange(candles_map)
        runner = CliRunner()
        with patch("run_public_ohlcv_burn_in._build_public_exchange", return_value=mock_ex):
            result = runner.invoke(
                main,
                [
                    "--symbols",
                    "BTCUSDT,ETHUSDT,SOLUSDT",
                    "--timeframe",
                    _TIMEFRAME,
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 1


# ── No live network / no API key ──────────────────────────────────────────────


class TestNoNetworkNoAPIKey:
    def test_build_public_exchange_uses_no_key(self) -> None:
        """_build_public_exchange must not require settings or env secrets."""
        from run_public_ohlcv_burn_in import _build_public_exchange

        # Should not raise — even without env vars or config files
        ex = _build_public_exchange("binance")
        # Should be a ccxt exchange instance without private credentials
        assert ex is not None
        # apiKey should be absent or empty/None for a public instance
        api_key = getattr(ex, "apiKey", None) or getattr(ex, "api_key", None)
        assert not api_key  # falsy: None, empty string, or absent

    def test_mocked_exchange_never_calls_real_network(self, tmp_path: Path) -> None:
        """Using a mock exchange must produce a result without any real API call."""
        mock_ex = _make_mock_exchange(_all_candles_map())
        result = run_burn_in(_ALL_SYMBOLS, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        # The real fetch_ohlcv would require network; mock was used instead
        assert mock_ex.fetch_ohlcv.called
        assert result["status"] == "passed"


# ── Constants sanity ──────────────────────────────────────────────────────────


class TestConstants:
    def test_supported_symbols_contains_all_three(self) -> None:
        assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"}.issubset(SUPPORTED_SYMBOLS)

    def test_supported_timeframes_contains_1h(self) -> None:
        assert "1h" in SUPPORTED_TIMEFRAMES

    def test_symbol_map_covers_all_supported(self) -> None:
        for code in SUPPORTED_SYMBOLS:
            assert code in _SYMBOL_TO_CCXT, f"{code} not in _SYMBOL_TO_CCXT"

    def test_max_limit_exceeds_default(self) -> None:
        assert _MAX_LIMIT > _DEFAULT_LIMIT

    def test_default_limit_positive(self) -> None:
        assert _DEFAULT_LIMIT > 0
