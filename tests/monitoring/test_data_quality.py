"""Deterministic data-quality monitoring tests.

Coverage:
- success path (valid dataset passes)
- missing intervals detected
- duplicate timestamps detected
- NaN values detected
- missing OHLCV columns rejected
- non-monotonic timestamps rejected
- stale dataset detected
- timezone violations rejected
- deterministic JSON output verified
- CLI exit code 0 on pass / 1 on fail
- same input produces identical report (deterministic replay)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from check_data_quality import main  # injected via tests/monitoring/conftest.py
from click.testing import CliRunner

from aqcs.monitoring.data_quality import (
    DataQualityReport,
    check_ohlcv_parquet_quality,
    report_to_dict,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1d"
_N = 60  # bars — enough for gap / stale tests without being slow
_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(
    n: int = _N,
    timeframe: str = _TIMEFRAME,
    *,
    utc: bool = True,
) -> pd.DataFrame:
    """Return a minimal, schema-valid OHLCV DataFrame."""
    freq_map = {"1m": "1min", "5m": "5min", "1h": "1h", "4h": "4h", "1d": "1D"}
    tz = "UTC" if utc else None
    idx = pd.date_range("2024-01-01", periods=n, freq=freq_map[timeframe], tz=tz)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": np.full(n, 100.0),
            "high": np.full(n, 101.0),
            "low": np.full(n, 99.0),
            "close": np.full(n, 100.5),
            "volume": np.full(n, 1_000.0),
            "symbol": _SYMBOL,
            "timeframe": timeframe,
            "exchange": "binance",
        }
    )


def _write(df: pd.DataFrame, tmp_path: Path, name: str = "data.parquet") -> Path:
    path = tmp_path / name
    df.to_parquet(path, index=False)
    return path


# ── Success path ──────────────────────────────────────────────────────────────


class TestValidDataset:
    def test_passes_with_no_errors_or_warnings(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is True
        assert report.errors == []
        assert report.row_count == _N
        assert report.required_columns_present is True
        assert report.utc_valid is True
        assert report.monotonic is True
        assert report.missing_interval_count == 0
        assert report.duplicate_timestamp_count == 0
        assert all(v == 0 for v in report.nan_count_by_column.values())

    def test_freshness_lag_computed(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        # Last row: 2024-03-01 (day 60); now: 2024-06-01 → ~91 days lag
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.freshness_lag_seconds is not None
        assert report.freshness_lag_seconds > 0

    def test_first_and_last_timestamps_populated(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.first_timestamp is not None
        assert report.last_timestamp is not None
        assert report.first_timestamp < report.last_timestamp

    def test_nan_count_by_column_keys_match_value_columns(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert set(report.nan_count_by_column.keys()) == {"open", "high", "low", "close", "volume"}


# ── Missing intervals ─────────────────────────────────────────────────────────


class TestMissingIntervals:
    def test_single_gap_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df = df.drop(index=10).reset_index(drop=True)  # remove one row → 1 missing bar
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is True  # gap is a warning, not an error
        assert report.missing_interval_count == 1
        assert any("missing interval" in w for w in report.warnings)

    def test_multiple_gaps_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df = df.drop(index=[5, 6, 20]).reset_index(drop=True)
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.missing_interval_count == 3

    def test_no_gaps_in_contiguous_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.missing_interval_count == 0


# ── Duplicate timestamps ──────────────────────────────────────────────────────


class TestDuplicateTimestamps:
    def test_duplicate_detected_as_warning(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        path = _write(dup, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.duplicate_timestamp_count == 1
        assert any("duplicate" in w for w in report.warnings)

    def test_multiple_duplicates_counted(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        dup = pd.concat([df, df.iloc[[0, 1, 2]]], ignore_index=True)
        path = _write(dup, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.duplicate_timestamp_count == 3


# ── NaN detection ─────────────────────────────────────────────────────────────


class TestNaNDetection:
    def test_single_nan_in_close(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df.loc[5, "close"] = float("nan")
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.nan_count_by_column["close"] == 1
        assert any("NaN" in w and "close" in w for w in report.warnings)
        assert report.passed is True  # NaN is a warning, not an error

    def test_multiple_nans_across_columns(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df.loc[3, "open"] = float("nan")
        df.loc[7, "volume"] = float("nan")
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.nan_count_by_column["open"] == 1
        assert report.nan_count_by_column["volume"] == 1

    def test_no_nans_in_clean_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert all(v == 0 for v in report.nan_count_by_column.values())


# ── Missing columns ───────────────────────────────────────────────────────────


class TestMissingColumns:
    def test_missing_close_column_fails(self, tmp_path: Path) -> None:
        df = _make_ohlcv().drop(columns=["close"])
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is False
        assert report.required_columns_present is False
        assert any("close" in e for e in report.errors)

    def test_missing_multiple_columns_fails(self, tmp_path: Path) -> None:
        df = _make_ohlcv().drop(columns=["open", "high", "symbol"])
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is False
        assert not report.required_columns_present


# ── Non-monotonic timestamps ──────────────────────────────────────────────────


class TestNonMonotonicTimestamps:
    def test_shuffled_timestamps_fail(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df["timestamp"] = df["timestamp"].sample(frac=1, random_state=99).reset_index(drop=True)
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is False
        assert report.monotonic is False
        assert any("monotonically" in e for e in report.errors)

    def test_reverse_order_fails(self, tmp_path: Path) -> None:
        df = _make_ohlcv().iloc[::-1].reset_index(drop=True)
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is False
        assert report.monotonic is False


# ── Stale dataset ─────────────────────────────────────────────────────────────


class TestStaleness:
    def test_stale_dataset_produces_warning(self, tmp_path: Path) -> None:
        df = _make_ohlcv()  # last bar: 2024-02-29 (day 60)
        path = _write(df, tmp_path)
        # now_utc far in the future: lag >> 2 × 86400s
        far_future = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=far_future)
        assert report.freshness_lag_seconds is not None
        assert report.freshness_lag_seconds > 86400 * 2
        assert any("stale" in w for w in report.warnings)
        assert report.passed is True  # staleness is a warning, not an error

    def test_fresh_dataset_has_no_stale_warning(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path = _write(df, tmp_path)
        last_ts = df["timestamp"].max().to_pydatetime()
        # now is just 10 seconds after the last bar — well under 2 × 86400s
        nearly_now = datetime(
            last_ts.year,
            last_ts.month,
            last_ts.day,
            last_ts.hour,
            last_ts.minute,
            last_ts.second + 10,
            tzinfo=UTC,
        )
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=nearly_now)
        assert not any("stale" in w for w in report.warnings)


# ── Timezone violations ───────────────────────────────────────────────────────


class TestTimezoneViolations:
    def test_naive_timestamps_rejected(self, tmp_path: Path) -> None:
        df = _make_ohlcv(utc=False)
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is False
        assert report.utc_valid is False
        assert any("naive" in e for e in report.errors)

    def test_utc_timestamps_accepted(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(utc=True), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.utc_valid is True


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_produces_identical_report(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        r1 = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        r2 = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert r1 == r2

    def test_json_output_is_deterministic(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        r1 = report_to_dict(check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW))
        r2 = report_to_dict(check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW))
        j1 = json.dumps(r1, sort_keys=True)
        j2 = json.dumps(r2, sort_keys=True)
        assert j1 == j2

    def test_report_fields_are_json_serializable(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        d = report_to_dict(report)
        serialized = json.dumps(d, sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["passed"] is True
        assert parsed["row_count"] == _N


# ── CLI ───────────────────────────────────────────────────────────────────────


class TestCLI:
    def test_exit_code_0_on_valid_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--parquet", str(path), "--timeframe", _TIMEFRAME])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] is True

    def test_exit_code_1_on_missing_columns(self, tmp_path: Path) -> None:
        df = _make_ohlcv().drop(columns=["close"])
        path = _write(df, tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--parquet", str(path), "--timeframe", _TIMEFRAME])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["passed"] is False

    def test_exit_code_1_on_naive_timestamps(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(utc=False), tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--parquet", str(path), "--timeframe", _TIMEFRAME])
        assert result.exit_code == 1

    def test_cli_json_output_is_valid_json(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--parquet", str(path), "--timeframe", _TIMEFRAME])
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)
        assert "passed" in parsed
        assert "errors" in parsed
        assert "warnings" in parsed

    def test_cli_rejects_unsupported_timeframe(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--parquet", str(path), "--timeframe", "3d"])
        # Click rejects invalid choice before our code runs
        assert result.exit_code != 0

    def test_cli_deterministic_output_across_runs(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        runner = CliRunner()
        r1 = runner.invoke(main, ["--parquet", str(path), "--timeframe", _TIMEFRAME])
        r2 = runner.invoke(main, ["--parquet", str(path), "--timeframe", _TIMEFRAME])
        # Exclude freshness_lag_seconds which depends on wall-clock time
        d1 = json.loads(r1.output)
        d2 = json.loads(r2.output)
        for key in d1:
            if key != "freshness_lag_seconds":
                assert d1[key] == d2[key], f"Non-deterministic field: {key}"


# ── Regression tests for primary data-integrity risks ────────────────────────


class TestRegressions:
    def test_unsupported_timeframe_returns_error_report(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, "3d", now_utc=_FIXED_NOW)
        assert report.passed is False
        assert any("Unsupported timeframe" in e for e in report.errors)

    def test_empty_dataset_fails(self, tmp_path: Path) -> None:
        df = _make_ohlcv().iloc[0:0]  # 0 rows, same schema
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert report.passed is False
        assert report.row_count == 0
        assert any("empty" in e for e in report.errors)

    def test_hourly_timeframe_detects_gap(self, tmp_path: Path) -> None:
        df = _make_ohlcv(n=48, timeframe="1h")
        df = df.drop(index=24).reset_index(drop=True)  # gap of 1 hour
        path = _write(df, tmp_path)
        report = check_ohlcv_parquet_quality(path, "1h", now_utc=_FIXED_NOW)
        assert report.missing_interval_count == 1

    def test_report_dataclass_is_immutable(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        report = check_ohlcv_parquet_quality(path, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert isinstance(report, DataQualityReport)
        with pytest.raises((AttributeError, TypeError)):
            report.passed = False  # type: ignore[misc]
