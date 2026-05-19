"""Tests for the read-only Binance Spot OHLCV public API smoke test.

All tests use mocked API responses. No live network calls are made.

Coverage:
- CLI argument validation: unsupported symbol, timeframe, exchange, limit
- Successful smoke flow (mocked exchange)
- Empty API response handled gracefully
- Duplicate timestamp failure (mocked _fetch_ohlcv)
- Non-monotonic timestamp failure (mocked _fetch_ohlcv)
- Manifest generation verified in smoke result
- Manifest verification failure on corrupted parquet
- Deterministic JSON summary (two runs with identical mock data)
- Status field is "passed" on success, "failed" on validation error
- Parquet file is written with correct symbol/timeframe naming
- JSON output contains all required fields
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from click.testing import CliRunner
from smoke_test_public_ohlcv import (
    _DEFAULT_LIMIT,
    _MAX_LIMIT,
    _SYMBOL_TO_CCXT,
    SUPPORTED_SYMBOLS,
    SUPPORTED_TIMEFRAMES,
    main,
    run_smoke_test,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_SYMBOL_CODE = "BTCUSDT"
_CCXT_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1h"
_EXCHANGE = "binance"
_HOUR_MS = 3_600_000
_BASE_MS = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_raw_candles(n: int = _DEFAULT_LIMIT, base_ms: int = _BASE_MS) -> list[list]:
    """Return synthetic ccxt-format OHLCV rows (timestamp_ms, o, h, l, c, v)."""
    return [
        [
            base_ms + i * _HOUR_MS,
            45_000.0 + i * 10,
            45_100.0 + i * 10,
            44_900.0 + i * 10,
            45_050.0 + i * 10,
            100.0 + i,
        ]
        for i in range(n)
    ]


def _make_mock_exchange(candles: list[list], exchange_id: str = "binance") -> MagicMock:
    ex = MagicMock()
    ex.id = exchange_id
    ex.fetch_ohlcv.return_value = candles
    return ex


def _make_valid_df(n: int = _DEFAULT_LIMIT) -> pd.DataFrame:
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
            "symbol": _CCXT_SYMBOL,
            "timeframe": _TIMEFRAME,
            "exchange": _EXCHANGE,
        }
    )


# ── CLI argument validation ───────────────────────────────────────────────────


class TestCLIArgumentValidation:
    def test_rejects_unsupported_symbol(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--symbol", "XRPUSDT", "--timeframe", "1h", "--output-dir", "/tmp"],
        )
        assert result.exit_code != 0
        assert "xrpusdt" in result.output.lower() or "invalid" in result.output.lower()

    def test_rejects_unsupported_timeframe(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--symbol", "BTCUSDT", "--timeframe", "1d", "--output-dir", "/tmp"],
        )
        assert result.exit_code != 0

    def test_rejects_unsupported_exchange(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--symbol",
                "BTCUSDT",
                "--timeframe",
                "1h",
                "--exchange",
                "kraken",
                "--output-dir",
                "/tmp",
            ],
        )
        assert result.exit_code != 0

    def test_rejects_zero_limit(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch("smoke_test_public_ohlcv.run_smoke_test") as mock_run:
            mock_run.return_value = {"status": "passed"}
            result = runner.invoke(
                main,
                [
                    "--symbol",
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
        with patch("smoke_test_public_ohlcv.run_smoke_test") as mock_run:
            mock_run.return_value = {"status": "passed"}
            result = runner.invoke(
                main,
                [
                    "--symbol",
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

    def test_accepts_valid_limit_at_max(self, tmp_path: Path) -> None:
        candles = _make_raw_candles(_MAX_LIMIT)
        mock_ex = _make_mock_exchange(candles)
        result = run_smoke_test(
            _SYMBOL_CODE,
            _TIMEFRAME,
            _MAX_LIMIT,
            tmp_path,
            exchange=mock_ex,
        )
        assert result["status"] == "passed"
        assert result["limit_requested"] == _MAX_LIMIT

    def test_missing_output_dir_option_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--symbol", "BTCUSDT", "--timeframe", "1h"],
        )
        assert result.exit_code != 0


# ── Successful smoke flow ─────────────────────────────────────────────────────


class TestSuccessfulSmokeFlow:
    def test_status_passed(self, tmp_path: Path) -> None:
        candles = _make_raw_candles()
        mock_ex = _make_mock_exchange(candles)
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["status"] == "passed"

    def test_rows_fetched_matches_candles(self, tmp_path: Path) -> None:
        n = 24
        mock_ex = _make_mock_exchange(_make_raw_candles(n))
        result = run_smoke_test(_SYMBOL_CODE, _TIMEFRAME, n, tmp_path, exchange=mock_ex)
        assert result["rows_fetched"] == n

    def test_parquet_file_is_created(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["parquet_path"] is not None
        assert Path(result["parquet_path"]).exists()

    def test_parquet_filename_uses_ccxt_symbol(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        parquet_name = Path(result["parquet_path"]).name
        # save_parquet uses "BTC_USDT_1h.parquet" for symbol "BTC/USDT"
        assert "BTC" in parquet_name and "USDT" in parquet_name

    def test_validation_is_valid(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["validation"]["is_valid"] is True
        assert result["validation"]["errors"] == []

    def test_manifest_fields_present(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        manifest = result["manifest"]
        assert len(manifest["content_hash"]) == 64
        assert len(manifest["schema_hash"]) == 64
        assert manifest["row_count"] == _DEFAULT_LIMIT
        assert manifest["start_timestamp_utc"] != ""
        assert manifest["end_timestamp_utc"] != ""

    def test_manifest_verified(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["manifest_verified"] is True

    def test_data_quality_passed(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["data_quality"]["passed"] is True
        assert result["data_quality"]["duplicate_count"] == 0

    def test_symbol_in_result_is_ccxt_format(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["symbol"] == _CCXT_SYMBOL

    def test_all_required_keys_present(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        required_keys = {
            "smoke_test",
            "status",
            "exchange",
            "symbol",
            "timeframe",
            "limit_requested",
            "rows_fetched",
            "parquet_path",
            "validation",
            "data_quality",
            "manifest",
            "manifest_verified",
        }
        assert required_keys.issubset(result.keys())

    def test_cli_exit_0_on_success(self, tmp_path: Path) -> None:
        candles = _make_raw_candles()
        mock_ex = _make_mock_exchange(candles)
        runner = CliRunner()
        with patch("smoke_test_public_ohlcv._build_public_exchange", return_value=mock_ex):
            result = runner.invoke(
                main,
                [
                    "--symbol",
                    _SYMBOL_CODE,
                    "--timeframe",
                    _TIMEFRAME,
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 0
        # The CLI may emit structlog lines before the JSON summary.
        # Extract the JSON block starting at the first '{'.
        json_text = result.output[result.output.index("{") :]
        data = json.loads(json_text)
        assert data["status"] == "passed"


# ── Empty API response ────────────────────────────────────────────────────────


class TestEmptyAPIResponse:
    def test_empty_response_returns_failed(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange([])
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["status"] == "failed"
        assert result["rows_fetched"] == 0
        assert result["parquet_path"] is None

    def test_empty_response_no_parquet_written(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange([])
        run_smoke_test(_SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex)
        parquet_files = list(tmp_path.glob("*.parquet"))
        assert parquet_files == []


# ── Validation failures via patched _fetch_ohlcv ─────────────────────────────


class TestValidationFailures:
    def test_duplicate_timestamp_fails(self, tmp_path: Path) -> None:
        df_with_dups = _make_valid_df()
        # Inject a duplicate row
        dup_row = df_with_dups.iloc[[0]].copy()
        df_with_dups = pd.concat([df_with_dups, dup_row], ignore_index=True)

        with patch("smoke_test_public_ohlcv._fetch_ohlcv", return_value=df_with_dups):
            mock_ex = _make_mock_exchange([])
            result = run_smoke_test(
                _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
            )
        assert result["status"] == "failed"
        assert any("duplicate" in e.lower() for e in result["validation"]["errors"])
        assert result.get("parquet_path") is None

    def test_non_monotonic_timestamp_fails(self, tmp_path: Path) -> None:
        df = _make_valid_df()
        # Reverse order = non-monotonic
        df_reversed = df.iloc[::-1].reset_index(drop=True)

        with patch("smoke_test_public_ohlcv._fetch_ohlcv", return_value=df_reversed):
            mock_ex = _make_mock_exchange([])
            result = run_smoke_test(
                _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
            )
        assert result["status"] == "failed"
        assert any(
            "increasing" in e.lower() or "monoton" in e.lower()
            for e in result["validation"]["errors"]
        )

    def test_naive_timestamps_fail(self, tmp_path: Path) -> None:
        df = _make_valid_df()
        # Strip timezone → naive timestamps
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)

        with patch("smoke_test_public_ohlcv._fetch_ohlcv", return_value=df):
            mock_ex = _make_mock_exchange([])
            result = run_smoke_test(
                _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
            )
        assert result["status"] == "failed"
        assert result.get("parquet_path") is None


# ── Manifest integration ──────────────────────────────────────────────────────


class TestManifestIntegration:
    def test_manifest_content_hash_is_sha256_hex(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        h = result["manifest"]["content_hash"]
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_manifest_row_count_matches_rows_fetched(self, tmp_path: Path) -> None:
        n = 12
        mock_ex = _make_mock_exchange(_make_raw_candles(n))
        result = run_smoke_test(_SYMBOL_CODE, _TIMEFRAME, n, tmp_path, exchange=mock_ex)
        assert result["manifest"]["row_count"] == result["rows_fetched"]

    def test_manifest_verified_is_true_on_untampered_data(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["manifest_verified"] is True

    def test_manifest_verified_fails_on_corrupted_parquet(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["status"] == "passed"

        # Extract manifest and parquet path from the first run
        from aqcs.data.manifest import load_manifest, verify_manifest

        # We cannot verify a manifest against a corrupted parquet via run_smoke_test
        # directly, so we verify the generate/verify round-trip independently.
        parquet_path = Path(result["parquet_path"])
        manifest_path = tmp_path / "manifest.json"

        from aqcs.data.manifest import generate_manifest, save_manifest

        manifest = generate_manifest(parquet_path, _CCXT_SYMBOL, _TIMEFRAME)
        save_manifest(manifest, manifest_path)

        # Corrupt the parquet by overwriting with garbage
        parquet_path.write_bytes(b"corrupted parquet content")

        loaded_manifest = load_manifest(manifest_path)
        # Cannot call verify_manifest on a corrupted file because generate_manifest
        # inside it will raise ValueError — confirm this is detected
        with pytest.raises(ValueError):
            verify_manifest(parquet_path, loaded_manifest)


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_json_output_deterministic(self, tmp_path: Path) -> None:
        candles = _make_raw_candles()

        mock_ex1 = _make_mock_exchange(candles)
        r1 = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path / "run1", exchange=mock_ex1
        )

        mock_ex2 = _make_mock_exchange(candles)
        r2 = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path / "run2", exchange=mock_ex2
        )

        # Compare all deterministic fields (exclude parquet_path which is path-specific)
        for key in ("status", "exchange", "symbol", "timeframe", "rows_fetched"):
            assert r1[key] == r2[key], f"Field '{key}' differs: {r1[key]} vs {r2[key]}"

        # Manifest hashes must be identical for identical data
        assert r1["manifest"]["content_hash"] == r2["manifest"]["content_hash"]
        assert r1["manifest"]["schema_hash"] == r2["manifest"]["schema_hash"]
        assert r1["manifest"]["row_count"] == r2["manifest"]["row_count"]

    def test_status_is_passed_string_on_success(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["status"] == "passed"

    def test_status_is_failed_string_on_failure(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange([])
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        assert result["status"] == "failed"

    def test_result_is_json_serializable(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        result = run_smoke_test(
            _SYMBOL_CODE, _TIMEFRAME, _DEFAULT_LIMIT, tmp_path, exchange=mock_ex
        )
        serialized = json.dumps(result, sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["status"] == "passed"

    def test_cli_outputs_valid_json(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange(_make_raw_candles())
        runner = CliRunner()
        with patch("smoke_test_public_ohlcv._build_public_exchange", return_value=mock_ex):
            result = runner.invoke(
                main,
                [
                    "--symbol",
                    _SYMBOL_CODE,
                    "--timeframe",
                    _TIMEFRAME,
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        json_text = result.output[result.output.index("{") :]
        parsed = json.loads(json_text)
        assert isinstance(parsed, dict)
        assert "status" in parsed

    def test_cli_exit_1_on_failure(self, tmp_path: Path) -> None:
        mock_ex = _make_mock_exchange([])
        runner = CliRunner()
        with patch("smoke_test_public_ohlcv._build_public_exchange", return_value=mock_ex):
            result = runner.invoke(
                main,
                [
                    "--symbol",
                    _SYMBOL_CODE,
                    "--timeframe",
                    _TIMEFRAME,
                    "--output-dir",
                    str(tmp_path),
                ],
            )
        assert result.exit_code == 1


# ── Symbol mapping constants ──────────────────────────────────────────────────


class TestConstants:
    def test_supported_symbols_are_frozenset(self) -> None:
        assert isinstance(SUPPORTED_SYMBOLS, frozenset)
        assert "BTCUSDT" in SUPPORTED_SYMBOLS

    def test_supported_timeframes_contains_1h(self) -> None:
        assert "1h" in SUPPORTED_TIMEFRAMES

    def test_symbol_map_covers_all_supported(self) -> None:
        for code in SUPPORTED_SYMBOLS:
            assert code in _SYMBOL_TO_CCXT, f"{code} not in _SYMBOL_TO_CCXT"

    def test_max_limit_exceeds_default(self) -> None:
        assert _MAX_LIMIT > _DEFAULT_LIMIT

    def test_default_limit_positive(self) -> None:
        assert _DEFAULT_LIMIT > 0
