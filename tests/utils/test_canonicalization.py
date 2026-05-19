"""Tests for the canonical serialization and hashing layer.

All tests are deterministic and local.  No network, no wall-clock, no randomness.

Coverage:
- canonical_json: compact separators, sort_keys, ensure_ascii=False, allow_nan=False
- canonical_bytes: UTF-8 encoding of canonical_json
- canonical_hash: SHA-256 of canonical_bytes
- canonical_hash is deterministic (same input → same output)
- canonical_hash differs from legacy_hash (different separator format)
- normalize_nan: NaN → None at all nesting depths
- restore_nan: None → NaN at all nesting depths
- normalize_nan / restore_nan round-trip
- legacy_json: default separators, sort_keys
- legacy_hash: SHA-256 of legacy_bytes
- legacy_hash is deterministic
- sha256_hex: raw bytes to hex
- canonical_hash: changes on key addition
- canonical_hash: changes on value change
- canonical_hash: stable across key insertion order variations
- canonical_hash: Unicode characters handled without escaping
- legacy_hash vs canonical_hash divergence documents the format difference
- backward compat: baseline_report._compute_report_hash matches legacy_hash
- backward compat: walkforward._compute_report_hash matches legacy_hash
- backward compat: manifest schema_hash uses sort_keys (legacy)
- cross-artifact: campaign._compute_campaign_hash matches canonical_hash
- regression: canonical_hash of known fixture produces known value
- regression: legacy_hash of known fixture produces known value
"""

from __future__ import annotations

import hashlib
import json
import math

from aqcs.utils.canonicalization import (
    canonical_hash,
    canonical_json,
    legacy_bytes,
    legacy_hash,
    legacy_json,
    normalize_nan,
    restore_nan,
    sha256_hex,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SIMPLE: dict = {"z": 2, "a": 1, "m": 3}
_NESTED: dict = {"outer": {"z": 99, "a": 1}, "x": [3, 1, 2]}
_WITH_NAN: dict = {"score": float("nan"), "count": 5}
_WITH_NONE: dict = {"score": None, "count": 5}
_UNICODE: dict = {"key": "BTC/USDT — 比特币", "val": 1}


# ── canonical_json ────────────────────────────────────────────────────────────


class TestCanonicalJson:
    def test_uses_compact_separators(self) -> None:
        result = canonical_json({"a": 1, "b": 2})
        # Compact separators produce exact output with no whitespace
        assert result == '{"a":1,"b":2}'
        assert ", " not in result
        assert ": " not in result

    def test_keys_are_sorted(self) -> None:
        result = canonical_json({"z": 1, "a": 2})
        assert result.index('"a"') < result.index('"z"')

    def test_nan_normalized_to_null(self) -> None:
        result = canonical_json({"v": float("nan")})
        assert "null" in result
        assert "nan" not in result.lower()

    def test_allow_nan_is_false_with_normalized(self) -> None:
        # normalize_nan converts NaN to None first, so allow_nan=False won't raise
        result = canonical_json({"v": float("nan")})
        assert result == '{"v":null}'

    def test_unicode_preserved_without_escaping(self) -> None:
        result = canonical_json({"k": "比特币"})
        assert "比特币" in result  # not escaped

    def test_nested_dict_keys_sorted(self) -> None:
        result = canonical_json({"outer": {"z": 1, "a": 2}})
        assert result.index('"a"') < result.index('"z"')


# ── canonical_hash ────────────────────────────────────────────────────────────


class TestCanonicalHash:
    def test_deterministic(self) -> None:
        assert canonical_hash(_SIMPLE) == canonical_hash(_SIMPLE)

    def test_key_order_invariant(self) -> None:
        d1 = {"z": 1, "a": 2}
        d2 = {"a": 2, "z": 1}
        assert canonical_hash(d1) == canonical_hash(d2)

    def test_changes_on_value_change(self) -> None:
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})

    def test_changes_on_key_addition(self) -> None:
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 1, "b": 2})

    def test_result_is_64_char_hex(self) -> None:
        h = canonical_hash(_SIMPLE)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_nan_and_none_hash_identically(self) -> None:
        assert canonical_hash({"v": float("nan")}) == canonical_hash({"v": None})

    def test_differs_from_legacy_hash(self) -> None:
        # The two formats produce different bytes → different hashes
        assert canonical_hash(_SIMPLE) != legacy_hash(_SIMPLE)

    def test_unicode_stable(self) -> None:
        h1 = canonical_hash(_UNICODE)
        h2 = canonical_hash(_UNICODE)
        assert h1 == h2

    def test_regression_known_fixture(self) -> None:
        """Fixed regression value — must not change."""
        data = {"a": 1, "b": 2}
        expected = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        assert canonical_hash(data) == expected


# ── normalize_nan / restore_nan ───────────────────────────────────────────────


class TestNanNormalization:
    def test_nan_becomes_none(self) -> None:
        assert normalize_nan(float("nan")) is None

    def test_non_nan_float_unchanged(self) -> None:
        assert normalize_nan(1.5) == 1.5

    def test_nested_dict(self) -> None:
        result = normalize_nan({"a": float("nan"), "b": {"c": float("nan")}})
        assert result["a"] is None
        assert result["b"]["c"] is None

    def test_list_items(self) -> None:
        result = normalize_nan([1.0, float("nan"), 3.0])
        assert result[1] is None

    def test_none_unchanged_by_normalize(self) -> None:
        assert normalize_nan(None) is None

    def test_restore_none_to_nan(self) -> None:
        assert math.isnan(restore_nan(None))

    def test_restore_non_none_unchanged(self) -> None:
        assert restore_nan(1.5) == 1.5

    def test_round_trip(self) -> None:
        original = {"v": float("nan"), "w": 1.0}
        normalized = normalize_nan(original)
        restored = restore_nan(normalized)
        assert math.isnan(restored["v"])
        assert restored["w"] == 1.0

    def test_normalize_tuple(self) -> None:
        result = normalize_nan((float("nan"), 1.0))
        assert result[0] is None
        assert result[1] == 1.0

    def test_int_unchanged(self) -> None:
        assert normalize_nan(42) == 42

    def test_string_unchanged(self) -> None:
        assert normalize_nan("hello") == "hello"


# ── legacy_json / legacy_hash ─────────────────────────────────────────────────


class TestLegacyFormat:
    def test_uses_default_separators(self) -> None:
        result = legacy_json({"a": 1, "b": 2})
        # Default separators produce ", " between items and ": " after key
        assert ", " in result or ": " in result

    def test_keys_sorted(self) -> None:
        result = legacy_json({"z": 1, "a": 2})
        assert result.index('"a"') < result.index('"z"')

    def test_deterministic(self) -> None:
        assert legacy_hash(_SIMPLE) == legacy_hash(_SIMPLE)

    def test_regression_known_fixture(self) -> None:
        """Fixed regression value — must not change."""
        data = {"a": 1, "b": 2}
        expected = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
        assert legacy_hash(data) == expected

    def test_nan_normalized_before_hash(self) -> None:
        # NaN must not appear in legacy JSON (would produce "NaN" which is
        # invalid JSON and platform-dependent)
        d = {"v": float("nan")}
        result = legacy_json(d, normalize=True)
        assert "null" in result
        assert "NaN" not in result

    def test_no_normalization_option(self) -> None:
        # When normalize=False, caller is responsible for pre-normalization
        d = {"v": 1.0}
        assert legacy_json(d, normalize=False) == legacy_json(d, normalize=True)


# ── sha256_hex ────────────────────────────────────────────────────────────────


class TestSha256Hex:
    def test_matches_stdlib(self) -> None:
        data = b"hello world"
        assert sha256_hex(data) == hashlib.sha256(data).hexdigest()

    def test_deterministic(self) -> None:
        assert sha256_hex(b"x") == sha256_hex(b"x")

    def test_empty_bytes(self) -> None:
        assert sha256_hex(b"") == hashlib.sha256(b"").hexdigest()


# ── Backward compatibility: existing artifact hash formats ────────────────────


class TestBackwardCompatibility:
    def test_baseline_report_hash_matches_legacy_hash(self) -> None:
        """baseline_report._compute_report_hash uses json.dumps(sort_keys=True)
        with default separators — this must match legacy_hash."""
        from aqcs.research.baseline_report import _compute_report_hash

        data = {
            "report_version": "1",
            "experiment_id": "test",
            "total_return": 0.10,
            "max_drawdown": 0.05,
        }
        assert _compute_report_hash(data) == legacy_hash(data)

    def test_walkforward_report_hash_matches_legacy_hash(self) -> None:
        """walkforward._compute_report_hash uses json.dumps(sort_keys=True)
        with default separators — this must match legacy_hash."""
        from aqcs.research.walkforward import _compute_report_hash

        data = {
            "report_version": "1",
            "total_bars": 300,
            "n_windows": 4,
            "summary": {"n_windows_total": 4},
        }
        assert _compute_report_hash(data) == legacy_hash(data)

    def test_campaign_hash_matches_canonical_hash(self) -> None:
        """campaign._compute_campaign_hash must use canonical_hash
        (compact separators)."""
        from aqcs.research.campaign import _compute_campaign_hash

        data = {"campaign_name": "test", "total_experiments": 2}
        assert _compute_campaign_hash(data) == canonical_hash(data)

    def test_manifest_schema_hash_uses_legacy_format(self) -> None:
        """manifest._compute_schema_hash hashes field pairs with
        json.dumps(sort_keys=True) — matches legacy_hash."""
        fields = [["exchange", "string"], ["symbol", "string"]]
        schema_bytes_legacy = json.dumps(fields, sort_keys=True).encode("utf-8")
        expected = hashlib.sha256(schema_bytes_legacy).hexdigest()
        # Verify legacy_hash matches (fields list, not dict, so sort_keys is no-op)
        assert hashlib.sha256(legacy_bytes(fields, normalize=False)).hexdigest() == expected

    def test_canonical_and_legacy_produce_different_hashes(self) -> None:
        """The two formats MUST produce different hashes for the same data.
        This documents the deliberate divergence and guards against accidental
        convergence of the two serialization formats.
        """
        data = {"a": 1, "b": 2, "c": "hello"}
        ch = canonical_hash(data)
        lh = legacy_hash(data)
        assert ch != lh, (
            "canonical_hash and legacy_hash must differ — "
            "if they are equal, the canonical format is not distinct."
        )


# ── Cross-artifact consistency ────────────────────────────────────────────────


class TestCrossArtifactConsistency:
    def test_campaign_verify_self_hash_uses_legacy(self) -> None:
        """campaign._verify_self_hash must use legacy_hash to correctly verify
        baseline and walk-forward report hashes."""
        from aqcs.research.campaign import _verify_self_hash

        # Build a dict with a report_hash computed by legacy_hash (as baseline/WF do)
        data = {"report_version": "1", "total_return": 0.10}
        data_no_hash = dict(data)
        real_hash = legacy_hash(data_no_hash)
        data_with_hash = {**data, "report_hash": real_hash}

        assert _verify_self_hash(data_with_hash, "report_hash") is True

    def test_campaign_verify_self_hash_detects_tamper(self) -> None:
        from aqcs.research.campaign import _verify_self_hash

        data = {"report_hash": "0" * 64, "total_return": 0.10}
        assert _verify_self_hash(data, "report_hash") is False

    def test_campaign_verify_rejects_canonical_hash_of_legacy_artifact(self) -> None:
        """If a legacy artifact's hash was incorrectly computed with canonical
        (compact) separators, _verify_self_hash should REJECT it — this confirms
        the format mismatch is correctly detected."""
        from aqcs.research.campaign import _verify_self_hash

        data = {"report_version": "1", "total_return": 0.10}
        # Incorrectly use canonical_hash (compact) for a legacy artifact
        wrong_hash = canonical_hash(data)
        data_with_wrong_hash = {**data, "report_hash": wrong_hash}

        # _verify_self_hash uses legacy format → compact hash does NOT match
        assert _verify_self_hash(data_with_wrong_hash, "report_hash") is False
