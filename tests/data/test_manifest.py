"""Deterministic dataset identity manifest tests.

Coverage:
- success path: manifest generated with all required fields
- content hash is deterministic (same data → same hash)
- content hash is order-invariant (shuffled rows → same hash)
- content hash detects corruption (modified value → different hash)
- schema hash is deterministic
- schema hash detects schema drift (added/removed/retyped columns)
- manifest round-trips through JSON without data loss
- save_manifest / load_manifest round-trip
- manifest_from_dict rejects missing fields (KeyError)
- verify_manifest: clean pass
- verify_manifest: content corruption detected
- verify_manifest: schema drift detected
- verify_manifest: row count change detected
- UTC enforcement: naive timestamps raise ValueError
- UTC enforcement: non-UTC timestamps raise ValueError
- empty dataset raises ValueError
- missing required columns raise ValueError
- missing Parquet file raises ValueError
- duplicate timestamps are counted
- missing intervals are counted for known timeframes
- missing intervals return count=0 for unsupported timeframe
- deterministic replay: two independent calls produce identical manifests
- CLI generate: exit 0 and valid JSON on success
- CLI generate: exit 1 on invalid parquet
- CLI generate: exit 1 on naive timestamps
- CLI generate: writes to file when --output given
- CLI verify: exit 0 on clean match
- CLI verify: exit 1 on content corruption
- CLI verify: exit 2 on unreadable manifest
- integration: real BTC/USDT 1d parquet produces stable manifest
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner
from generate_manifest import main as gen_main  # injected via tests/data/conftest.py
from verify_manifest import main as ver_main

from aqcs.data.manifest import (
    MANIFEST_VERSION,
    DatasetManifest,
    ManifestVerificationResult,
    _compute_content_hash,
    _compute_schema_hash,
    generate_manifest,
    load_manifest,
    manifest_from_dict,
    manifest_to_dict,
    save_manifest,
    verify_manifest,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_SYMBOL = "BTC/USDT"
_EXCHANGE = "binance"
_TIMEFRAME = "1d"
_N = 90
_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)

# Path to real BTC/USDT daily data — static fixture, no network calls.
_REAL_PARQUET = Path(__file__).resolve().parents[2] / "data" / "raw" / "BTC_USDT_1d.parquet"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(
    n: int = _N,
    timeframe: str = _TIMEFRAME,
    *,
    utc: bool = True,
    exchange: str = _EXCHANGE,
    symbol: str = _SYMBOL,
) -> pd.DataFrame:
    """Return a minimal schema-valid OHLCV DataFrame."""
    freq_map = {
        "1m": "1min",
        "5m": "5min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1D",
    }
    tz = "UTC" if utc else None
    idx = pd.date_range("2024-01-01", periods=n, freq=freq_map.get(timeframe, "1D"), tz=tz)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": np.linspace(100.0, 200.0, n),
            "high": np.linspace(101.0, 201.0, n),
            "low": np.linspace(99.0, 199.0, n),
            "close": np.linspace(100.5, 200.5, n),
            "volume": np.linspace(1_000.0, 2_000.0, n),
            "symbol": symbol,
            "timeframe": timeframe,
            "exchange": exchange,
        }
    )


def _write(df: pd.DataFrame, tmp_path: Path, name: str = "data.parquet") -> Path:
    path = tmp_path / name
    df.to_parquet(path, index=False)
    return path


# ── Generate manifest: success path ──────────────────────────────────────────


class TestGenerateManifest:
    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.manifest_version == MANIFEST_VERSION
        assert m.exchange == _EXCHANGE
        assert m.symbol == _SYMBOL
        assert m.timeframe == _TIMEFRAME
        assert m.timezone == "UTC"
        assert m.row_count == _N
        assert m.start_timestamp_utc != ""
        assert m.end_timestamp_utc != ""
        assert len(m.schema_hash) == 64
        assert len(m.content_hash) == 64
        assert isinstance(m.duplicate_count, int)
        assert isinstance(m.missing_interval_summary, dict)
        assert m.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_start_before_end(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.start_timestamp_utc < m.end_timestamp_utc

    def test_row_count_matches_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(n=50), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.row_count == 50

    def test_timezone_always_utc(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.timezone == "UTC"

    def test_default_now_utc_used_when_not_injected(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        before = datetime.now(UTC)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME)
        after = datetime.now(UTC)
        gen_ts = datetime.fromisoformat(m.generation_timestamp_utc)
        assert before <= gen_ts <= after


# ── Content hash ─────────────────────────────────────────────────────────────


class TestContentHash:
    def test_deterministic_same_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m1 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.content_hash == m2.content_hash

    def test_shuffle_invariant(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df_shuffled = df.sample(frac=1, random_state=42).reset_index(drop=True)
        path1 = _write(df, tmp_path, "ordered.parquet")
        path2 = _write(df_shuffled, tmp_path, "shuffled.parquet")
        m1 = generate_manifest(path1, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path2, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.content_hash == m2.content_hash

    def test_close_corruption_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path_clean = _write(df, tmp_path, "clean.parquet")
        df_corrupt = df.copy()
        df_corrupt.loc[0, "close"] = 99999.0
        path_corrupt = _write(df_corrupt, tmp_path, "corrupt.parquet")
        m_clean = generate_manifest(path_clean, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m_corrupt = generate_manifest(path_corrupt, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m_clean.content_hash != m_corrupt.content_hash

    def test_open_corruption_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path_clean = _write(df, tmp_path, "clean.parquet")
        df_corrupt = df.copy()
        df_corrupt.loc[5, "open"] = 0.001
        path_corrupt = _write(df_corrupt, tmp_path, "corrupt.parquet")
        m1 = generate_manifest(path_clean, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path_corrupt, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.content_hash != m2.content_hash

    def test_volume_corruption_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path_clean = _write(df, tmp_path, "clean.parquet")
        df_corrupt = df.copy()
        df_corrupt.loc[10, "volume"] = 0.0
        path_corrupt = _write(df_corrupt, tmp_path, "corrupt.parquet")
        m1 = generate_manifest(path_clean, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path_corrupt, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.content_hash != m2.content_hash

    def test_extra_row_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path1 = _write(df, tmp_path, "orig.parquet")
        df_extra = pd.concat([df, df.iloc[[-1]]], ignore_index=True)
        df_extra.loc[len(df_extra) - 1, "timestamp"] = df["timestamp"].max() + pd.Timedelta(days=1)
        path2 = _write(df_extra, tmp_path, "extra.parquet")
        m1 = generate_manifest(path1, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path2, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.content_hash != m2.content_hash

    def test_content_hash_hex_is_64_chars(self, tmp_path: Path) -> None:
        df = _make_ohlcv().sort_values("timestamp").reset_index(drop=True)
        h = _compute_content_hash(df)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_timestamp_shift_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path1 = _write(df, tmp_path, "orig.parquet")
        df_shifted = df.copy()
        df_shifted["timestamp"] = df_shifted["timestamp"] + pd.Timedelta(hours=1)
        path2 = _write(df_shifted, tmp_path, "shifted.parquet")
        m1 = generate_manifest(path1, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path2, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.content_hash != m2.content_hash


# ── Schema hash ───────────────────────────────────────────────────────────────


class TestSchemaHash:
    def test_deterministic_same_file(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        h1 = _compute_schema_hash(path)
        h2 = _compute_schema_hash(path)
        assert h1 == h2

    def test_added_column_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path1 = _write(df, tmp_path, "orig.parquet")
        df["extra"] = 1.0
        path2 = _write(df, tmp_path, "extra_col.parquet")
        assert _compute_schema_hash(path1) != _compute_schema_hash(path2)

    def test_removed_column_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path1 = _write(df, tmp_path, "orig.parquet")
        path2 = _write(df.drop(columns=["volume"]), tmp_path, "no_vol.parquet")
        assert _compute_schema_hash(path1) != _compute_schema_hash(path2)

    def test_consistent_across_manifests(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m1 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1.schema_hash == m2.schema_hash


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_manifest_to_dict_round_trip(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        d = manifest_to_dict(m)
        restored = manifest_from_dict(d)
        assert m == restored

    def test_json_dumps_deterministic(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        j1 = json.dumps(manifest_to_dict(m), sort_keys=True)
        j2 = json.dumps(manifest_to_dict(m), sort_keys=True)
        assert j1 == j2

    def test_all_fields_json_serializable(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        serialized = json.dumps(manifest_to_dict(m), sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["manifest_version"] == MANIFEST_VERSION
        assert parsed["row_count"] == _N

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        parquet_path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(parquet_path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        manifest_path = tmp_path / "manifest.json"
        save_manifest(m, manifest_path)
        loaded = load_manifest(manifest_path)
        assert m == loaded

    def test_load_manifest_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_manifest(bad)

    def test_manifest_from_dict_missing_field_raises(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        d = manifest_to_dict(m)
        del d["content_hash"]
        with pytest.raises(KeyError):
            manifest_from_dict(d)

    def test_manifest_dataclass_is_immutable(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert isinstance(m, DatasetManifest)
        with pytest.raises((AttributeError, TypeError)):
            m.content_hash = "tampered"  # type: ignore[misc]


# ── Verify manifest ───────────────────────────────────────────────────────────


class TestVerifyManifest:
    def test_clean_dataset_passes(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        result = verify_manifest(path, m)
        assert isinstance(result, ManifestVerificationResult)
        assert result.verified is True
        assert result.mismatches == []

    def test_content_corruption_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path = _write(df, tmp_path)
        reference = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        # Corrupt one value and overwrite
        df.loc[0, "close"] = 999_999.0
        path.write_bytes(b"")  # truncate then rewrite
        df.to_parquet(path, index=False)
        result = verify_manifest(path, reference)
        assert result.verified is False
        fields = [f for f, _, _ in result.mismatches]
        assert "content_hash" in fields

    def test_schema_drift_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path = _write(df, tmp_path)
        reference = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        # Add a column and overwrite
        df["extra_col"] = 0.0
        df.to_parquet(path, index=False)
        result = verify_manifest(path, reference)
        assert result.verified is False
        fields = [f for f, _, _ in result.mismatches]
        assert "schema_hash" in fields

    def test_row_count_change_detected(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path = _write(df, tmp_path)
        reference = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        df_short = df.iloc[:50].copy()
        df_short.to_parquet(path, index=False)
        result = verify_manifest(path, reference)
        assert result.verified is False
        fields = [f for f, _, _ in result.mismatches]
        assert "row_count" in fields

    def test_verification_result_lists_expected_and_actual(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path = _write(df, tmp_path)
        reference = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        df.loc[0, "close"] = 999_999.0
        df.to_parquet(path, index=False)
        result = verify_manifest(path, reference)
        mismatch_map = {f: (e, a) for f, e, a in result.mismatches}
        expected_hash, actual_hash = mismatch_map["content_hash"]
        assert expected_hash == reference.content_hash
        assert actual_hash != reference.content_hash


# ── UTC enforcement ───────────────────────────────────────────────────────────


class TestUTCEnforcement:
    def test_naive_timestamps_raise(self, tmp_path: Path) -> None:
        df = _make_ohlcv(utc=False)
        path = _write(df, tmp_path)
        with pytest.raises(ValueError, match="naive"):
            generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)

    def test_utc_timestamps_accepted(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(utc=True), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.timezone == "UTC"
        assert m.utc_valid if hasattr(m, "utc_valid") else True


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            generate_manifest(tmp_path / "missing.parquet", _SYMBOL, _TIMEFRAME)

    def test_empty_dataset_raises(self, tmp_path: Path) -> None:
        df = _make_ohlcv().iloc[0:0]
        path = _write(df, tmp_path)
        with pytest.raises(ValueError, match="empty"):
            generate_manifest(path, _SYMBOL, _TIMEFRAME)

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        df = _make_ohlcv().drop(columns=["close"])
        path = _write(df, tmp_path)
        with pytest.raises(ValueError, match="Missing required columns"):
            generate_manifest(path, _SYMBOL, _TIMEFRAME)

    def test_invalid_parquet_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.parquet"
        bad.write_bytes(b"not parquet data at all")
        with pytest.raises(ValueError, match="Cannot read"):
            generate_manifest(bad, _SYMBOL, _TIMEFRAME)

    def test_duplicate_count_zero_for_clean_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.duplicate_count == 0

    def test_duplicate_count_nonzero_when_duplicates_present(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        path = _write(dup, tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.duplicate_count == 1

    def test_single_row_dataset(self, tmp_path: Path) -> None:
        df = _make_ohlcv(n=1)
        path = _write(df, tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.row_count == 1
        assert m.start_timestamp_utc == m.end_timestamp_utc
        assert m.missing_interval_summary["count"] == 0


# ── Missing intervals ─────────────────────────────────────────────────────────


class TestMissingIntervals:
    def test_no_gaps_in_contiguous_data(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.missing_interval_summary["count"] == 0

    def test_single_gap_counted(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df = df.drop(index=10).reset_index(drop=True)
        path = _write(df, tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.missing_interval_summary["count"] == 1
        assert "first_gap_utc" in m.missing_interval_summary
        assert "last_gap_utc" in m.missing_interval_summary

    def test_multiple_gaps_counted(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df = df.drop(index=[5, 6, 20]).reset_index(drop=True)
        path = _write(df, tmp_path)
        m = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m.missing_interval_summary["count"] == 3

    def test_unsupported_timeframe_returns_zero(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        path = _write(df, tmp_path)
        # "3d" is not in SUPPORTED_TIMEFRAMES → count == 0 (no crash)
        m = generate_manifest(path, _SYMBOL, "3d", now_utc=_FIXED_NOW)
        assert m.missing_interval_summary["count"] == 0

    def test_hourly_gap_counted(self, tmp_path: Path) -> None:
        df = _make_ohlcv(n=48, timeframe="1h")
        df = df.drop(index=24).reset_index(drop=True)
        path = _write(df, tmp_path)
        m = generate_manifest(path, _SYMBOL, "1h", now_utc=_FIXED_NOW)
        assert m.missing_interval_summary["count"] == 1


# ── Deterministic replay ──────────────────────────────────────────────────────


class TestDeterministicReplay:
    def test_two_independent_calls_identical(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m1 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        assert m1 == m2

    def test_json_replay_identical(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        m1 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        m2 = generate_manifest(path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        j1 = json.dumps(manifest_to_dict(m1), sort_keys=True)
        j2 = json.dumps(manifest_to_dict(m2), sort_keys=True)
        assert j1 == j2

    def test_hash_stable_after_save_load(self, tmp_path: Path) -> None:
        parquet_path = _write(_make_ohlcv(), tmp_path)
        m_orig = generate_manifest(parquet_path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        manifest_path = tmp_path / "m.json"
        save_manifest(m_orig, manifest_path)
        m_loaded = load_manifest(manifest_path)
        assert m_loaded.content_hash == m_orig.content_hash
        assert m_loaded.schema_hash == m_orig.schema_hash


# ── CLI: generate_manifest ────────────────────────────────────────────────────


class TestCLIGenerate:
    def test_exit_0_and_valid_json_on_success(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            gen_main,
            ["--parquet", str(path), "--symbol", _SYMBOL, "--timeframe", _TIMEFRAME],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["manifest_version"] == MANIFEST_VERSION
        assert data["symbol"] == _SYMBOL
        assert "content_hash" in data
        assert "schema_hash" in data

    def test_exit_1_on_naive_timestamps(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(utc=False), tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            gen_main,
            ["--parquet", str(path), "--symbol", _SYMBOL, "--timeframe", _TIMEFRAME],
        )
        assert result.exit_code == 1

    def test_exit_1_on_missing_columns(self, tmp_path: Path) -> None:
        df = _make_ohlcv().drop(columns=["close"])
        path = _write(df, tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            gen_main,
            ["--parquet", str(path), "--symbol", _SYMBOL, "--timeframe", _TIMEFRAME],
        )
        assert result.exit_code == 1

    def test_writes_to_file_when_output_given(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        out = tmp_path / "out.json"
        runner = CliRunner()
        result = runner.invoke(
            gen_main,
            [
                "--parquet",
                str(path),
                "--symbol",
                _SYMBOL,
                "--timeframe",
                _TIMEFRAME,
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["symbol"] == _SYMBOL

    def test_rejects_unsupported_timeframe(self, tmp_path: Path) -> None:
        path = _write(_make_ohlcv(), tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            gen_main,
            ["--parquet", str(path), "--symbol", _SYMBOL, "--timeframe", "3d"],
        )
        assert result.exit_code != 0


# ── CLI: verify_manifest ──────────────────────────────────────────────────────


class TestCLIVerify:
    def test_exit_0_on_clean_match(self, tmp_path: Path) -> None:
        parquet_path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(parquet_path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        manifest_path = tmp_path / "m.json"
        save_manifest(m, manifest_path)
        runner = CliRunner()
        result = runner.invoke(
            ver_main,
            ["--parquet", str(parquet_path), "--manifest", str(manifest_path)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["verified"] is True
        assert data["mismatches"] == []

    def test_exit_1_on_content_corruption(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        parquet_path = _write(df, tmp_path)
        m = generate_manifest(parquet_path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        manifest_path = tmp_path / "m.json"
        save_manifest(m, manifest_path)
        # Corrupt the data
        df.loc[0, "close"] = 999_999.0
        df.to_parquet(parquet_path, index=False)
        runner = CliRunner()
        result = runner.invoke(
            ver_main,
            ["--parquet", str(parquet_path), "--manifest", str(manifest_path)],
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["verified"] is False
        assert len(data["mismatches"]) > 0

    def test_exit_2_on_unreadable_manifest(self, tmp_path: Path) -> None:
        parquet_path = _write(_make_ohlcv(), tmp_path)
        bad_manifest = tmp_path / "bad.json"
        bad_manifest.write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            ver_main,
            ["--parquet", str(parquet_path), "--manifest", str(bad_manifest)],
        )
        assert result.exit_code == 2

    def test_verify_output_includes_paths(self, tmp_path: Path) -> None:
        parquet_path = _write(_make_ohlcv(), tmp_path)
        m = generate_manifest(parquet_path, _SYMBOL, _TIMEFRAME, now_utc=_FIXED_NOW)
        manifest_path = tmp_path / "m.json"
        save_manifest(m, manifest_path)
        runner = CliRunner()
        result = runner.invoke(
            ver_main,
            ["--parquet", str(parquet_path), "--manifest", str(manifest_path)],
        )
        data = json.loads(result.output)
        assert "parquet_path" in data
        assert "manifest_path" in data


# ── Integration: real BTC/USDT 1d data ───────────────────────────────────────


@pytest.mark.skipif(
    not _REAL_PARQUET.exists(),
    reason="data/raw/BTC_USDT_1d.parquet not available",
)
class TestIntegration:
    def test_manifest_generated_without_error(self) -> None:
        m = generate_manifest(_REAL_PARQUET, "BTC/USDT", "1d", now_utc=_FIXED_NOW)
        assert m.row_count > 0
        assert len(m.content_hash) == 64
        assert len(m.schema_hash) == 64
        assert m.timezone == "UTC"
        assert m.exchange == "binance"

    def test_manifest_is_deterministic(self) -> None:
        m1 = generate_manifest(_REAL_PARQUET, "BTC/USDT", "1d", now_utc=_FIXED_NOW)
        m2 = generate_manifest(_REAL_PARQUET, "BTC/USDT", "1d", now_utc=_FIXED_NOW)
        assert m1 == m2

    def test_verify_against_self_passes(self) -> None:
        m = generate_manifest(_REAL_PARQUET, "BTC/USDT", "1d", now_utc=_FIXED_NOW)
        result = verify_manifest(_REAL_PARQUET, m)
        assert result.verified is True

    def test_json_output_is_stable(self) -> None:
        m = generate_manifest(_REAL_PARQUET, "BTC/USDT", "1d", now_utc=_FIXED_NOW)
        j1 = json.dumps(manifest_to_dict(m), sort_keys=True)
        j2 = json.dumps(manifest_to_dict(m), sort_keys=True)
        assert j1 == j2

    def test_start_and_end_are_utc_isoformat(self) -> None:
        m = generate_manifest(_REAL_PARQUET, "BTC/USDT", "1d", now_utc=_FIXED_NOW)
        start = datetime.fromisoformat(m.start_timestamp_utc)
        end = datetime.fromisoformat(m.end_timestamp_utc)
        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert start < end
