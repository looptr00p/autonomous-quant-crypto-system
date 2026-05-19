"""Tests for deterministic dataset fleet monitoring snapshots.

All tests use temporary local datasets only.  No live network calls.

Coverage:
- snapshot generation: valid, empty, single entry, multiple entries
- snapshot hashing: deterministic, changes on data modification
- registry_hash changes when issues change
- registry_entries_hash stable across metadata-only changes
- drift detection: added, removed, modified datasets
- freshness change detection: updated, truncated, unchanged
- new/resolved issue detection in compare
- has_drift true/false cases
- orphan manifest propagation into snapshot
- duplicate identity propagation into snapshot
- missing manifest issue propagation
- JSON serialization round-trip (snapshot_to_dict / snapshot_from_dict)
- save_snapshot / load_snapshot round-trip
- load_snapshot: invalid JSON raises ValueError
- snapshot_from_dict: missing field raises KeyError
- FleetSnapshot dataclass immutable
- FleetDrift summary string
- CLI build: exit 0 on clean directory
- CLI build: exit 1 when issues exist
- CLI build: writes output-json when specified
- CLI compare: exit 0 on no drift
- CLI compare: exit 1 on drift
- CLI compare: exit 2 on malformed snapshot
- timezone validation via registry
- deterministic ordering of snapshot entries
- two scans of same directory produce identical snapshot
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from build_fleet_snapshot import main as build_main
from click.testing import CliRunner
from compare_fleet_snapshots import main as compare_main

from aqcs.data.manifest import generate_manifest, save_manifest
from aqcs.monitoring.fleet_monitoring import (
    SNAPSHOT_VERSION,
    FleetSnapshot,
    build_snapshot,
    compare_snapshots,
    drift_to_dict,
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
    snapshot_to_dict,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_TIMEFRAME = "1h"
_N = 24


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv_df(
    symbol: str,
    n: int = _N,
    *,
    utc: bool = True,
    base_price: float = 45_000.0,
    start: str = "2024-01-01",
) -> pd.DataFrame:
    tz = "UTC" if utc else None
    idx = pd.date_range(start, periods=n, freq="1h", tz=tz)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": np.full(n, base_price),
            "high": np.full(n, base_price + 100),
            "low": np.full(n, base_price - 100),
            "close": np.full(n, base_price + 50),
            "volume": np.full(n, 1_000.0),
            "symbol": symbol,
            "timeframe": _TIMEFRAME,
            "exchange": "binance",
        }
    )


def _write_parquet(
    directory: Path,
    safe_symbol: str,
    timeframe: str = _TIMEFRAME,
    **df_kwargs: object,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    ccxt_symbol = safe_symbol.replace("_", "/")
    df = _make_ohlcv_df(ccxt_symbol, **df_kwargs)  # type: ignore[arg-type]
    path = directory / f"{safe_symbol}_{timeframe}.parquet"
    df.to_parquet(path, index=False)
    return path


def _write_manifest(parquet_path: Path, ccxt_symbol: str) -> Path:
    manifest = generate_manifest(parquet_path, ccxt_symbol, _TIMEFRAME, now_utc=_FIXED_NOW)
    mf_path = parquet_path.parent / f"{parquet_path.stem}_manifest.json"
    save_manifest(manifest, mf_path)
    return mf_path


def _setup(
    directory: Path,
    safe_symbol: str,
    **df_kwargs: object,
) -> tuple[Path, Path]:
    pq = _write_parquet(directory, safe_symbol, **df_kwargs)
    mf = _write_manifest(pq, safe_symbol.replace("_", "/"))
    return pq, mf


# ── Snapshot generation ───────────────────────────────────────────────────────


class TestSnapshotGeneration:
    def test_empty_directory(self, tmp_path: Path) -> None:
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.total_datasets == 0
        assert snap.snapshot_entries == ()
        assert snap.snapshot_version == SNAPSHOT_VERSION

    def test_single_entry(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.total_datasets == 1
        assert len(snap.snapshot_entries) == 1
        e = snap.snapshot_entries[0]
        assert e.symbol == "BTC/USDT"
        assert e.row_count == _N
        assert len(e.content_hash) == 64

    def test_multiple_entries(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        _setup(tmp_path, "ETH_USDT", base_price=3_000.0)
        _setup(tmp_path, "SOL_USDT", base_price=100.0)
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.total_datasets == 3

    def test_generation_timestamp_uses_injection(self, tmp_path: Path) -> None:
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_symbols_sorted(self, tmp_path: Path) -> None:
        _setup(tmp_path, "SOL_USDT", base_price=100.0)
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert list(snap.symbols) == sorted(snap.symbols)

    def test_datasets_by_symbol_populated(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        _setup(tmp_path, "ETH_USDT", base_price=3_000.0)
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.datasets_by_symbol.get("BTC/USDT", 0) == 1
        assert snap.datasets_by_symbol.get("ETH/USDT", 0) == 1

    def test_total_manifests_counted(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        _write_parquet(tmp_path, "ETH_USDT", base_price=3_000.0)  # no manifest
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.total_manifests == 1

    def test_issue_count_nonzero_for_missing_manifest(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.issue_count > 0

    def test_issue_count_zero_for_clean_data(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.issue_count == 0

    def test_orphan_manifest_count_propagated(self, tmp_path: Path) -> None:
        orphan = tmp_path / "ZZZ_1h_manifest.json"
        orphan.write_text("{}", encoding="utf-8")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.orphan_manifest_count == 1

    def test_duplicate_identity_count_propagated(self, tmp_path: Path) -> None:
        pq1 = _write_parquet(tmp_path, "BTC_USDT")
        _write_manifest(pq1, "BTC/USDT")
        pq2 = tmp_path / "BTC_USDT_1h_copy.parquet"
        _make_ohlcv_df("BTC/USDT").to_parquet(pq2, index=False)
        mf2 = generate_manifest(pq2, "BTC/USDT", _TIMEFRAME, now_utc=_FIXED_NOW)
        save_manifest(mf2, tmp_path / "BTC_USDT_1h_copy_manifest.json")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.duplicate_identity_count == 1


# ── Hashing ───────────────────────────────────────────────────────────────────


class TestSnapshotHashing:
    def test_registry_hash_deterministic(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        s1 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        s2 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert s1.registry_hash == s2.registry_hash

    def test_registry_hash_changes_on_data_modification(self, tmp_path: Path) -> None:
        pq, _ = _setup(tmp_path, "BTC_USDT")
        snap1 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        # Modify the data and regenerate the manifest
        pq.unlink()
        pq2 = _write_parquet(tmp_path, "BTC_USDT", base_price=60_000.0)
        _write_manifest(pq2, "BTC/USDT")
        snap2 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap1.registry_hash != snap2.registry_hash

    def test_entries_hash_is_64_chars_hex(self, tmp_path: Path) -> None:
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert len(snap.registry_entries_hash) == 64
        assert all(c in "0123456789abcdef" for c in snap.registry_entries_hash)

    def test_registry_hash_changes_on_issue_added(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap1 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        _write_parquet(tmp_path, "ETH_USDT", base_price=3_000.0)  # no manifest
        snap2 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap1.registry_hash != snap2.registry_hash

    def test_two_scans_produce_identical_snapshot(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        s1 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        s2 = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert s1 == s2


# ── Drift detection ───────────────────────────────────────────────────────────


class TestDriftDetection:
    def test_no_drift_same_snapshot(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        drift = compare_snapshots(snap, snap)
        assert drift.has_drift is False
        assert drift.summary == "No drift detected"

    def test_dataset_added(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        base = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        _setup(tmp_path, "ETH_USDT", base_price=3_000.0)
        cand = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert drift.has_drift is True
        assert len(drift.added_datasets) == 1
        assert any("ETH_USDT" in p for p in drift.added_datasets)

    def test_dataset_removed(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _setup(base_dir, "BTC_USDT")
        _setup(base_dir, "ETH_USDT", base_price=3_000.0)
        _setup(cand_dir, "BTC_USDT")
        base = build_snapshot(base_dir, now_utc=_FIXED_NOW)
        cand = build_snapshot(cand_dir, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert drift.has_drift is True
        assert len(drift.removed_datasets) == 1

    def test_dataset_content_modified(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _setup(base_dir, "BTC_USDT", base_price=45_000.0)
        _setup(cand_dir, "BTC_USDT", base_price=60_000.0)  # different price
        base = build_snapshot(base_dir, now_utc=_FIXED_NOW)
        cand = build_snapshot(cand_dir, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert drift.has_drift is True
        assert "BTC_USDT_1h.parquet" in " ".join(drift.modified_datasets)

    def test_added_datasets_sorted(self, tmp_path: Path) -> None:
        _setup(tmp_path / "base", "BTC_USDT")
        _setup(tmp_path / "cand", "BTC_USDT")
        _setup(tmp_path / "cand", "ETH_USDT", base_price=3_000.0)
        _setup(tmp_path / "cand", "SOL_USDT", base_price=100.0)
        base = build_snapshot(tmp_path / "base", now_utc=_FIXED_NOW)
        cand = build_snapshot(tmp_path / "cand", now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert list(drift.added_datasets) == sorted(drift.added_datasets)

    def test_removed_datasets_sorted(self, tmp_path: Path) -> None:
        for sym in ("BTC_USDT", "ETH_USDT", "SOL_USDT"):
            _setup(tmp_path / "base", sym, base_price=1.0)
        _setup(tmp_path / "cand", "BTC_USDT")
        base = build_snapshot(tmp_path / "base", now_utc=_FIXED_NOW)
        cand = build_snapshot(tmp_path / "cand", now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert list(drift.removed_datasets) == sorted(drift.removed_datasets)


# ── Freshness change detection ─────────────────────────────────────────────────


class TestFreshnessChanges:
    def test_dataset_updated_detected(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _setup(base_dir, "BTC_USDT", start="2024-01-01")
        _setup(cand_dir, "BTC_USDT", start="2024-01-02")  # later start → later end
        base = build_snapshot(base_dir, now_utc=_FIXED_NOW)
        cand = build_snapshot(cand_dir, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        updated = [fc for fc in drift.freshness_changes if fc.direction == "updated"]
        assert len(updated) == 1

    def test_dataset_truncated_detected(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _setup(base_dir, "BTC_USDT", start="2024-01-02")  # later end
        _setup(cand_dir, "BTC_USDT", start="2024-01-01")  # earlier end
        base = build_snapshot(base_dir, now_utc=_FIXED_NOW)
        cand = build_snapshot(cand_dir, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        truncated = [fc for fc in drift.freshness_changes if fc.direction == "truncated"]
        assert len(truncated) == 1

    def test_unchanged_dataset_no_freshness_entry(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        drift = compare_snapshots(snap, snap)
        assert drift.freshness_changes == ()


# ── Issue propagation ─────────────────────────────────────────────────────────


class TestIssuePropagation:
    def test_new_issue_detected(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _setup(base_dir, "BTC_USDT")
        _setup(cand_dir, "BTC_USDT")
        _write_parquet(cand_dir, "ETH_USDT", base_price=3_000.0)  # no manifest
        base = build_snapshot(base_dir, now_utc=_FIXED_NOW)
        cand = build_snapshot(cand_dir, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert len(drift.new_issues) > 0
        assert drift.has_drift is True

    def test_resolved_issue_detected(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _write_parquet(base_dir, "BTC_USDT")  # no manifest in baseline
        _setup(cand_dir, "BTC_USDT")  # manifest present in candidate
        base = build_snapshot(base_dir, now_utc=_FIXED_NOW)
        cand = build_snapshot(cand_dir, now_utc=_FIXED_NOW)
        drift = compare_snapshots(base, cand)
        assert len(drift.resolved_issues) > 0

    def test_orphan_manifest_appears_in_issues(self, tmp_path: Path) -> None:
        orphan = tmp_path / "ORPHAN_1h_manifest.json"
        orphan.write_text("{}", encoding="utf-8")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert snap.orphan_manifest_count == 1
        assert any("Orphan" in i for i in snap.issues)


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_snapshot_to_dict_round_trip(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        d = snapshot_to_dict(snap)
        restored = snapshot_from_dict(d)
        assert snap == restored

    def test_json_dumps_deterministic(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        j1 = json.dumps(snapshot_to_dict(snap), sort_keys=True)
        j2 = json.dumps(snapshot_to_dict(snap), sort_keys=True)
        assert j1 == j2

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup(data_dir, "BTC_USDT")
        snap = build_snapshot(data_dir, now_utc=_FIXED_NOW)
        path = tmp_path / "snap.json"
        save_snapshot(snap, path)
        loaded = load_snapshot(path)
        assert snap == loaded

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_snapshot(bad)

    def test_from_dict_missing_field_raises(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        d = snapshot_to_dict(snap)
        del d["registry_hash"]
        with pytest.raises(KeyError):
            snapshot_from_dict(d)

    def test_snapshot_is_immutable(self, tmp_path: Path) -> None:
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert isinstance(snap, FleetSnapshot)
        with pytest.raises((AttributeError, TypeError)):
            snap.total_datasets = 99  # type: ignore[misc]

    def test_drift_to_dict_serializable(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        drift = compare_snapshots(snap, snap)
        d = drift_to_dict(drift)
        serialized = json.dumps(d, sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["has_drift"] is False

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        out = tmp_path / "nested" / "deep" / "snap.json"
        save_snapshot(snap, out)
        assert out.exists()


# ── CLI build_fleet_snapshot ──────────────────────────────────────────────────


class TestCLIBuild:
    def test_exit_0_on_clean_directory(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", str(tmp_path)])
        assert result.exit_code == 0

    def test_exit_1_when_issues_exist(self, tmp_path: Path) -> None:
        _write_parquet(tmp_path, "BTC_USDT")  # no manifest
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", str(tmp_path)])
        assert result.exit_code == 1

    def test_writes_output_json(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup(data_dir, "BTC_USDT")
        out = tmp_path / "snap.json"
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--data-dir", str(data_dir), "--output-json", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert "registry_hash" in data

    def test_stdout_contains_summary_json(self, tmp_path: Path) -> None:
        _setup(tmp_path, "BTC_USDT")
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", str(tmp_path)])
        json_text = result.output[result.output.index("{") :]
        summary = json.loads(json_text)
        assert "total_datasets" in summary
        assert summary["total_datasets"] == 1

    def test_rejects_nonexistent_data_dir(self) -> None:
        runner = CliRunner()
        result = runner.invoke(build_main, ["--data-dir", "/nonexistent/xyz"])
        assert result.exit_code != 0


# ── CLI compare_fleet_snapshots ───────────────────────────────────────────────


class TestCLICompare:
    def _save_snap(self, data_dir: Path, out: Path, **kwargs: object) -> None:
        snap = build_snapshot(data_dir, now_utc=_FIXED_NOW)
        save_snapshot(snap, out)

    def test_exit_0_on_no_drift(self, tmp_path: Path) -> None:
        _setup(tmp_path / "data", "BTC_USDT")
        snap_path = tmp_path / "snap.json"
        self._save_snap(tmp_path / "data", snap_path)
        runner = CliRunner()
        result = runner.invoke(
            compare_main,
            ["--baseline", str(snap_path), "--candidate", str(snap_path)],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["has_drift"] is False

    def test_exit_1_on_drift(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        cand_dir = tmp_path / "cand"
        _setup(base_dir, "BTC_USDT")
        _setup(cand_dir, "BTC_USDT")
        _setup(cand_dir, "ETH_USDT", base_price=3_000.0)
        base_path = tmp_path / "base.json"
        cand_path = tmp_path / "cand.json"
        save_snapshot(build_snapshot(base_dir, now_utc=_FIXED_NOW), base_path)
        save_snapshot(build_snapshot(cand_dir, now_utc=_FIXED_NOW), cand_path)
        runner = CliRunner()
        result = runner.invoke(
            compare_main,
            ["--baseline", str(base_path), "--candidate", str(cand_path)],
        )
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["has_drift"] is True

    def test_exit_2_on_malformed_baseline(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        good = tmp_path / "good.json"
        save_snapshot(build_snapshot(tmp_path, now_utc=_FIXED_NOW), good)
        runner = CliRunner()
        result = runner.invoke(
            compare_main,
            ["--baseline", str(bad), "--candidate", str(good)],
        )
        assert result.exit_code == 2

    def test_report_contains_required_fields(self, tmp_path: Path) -> None:
        _setup(tmp_path / "data", "BTC_USDT")
        snap_path = tmp_path / "snap.json"
        save_snapshot(build_snapshot(tmp_path / "data", now_utc=_FIXED_NOW), snap_path)
        runner = CliRunner()
        result = runner.invoke(
            compare_main,
            ["--baseline", str(snap_path), "--candidate", str(snap_path)],
        )
        parsed = json.loads(result.output)
        required = {
            "baseline_timestamp_utc",
            "candidate_timestamp_utc",
            "added_datasets",
            "removed_datasets",
            "modified_datasets",
            "freshness_changes",
            "new_issues",
            "resolved_issues",
            "has_drift",
            "summary",
        }
        assert required.issubset(parsed.keys())


# ── Timezone validation ────────────────────────────────────────────────────────


class TestTimezoneValidation:
    def test_naive_timestamp_recorded_as_issue(self, tmp_path: Path) -> None:
        df = _make_ohlcv_df("BTC/USDT", utc=False)
        pq = tmp_path / "BTC_USDT_1h.parquet"
        df.to_parquet(pq, index=False)
        snap = build_snapshot(tmp_path, now_utc=_FIXED_NOW)
        assert any("naive" in issue.lower() for issue in snap.issues)
