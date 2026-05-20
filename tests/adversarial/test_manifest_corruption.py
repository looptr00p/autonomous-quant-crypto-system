"""Adversarial: manifest corruption and orphan-artifact scenarios.

Directly mutates saved manifests and dataset state to verify that:
1. content_hash mutation is detected by verify_manifest.
2. schema_hash mutation is detected by verify_manifest.
3. Orphan manifests (no matching parquet) are reported by scan_directory.
4. Missing manifests (parquet with no manifest) are reported by scan_directory.
5. Lineage fields (row_count, start/end timestamps) that diverge from the
   actual parquet are reported as mismatches.
6. Partial corruption (multiple fields corrupted) is fully enumerated.
7. After data mutation, a freshly generated manifest has different hashes.

Corruption classes covered:
- content_hash mutation
- schema_hash mutation
- orphan manifest artifact
- missing manifest artifact
- lineage inconsistency (row_count, timestamp range)
- partial (multi-field) corruption
- manifest drift after data change
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from aqcs.data.dataset_registry import scan_directory
from aqcs.data.manifest import (
    DatasetManifest,
    generate_manifest,
    load_manifest,
    manifest_from_dict,
    manifest_to_dict,
    save_manifest,
    verify_manifest,
)

from .conftest import FIXED_NOW

_SYMBOL = "BTC/USDT"
_EXCHANGE = "binance"
_TIMEFRAME = "1d"
_N = 30


# ── Factory helpers ──────────────────────────────────────────────────────────


def _clean_df(n: int = _N) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    close = np.linspace(45_000.0, 50_000.0, n)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": np.linspace(100.0, 200.0, n),
            "symbol": _SYMBOL,
            "timeframe": _TIMEFRAME,
            "exchange": _EXCHANGE,
        }
    )


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    df.to_parquet(path, index=False)


def _write_parquet_and_manifest(
    tmp_path: Path,
    stem: str = "BTC_USDT_1d",
    df: pd.DataFrame | None = None,
) -> tuple[Path, Path, DatasetManifest]:
    df = df if df is not None else _clean_df()
    pq_path = tmp_path / f"{stem}.parquet"
    mf_path = tmp_path / f"{stem}_manifest.json"
    _write_parquet(df, pq_path)
    manifest = generate_manifest(pq_path, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
    save_manifest(manifest, mf_path)
    return pq_path, mf_path, manifest


# ── Content hash mutation ─────────────────────────────────────────────────────


class TestContentHashMutation:
    def test_mutated_content_hash_detected_by_verify(self, tmp_path: Path) -> None:
        """Replacing content_hash in the manifest causes verify_manifest to fail."""
        pq_path, mf_path, original = _write_parquet_and_manifest(tmp_path)

        # Tamper: replace content_hash with an all-zeros digest
        tampered_dict = manifest_to_dict(original)
        tampered_dict["content_hash"] = "0" * 64
        mf_path.write_text(json.dumps(tampered_dict, indent=2, sort_keys=True), encoding="utf-8")
        tampered_manifest = load_manifest(mf_path)

        result = verify_manifest(pq_path, tampered_manifest)

        assert (
            result.verified is False
        ), "verify_manifest must fail when content_hash has been tampered with."
        mismatch_fields = [f for f, _, _ in result.mismatches]
        assert (
            "content_hash" in mismatch_fields
        ), f"content_hash must appear in mismatches. Got: {mismatch_fields}"

    def test_mutated_content_hash_mismatches_contain_expected_and_actual(
        self, tmp_path: Path
    ) -> None:
        """Mismatch record contains original expected hash and actual recomputed hash."""
        pq_path, mf_path, original = _write_parquet_and_manifest(tmp_path)
        fake_hash = "f" * 64
        tampered = manifest_from_dict({**manifest_to_dict(original), "content_hash": fake_hash})

        result = verify_manifest(pq_path, tampered)
        assert not result.verified
        field_map = {f: (exp, act) for f, exp, act in result.mismatches}
        assert "content_hash" in field_map, "content_hash mismatch must be in result"
        expected_val, actual_val = field_map["content_hash"]
        assert (
            expected_val == fake_hash
        ), f"Expected value should be the tampered hash. Got: {expected_val!r}"
        assert (
            actual_val == original.content_hash
        ), f"Actual value should be the recomputed (correct) hash. Got: {actual_val!r}"


# ── Schema hash mutation ──────────────────────────────────────────────────────


class TestSchemaHashMutation:
    def test_mutated_schema_hash_detected_by_verify(self, tmp_path: Path) -> None:
        """Replacing schema_hash in the manifest causes verify_manifest to fail."""
        pq_path, mf_path, original = _write_parquet_and_manifest(tmp_path)

        tampered = manifest_from_dict({**manifest_to_dict(original), "schema_hash": "a" * 64})
        result = verify_manifest(pq_path, tampered)

        assert (
            result.verified is False
        ), "verify_manifest must fail when schema_hash has been tampered with."
        mismatch_fields = [f for f, _, _ in result.mismatches]
        assert (
            "schema_hash" in mismatch_fields
        ), f"schema_hash must appear in mismatches. Got: {mismatch_fields}"

    def test_clean_schema_hash_passes_verify(self, tmp_path: Path) -> None:
        """An unmodified manifest passes verify_manifest cleanly."""
        pq_path, _mf_path, original = _write_parquet_and_manifest(tmp_path)
        result = verify_manifest(pq_path, original)
        assert (
            result.verified is True
        ), f"Clean manifest must pass verify_manifest. Mismatches: {result.mismatches}"


# ── Orphan artifact detection ─────────────────────────────────────────────────


class TestOrphanArtifactDetection:
    def test_orphan_manifest_detected_by_registry(self, tmp_path: Path) -> None:
        """scan_directory must report a manifest file with no matching parquet."""
        # Create an orphan manifest (no parquet alongside it)
        orphan_mf = tmp_path / "GHOST_1d_manifest.json"
        df = _clean_df(5)
        pq_scratch = tmp_path / "_scratch.parquet"
        _write_parquet(df, pq_scratch)
        manifest = generate_manifest(pq_scratch, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        pq_scratch.unlink()  # remove the parquet — manifest remains as orphan
        save_manifest(manifest, orphan_mf)

        registry = scan_directory(tmp_path, now_utc=FIXED_NOW)

        assert len(registry.orphan_manifests) >= 1, (
            "scan_directory must detect orphan manifests. "
            f"orphan_manifests={registry.orphan_manifests}"
        )
        orphan_names = [Path(p).name for p in registry.orphan_manifests]
        assert (
            "GHOST_1d_manifest.json" in orphan_names
        ), f"GHOST_1d_manifest.json must be in orphan list. Got: {orphan_names}"
        # Issues list must mention the orphan
        issues_text = " ".join(registry.issues)
        assert (
            "orphan" in issues_text.lower() or "ghost_1d_manifest" in issues_text.lower()
        ), f"Issues must mention orphan. Got: {registry.issues}"

    def test_missing_manifest_detected_by_registry(self, tmp_path: Path) -> None:
        """scan_directory must report a parquet file with no accompanying manifest."""
        # Write parquet only — no manifest
        df = _clean_df(10)
        pq_path = tmp_path / "NO_MANIFEST_1d.parquet"
        _write_parquet(df, pq_path)

        registry = scan_directory(tmp_path, now_utc=FIXED_NOW)

        issues_text = " ".join(registry.issues).lower()
        assert (
            "missing manifest" in issues_text or "no_manifest" in issues_text
        ), f"Issues must mention missing manifest. Got: {registry.issues}"

    def test_matched_pair_has_no_orphan(self, tmp_path: Path) -> None:
        """A correctly paired parquet + manifest produces no orphans."""
        _write_parquet_and_manifest(tmp_path)
        registry = scan_directory(tmp_path, verify_manifests=True, now_utc=FIXED_NOW)
        assert len(registry.orphan_manifests) == 0, (
            f"No orphans expected when parquet and manifest are correctly paired. "
            f"Got: {registry.orphan_manifests}"
        )


# ── Lineage inconsistency ─────────────────────────────────────────────────────


class TestLineageInconsistency:
    def test_corrupted_row_count_detected(self, tmp_path: Path) -> None:
        """Manifest with wrong row_count causes a mismatch in verify_manifest."""
        pq_path, _mf_path, original = _write_parquet_and_manifest(tmp_path)

        tampered = manifest_from_dict(
            {**manifest_to_dict(original), "row_count": original.row_count + 999}
        )
        result = verify_manifest(pq_path, tampered)

        assert result.verified is False, "verify_manifest must fail when row_count is wrong."
        mismatch_fields = [f for f, _, _ in result.mismatches]
        assert (
            "row_count" in mismatch_fields
        ), f"row_count must appear in mismatches. Got: {mismatch_fields}"

    def test_corrupted_timestamp_range_detected(self, tmp_path: Path) -> None:
        """Manifest with wrong start_timestamp_utc causes verify_manifest to fail."""
        pq_path, _mf_path, original = _write_parquet_and_manifest(tmp_path)

        tampered = manifest_from_dict(
            {
                **manifest_to_dict(original),
                "start_timestamp_utc": "1970-01-01T00:00:00+00:00",
            }
        )
        result = verify_manifest(pq_path, tampered)

        assert result.verified is False
        mismatch_fields = [f for f, _, _ in result.mismatches]
        assert (
            "start_timestamp_utc" in mismatch_fields
        ), f"start_timestamp_utc mismatch must be reported. Got: {mismatch_fields}"


# ── Partial (multi-field) corruption ─────────────────────────────────────────


class TestPartialCorruption:
    def test_multiple_corrupted_fields_all_reported(self, tmp_path: Path) -> None:
        """verify_manifest enumerates ALL corrupted fields, not just the first."""
        pq_path, _mf_path, original = _write_parquet_and_manifest(tmp_path)

        tampered = manifest_from_dict(
            {
                **manifest_to_dict(original),
                "content_hash": "0" * 64,
                "schema_hash": "1" * 64,
                "row_count": 9999,
            }
        )
        result = verify_manifest(pq_path, tampered)

        assert result.verified is False
        mismatch_fields = {f for f, _, _ in result.mismatches}

        for expected_field in ("content_hash", "schema_hash", "row_count"):
            assert expected_field in mismatch_fields, (
                f"'{expected_field}' must be in mismatches when multiple fields corrupted. "
                f"Mismatches found: {mismatch_fields}"
            )

    def test_mismatches_list_is_non_empty_and_structured(self, tmp_path: Path) -> None:
        """Each mismatch is a (field, expected, actual) triple with non-empty strings."""
        pq_path, _mf_path, original = _write_parquet_and_manifest(tmp_path)
        tampered = manifest_from_dict(
            {**manifest_to_dict(original), "content_hash": "bad" + "0" * 61}
        )
        result = verify_manifest(pq_path, tampered)

        assert result.mismatches, "mismatches must be non-empty for a corrupted manifest"
        for field, expected, actual in result.mismatches:
            assert isinstance(field, str) and field, "field must be a non-empty string"
            assert isinstance(expected, str), "expected must be a string"
            assert isinstance(actual, str), "actual must be a string"


# ── Manifest drift after data change ─────────────────────────────────────────


class TestManifestDrift:
    def test_adding_rows_changes_content_hash(self, tmp_path: Path) -> None:
        """After appending a row to the parquet, content_hash changes."""
        df_orig = _clean_df(20)
        pq_path, _mf_path, manifest_orig = _write_parquet_and_manifest(tmp_path, df=df_orig)

        # Append one new row to the parquet (mutate data)
        extra = _clean_df(1)
        extra["timestamp"] = pd.date_range("2024-01-21", periods=1, freq="1D", tz="UTC")
        extra["open"] = 51_000.0
        extra["high"] = 51_200.0
        extra["low"] = 50_800.0
        extra["close"] = 51_000.0
        df_extended = pd.concat([df_orig, extra], ignore_index=True)
        _write_parquet(df_extended, pq_path)

        manifest_new = generate_manifest(pq_path, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)

        assert manifest_new.content_hash != manifest_orig.content_hash, (
            "content_hash must change after appending a row to the parquet. "
            "Manifest drift (data change) must be detectable."
        )
        assert manifest_new.row_count == manifest_orig.row_count + 1, (
            f"row_count must increase by 1. orig={manifest_orig.row_count}, "
            f"new={manifest_new.row_count}"
        )

    def test_modifying_single_value_changes_content_hash(self, tmp_path: Path) -> None:
        """Changing a single price value changes content_hash."""
        df_orig = _clean_df(20)
        pq_path, _mf_path, manifest_orig = _write_parquet_and_manifest(
            tmp_path, df=df_orig, stem="MOD_test"
        )

        # Modify one close price
        df_mod = df_orig.copy()
        df_mod.loc[10, "close"] = df_mod.loc[10, "close"] + 0.0001
        _write_parquet(df_mod, pq_path)

        manifest_mod = generate_manifest(pq_path, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)

        assert manifest_mod.content_hash != manifest_orig.content_hash, (
            "content_hash must change after modifying a single close price. "
            "Even a 0.0001 price change must be detectable."
        )

    def test_verify_manifest_detects_post_write_drift(self, tmp_path: Path) -> None:
        """A manifest generated before data mutation fails verify_manifest after mutation."""
        df_orig = _clean_df(20)
        pq_path, _mf_path, manifest_pre = _write_parquet_and_manifest(
            tmp_path, df=df_orig, stem="DRIFT_test"
        )

        # Mutate the parquet in-place
        df_mut = df_orig.copy()
        df_mut.loc[5, "volume"] = 999_999.0
        _write_parquet(df_mut, pq_path)

        result = verify_manifest(pq_path, manifest_pre)
        assert result.verified is False, (
            "verify_manifest must detect that parquet data has changed since "
            "the reference manifest was generated."
        )
