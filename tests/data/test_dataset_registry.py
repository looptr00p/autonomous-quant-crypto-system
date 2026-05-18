"""Tests for the deterministic local dataset registry.

All tests use temporary local datasets only.  No live network calls.

Coverage:
- valid registry generation (single entry, multiple entries)
- deterministic ordering by (symbol, timeframe, dataset_path)
- deterministic scan across multiple invocations
- orphan manifest detection
- missing manifest detection
- duplicate dataset identity detection
- manifest mismatch detection (verify_manifests=True)
- malformed manifest JSON rejection
- timezone-naive parquet metadata warning
- JSON serialization round-trip (registry_to_dict / registry_from_dict)
- save_registry / load_registry round-trip
- load_registry: invalid JSON raises ValueError
- registry_from_dict: missing field raises KeyError
- registry dataclass is immutable
- empty directory → empty registry
- registry total_datasets matches entry count
- CLI build: exit 0 on clean directory
- CLI build: exit 1 when issues exist
- CLI build: writes to output-json when specified
- CLI validate: exit 0 on clean registry
- CLI validate: exit 1 when issues present
- CLI validate: exit 2 on malformed registry file
- issues list is populated for each anomaly type
- duplicate_identities groups correct paths
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from build_dataset_registry import main as build_main
from click.testing import CliRunner
from validate_dataset_registry import main as validate_main

from aqcs.data.dataset_registry import (
    REGISTRY_VERSION,
    DatasetRegistry,
    load_registry,
    registry_from_dict,
    registry_to_dict,
    save_registry,
    scan_directory,
)
from aqcs.data.manifest import generate_manifest, save_manifest

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_TIMEFRAME = "1h"
_N = 48  # bars per test parquet


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv_df(
    symbol: str,
    timeframe: str = _TIMEFRAME,
    n: int = _N,
    *,
    utc: bool = True,
    base_price: float = 45_000.0,
) -> pd.DataFrame:
    """Return a minimal schema-valid OHLCV DataFrame."""
    tz = "UTC" if utc else None
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz=tz)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": np.full(n, base_price),
            "high": np.full(n, base_price + 100),
            "low": np.full(n, base_price - 100),
            "close": np.full(n, base_price + 50),
            "volume": np.full(n, 1_000.0),
            "symbol": symbol,
            "timeframe": timeframe,
            "exchange": "binance",
        }
    )


def _write_parquet(
    tmp_path: Path,
    safe_symbol: str,
    timeframe: str = _TIMEFRAME,
    **df_kwargs: object,
) -> Path:
    """Write a parquet with AQCS naming convention and return its path."""
    ccxt_symbol = safe_symbol.replace("_", "/")
    df = _make_ohlcv_df(ccxt_symbol, timeframe, **df_kwargs)  # type: ignore[arg-type]
    path = tmp_path / f"{safe_symbol}_{timeframe}.parquet"
    df.to_parquet(path, index=False)
    return path


def _write_manifest(parquet_path: Path, ccxt_symbol: str, timeframe: str = _TIMEFRAME) -> Path:
    """Generate and save a manifest for a parquet, return the manifest path."""
    manifest = generate_manifest(parquet_path, ccxt_symbol, timeframe, now_utc=_FIXED_NOW)
    manifest_path = parquet_path.parent / f"{parquet_path.stem}_manifest.json"
    save_manifest(manifest, manifest_path)
    return manifest_path


def _setup_clean_dataset(
    tmp_path: Path,
    safe_symbol: str = "BTC_USDT",
    timeframe: str = _TIMEFRAME,
    **df_kwargs: object,
) -> tuple[Path, Path]:
    """Write parquet + manifest pair; return (parquet_path, manifest_path)."""
    pq = _write_parquet(tmp_path, safe_symbol, timeframe, **df_kwargs)
    ccxt = safe_symbol.replace("_", "/")
    mf = _write_manifest(pq, ccxt, timeframe)
    return pq, mf


# ── Registry generation ───────────────────────────────────────────────────────


class TestRegistryGeneration:
    def test_empty_directory_produces_empty_registry(self, tmp_path: Path) -> None:
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.total_datasets == 0
        assert registry.entries == ()
        assert registry.orphan_manifests == ()
        assert registry.issues == ()

    def test_single_valid_entry(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.total_datasets == 1
        assert len(registry.entries) == 1
        e = registry.entries[0]
        assert e.has_manifest is True
        assert e.symbol == "BTC/USDT"
        assert e.timeframe == _TIMEFRAME
        assert e.exchange == "binance"
        assert e.row_count == _N
        assert len(e.content_hash) == 64
        assert len(e.schema_hash) == 64

    def test_multiple_valid_entries(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        _setup_clean_dataset(tmp_path, "ETH_USDT", base_price=3_000.0)
        _setup_clean_dataset(tmp_path, "SOL_USDT", base_price=100.0)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.total_datasets == 3
        assert len(registry.entries) == 3

    def test_total_datasets_matches_entry_count(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        _setup_clean_dataset(tmp_path, "ETH_USDT", base_price=3_000.0)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.total_datasets == len(registry.entries)

    def test_registry_version_is_current(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.registry_version == REGISTRY_VERSION

    def test_generation_timestamp_uses_injection(self, tmp_path: Path) -> None:
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_data_dir_is_recorded(self, tmp_path: Path) -> None:
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.data_dir == str(tmp_path)

    def test_dataset_path_is_relative_to_data_dir(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        e = registry.entries[0]
        assert not Path(e.dataset_path).is_absolute()
        assert (tmp_path / e.dataset_path).exists()


# ── Deterministic ordering ────────────────────────────────────────────────────


class TestDeterministicOrdering:
    def test_entries_sorted_by_symbol_then_timeframe(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "SOL_USDT", base_price=100.0)
        _setup_clean_dataset(tmp_path, "BTC_USDT", base_price=45_000.0)
        _setup_clean_dataset(tmp_path, "ETH_USDT", base_price=3_000.0)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        symbols = [e.symbol for e in registry.entries]
        assert symbols == sorted(symbols)

    def test_two_scans_produce_identical_registry(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        _setup_clean_dataset(tmp_path, "ETH_USDT", base_price=3_000.0)
        r1 = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        r2 = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert r1 == r2

    def test_json_is_deterministic(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        r1 = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        r2 = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        j1 = json.dumps(registry_to_dict(r1), sort_keys=True)
        j2 = json.dumps(registry_to_dict(r2), sort_keys=True)
        assert j1 == j2

    def test_orphan_manifests_are_sorted(self, tmp_path: Path) -> None:
        # Create orphan manifests without parquets
        (tmp_path / "ZZZ_manifest.json").write_text(json.dumps({"dummy": 1}), encoding="utf-8")
        (tmp_path / "AAA_manifest.json").write_text(json.dumps({"dummy": 1}), encoding="utf-8")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert list(registry.orphan_manifests) == sorted(registry.orphan_manifests)


# ── Missing manifest detection ────────────────────────────────────────────────


class TestMissingManifest:
    def test_missing_manifest_issue_recorded(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.total_datasets == 1
        assert any("Missing manifest" in issue for issue in registry.issues)

    def test_entry_has_manifest_false(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        e = registry.entries[0]
        assert e.has_manifest is False
        assert e.manifest_path is None
        assert e.content_hash == ""

    def test_entry_still_has_parquet_metadata(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        e = registry.entries[0]
        assert e.symbol == "BTC/USDT"
        assert e.row_count == _N
        assert e.start_timestamp_utc != ""
        assert e.end_timestamp_utc != ""


# ── Orphan manifest detection ─────────────────────────────────────────────────


class TestOrphanManifest:
    def test_orphan_manifest_detected(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        # Create an orphan manifest with no matching parquet
        orphan = tmp_path / "ETH_USDT_1h_manifest.json"
        orphan.write_text(json.dumps({"dummy": True}), encoding="utf-8")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert len(registry.orphan_manifests) == 1
        assert any("Orphan manifest" in issue for issue in registry.issues)

    def test_orphan_manifest_path_is_relative(self, tmp_path: Path) -> None:
        orphan = tmp_path / "ZZZ_1h_manifest.json"
        orphan.write_text("{}", encoding="utf-8")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert len(registry.orphan_manifests) == 1
        assert not Path(registry.orphan_manifests[0]).is_absolute()

    def test_matched_manifest_not_in_orphans(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.orphan_manifests == ()


# ── Duplicate identity detection ──────────────────────────────────────────────


class TestDuplicateIdentity:
    def test_identical_data_detected_as_duplicate(self, tmp_path: Path) -> None:
        # Two parquets with identical OHLCV values → same content_hash
        pq1 = _write_parquet(tmp_path, "BTC_USDT")
        _write_manifest(pq1, "BTC/USDT")

        # Second parquet: different filename but same data
        pq2 = tmp_path / "BTC_USDT_1h_copy.parquet"
        df = _make_ohlcv_df("BTC/USDT")
        df.to_parquet(pq2, index=False)
        mf2_path = tmp_path / "BTC_USDT_1h_copy_manifest.json"
        mf2 = generate_manifest(pq2, "BTC/USDT", _TIMEFRAME, now_utc=_FIXED_NOW)
        save_manifest(mf2, mf2_path)

        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert len(registry.duplicate_identities) == 1
        dup_group = registry.duplicate_identities[0]
        assert len(dup_group) == 2
        assert any("Duplicate" in issue for issue in registry.issues)

    def test_distinct_data_not_flagged(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT", base_price=45_000.0)
        _setup_clean_dataset(tmp_path, "ETH_USDT", base_price=3_000.0)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.duplicate_identities == ()

    def test_entries_without_manifest_not_flagged_as_duplicates(self, tmp_path: Path) -> None:
        # Two parquets with same data but no manifests: content_hash is ""
        _write_parquet(tmp_path, "BTC_USDT")
        _write_parquet(tmp_path, "BTC_USDT_copy")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        # Empty content_hash is excluded from duplicate detection
        assert registry.duplicate_identities == ()


# ── Manifest verification ─────────────────────────────────────────────────────


class TestManifestVerification:
    def test_verify_passes_on_clean_data(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, verify_manifests=True, now_utc=_FIXED_NOW)
        assert registry.entries[0].manifest_verified is True
        assert not any("mismatch" in i.lower() for i in registry.issues)

    def test_verify_detects_corrupted_parquet(self, tmp_path: Path) -> None:
        pq, _ = _setup_clean_dataset(tmp_path, "BTC_USDT")
        # Corrupt the parquet AFTER manifest generation
        pq.write_bytes(b"corrupted parquet bytes")
        registry = scan_directory(tmp_path, verify_manifests=True, now_utc=_FIXED_NOW)
        assert registry.entries[0].manifest_verified is False
        assert any("mismatch" in i.lower() or "failed" in i.lower() for i in registry.issues)

    def test_verify_false_skips_verification(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, verify_manifests=False, now_utc=_FIXED_NOW)
        # verify_manifests=False → manifest_verified is always False (not checked)
        assert registry.entries[0].manifest_verified is False
        # But no "mismatch" issues
        assert not any("mismatch" in i.lower() for i in registry.issues)


# ── Malformed manifest ────────────────────────────────────────────────────────


class TestMalformedManifest:
    def test_invalid_json_recorded_as_issue(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")
        bad_manifest = tmp_path / "BTC_USDT_1h_manifest.json"
        bad_manifest.write_text("not valid json", encoding="utf-8")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert any("Malformed" in issue for issue in registry.issues)

    def test_missing_field_in_manifest_recorded(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")
        incomplete = tmp_path / "BTC_USDT_1h_manifest.json"
        # Write a JSON that is valid but missing required manifest fields
        incomplete.write_text(
            json.dumps({"manifest_version": "1", "symbol": "BTC/USDT"}),
            encoding="utf-8",
        )
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert any("Malformed" in issue for issue in registry.issues)


# ── Timezone validation ───────────────────────────────────────────────────────


class TestTimezoneValidation:
    def test_naive_timestamps_recorded_as_issue(self, tmp_path: Path) -> None:
        df = _make_ohlcv_df("BTC/USDT", utc=False)
        pq = tmp_path / "BTC_USDT_1h.parquet"
        df.to_parquet(pq, index=False)
        # No manifest — will try to read metadata from parquet
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert any("naive" in issue.lower() for issue in registry.issues)

    def test_utc_timestamps_no_timezone_issue(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert not any("naive" in issue.lower() for issue in registry.issues)


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_registry_to_dict_round_trip(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        r = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        d = registry_to_dict(r)
        restored = registry_from_dict(d)
        assert r == restored

    def test_json_serializable(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        r = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        serialized = json.dumps(registry_to_dict(r), sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["registry_version"] == REGISTRY_VERSION

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup_clean_dataset(data_dir, "BTC_USDT")
        r = scan_directory(data_dir, now_utc=_FIXED_NOW)
        out = tmp_path / "registry.json"
        save_registry(r, out)
        loaded = load_registry(out)
        assert r == loaded

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_registry(bad)

    def test_from_dict_missing_field_raises(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        r = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        d = registry_to_dict(r)
        del d["registry_version"]
        with pytest.raises(KeyError):
            registry_from_dict(d)

    def test_registry_is_immutable(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        r = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert isinstance(r, DatasetRegistry)
        with pytest.raises((AttributeError, TypeError)):
            r.total_datasets = 99  # type: ignore[misc]

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup_clean_dataset(data_dir, "BTC_USDT")
        r = scan_directory(data_dir, now_utc=_FIXED_NOW)
        out = tmp_path / "nested" / "deep" / "registry.json"
        save_registry(r, out)
        assert out.exists()


# ── CLI build_dataset_registry ────────────────────────────────────────────────


class TestCLIBuild:
    def test_exit_0_on_clean_directory(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", str(tmp_path)])
        assert result.exit_code == 0

    def test_exit_1_when_issues_exist(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")  # no manifest → issue
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", str(tmp_path)])
        assert result.exit_code == 1

    def test_writes_registry_json(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup_clean_dataset(data_dir, "BTC_USDT")
        out = tmp_path / "reg.json"
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--data-dir", str(data_dir), "--output-json", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "registry_version" in data

    def test_stdout_contains_json_summary(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", str(tmp_path)])
        # Extract JSON from potentially mixed output
        json_text = result.output[result.output.index("{") :]
        summary = json.loads(json_text)
        assert "total_datasets" in summary
        assert summary["total_datasets"] == 1

    def test_rejects_nonexistent_data_dir(self) -> None:
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", "/nonexistent/path/xyz"])
        assert result.exit_code != 0


# ── CLI validate_dataset_registry ────────────────────────────────────────────


class TestCLIValidate:
    def _build_registry_file(self, data_dir: Path, output_path: Path) -> None:
        from aqcs.data.dataset_registry import save_registry, scan_directory

        r = scan_directory(data_dir, now_utc=_FIXED_NOW)
        save_registry(r, output_path)

    def test_exit_0_on_clean_registry(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup_clean_dataset(data_dir, "BTC_USDT")
        reg_path = tmp_path / "reg.json"
        self._build_registry_file(data_dir, reg_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--registry-json", str(reg_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["clean"] is True

    def test_exit_1_when_issues_in_registry(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_parquet(data_dir, "BTC_USDT")  # no manifest
        reg_path = tmp_path / "reg.json"
        self._build_registry_file(data_dir, reg_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--registry-json", str(reg_path)])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["clean"] is False
        assert data["issues_count"] > 0

    def test_exit_2_on_malformed_registry(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--registry-json", str(bad)])
        assert result.exit_code == 2

    def test_report_contains_required_fields(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup_clean_dataset(data_dir, "BTC_USDT")
        reg_path = tmp_path / "reg.json"
        self._build_registry_file(data_dir, reg_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--registry-json", str(reg_path)])
        data = json.loads(result.output)
        required_keys = {
            "registry_version",
            "total_datasets",
            "entries_with_manifest",
            "entries_missing_manifest",
            "orphan_manifests_count",
            "duplicate_identity_groups",
            "issues_count",
            "clean",
        }
        assert required_keys.issubset(data.keys())


# ── Reproducible replay inventory ─────────────────────────────────────────────


class TestReplayInventory:
    def test_registry_identifies_all_datasets(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        _setup_clean_dataset(tmp_path, "ETH_USDT", base_price=3_000.0)
        _setup_clean_dataset(tmp_path, "SOL_USDT", base_price=100.0)
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        symbols = {e.symbol for e in registry.entries}
        assert symbols == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}

    def test_content_hashes_are_stable(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        r1 = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        r2 = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert r1.entries[0].content_hash == r2.entries[0].content_hash

    def test_start_and_end_timestamps_are_utc_isoformat(self, tmp_path: Path) -> None:
        _setup_clean_dataset(tmp_path, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        e = registry.entries[0]
        start = datetime.fromisoformat(e.start_timestamp_utc)
        end = datetime.fromisoformat(e.end_timestamp_utc)
        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert start < end

    def test_nested_directory_parquets_discovered(self, tmp_path: Path) -> None:
        sub = tmp_path / "btc"
        sub.mkdir()
        _setup_clean_dataset(sub, "BTC_USDT")
        registry = scan_directory(tmp_path, now_utc=_FIXED_NOW)
        assert registry.total_datasets == 1
        assert "btc" in registry.entries[0].dataset_path
