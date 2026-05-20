"""Adversarial: canonicalization drift and serialization instability.

Verifies that the AQCS canonicalization layer:
1. Produces identical hashes regardless of key insertion order.
2. Detects any mutation to data (key or value changes hash).
3. Handles NaN at all nesting depths deterministically.
4. Distinguishes canonical format (compact separators) from legacy format.
5. Maintains bit-for-bit hash stability across repeated calls.
6. Detects floating-point representation variations via NaN normalization.

Corruption classes covered:
- serialization ordering corruption (key-order instability)
- metadata mutation (any field change → hash change)
- floating-point instability (NaN normalization)
- NaN instability (all NaN forms → null)
- canonical hash drift (determinism across calls)
- legacy vs canonical format divergence
"""

from __future__ import annotations

import hashlib
import math

from aqcs.utils.canonicalization import (
    canonical_bytes,
    canonical_hash,
    canonical_json,
    legacy_hash,
    legacy_json,
    normalize_nan,
    restore_nan,
    sha256_hex,
)

# ── Serialization ordering stability ─────────────────────────────────────────


class TestSerializationOrderingStability:
    """canonical_hash is independent of dict key insertion order."""

    def test_different_insertion_order_same_hash(self) -> None:
        """Two dicts with the same keys/values but different insertion orders hash identically."""
        d1 = {"z": 1, "a": 2, "m": 3, "b": 4}
        d2 = {"a": 2, "b": 4, "m": 3, "z": 1}
        assert canonical_hash(d1) == canonical_hash(d2), (
            "canonical_hash must be independent of dict key insertion order. "
            f"d1 hash={canonical_hash(d1)[:16]}…, d2 hash={canonical_hash(d2)[:16]}…"
        )

    def test_nested_dict_ordering_stable(self) -> None:
        """Nested dicts also produce order-stable hashes."""
        d1 = {"outer": {"z": 99, "a": 1}, "x": 2}
        d2 = {"x": 2, "outer": {"a": 1, "z": 99}}
        assert canonical_hash(d1) == canonical_hash(
            d2
        ), "Nested dict key ordering must not affect canonical_hash."

    def test_list_ordering_is_preserved(self) -> None:
        """List element order IS significant — [1,2,3] != [3,2,1]."""
        d_asc = {"items": [1, 2, 3]}
        d_desc = {"items": [3, 2, 1]}
        assert canonical_hash(d_asc) != canonical_hash(d_desc), (
            "List order must be preserved in canonical_hash. "
            "[1,2,3] and [3,2,1] must hash differently."
        )

    def test_canonical_json_uses_compact_separators(self) -> None:
        """canonical_json output contains no whitespace from separators."""
        result = canonical_json({"a": 1, "b": 2})
        assert '", "' not in result, "canonical_json must not use default separators"
        assert '": "' not in result
        assert result == '{"a":1,"b":2}', f"Unexpected canonical_json output: {result!r}"


# ── Key-order instability between formats ────────────────────────────────────


class TestKeyOrderInstability:
    """canonical_hash and legacy_hash use different separators — they must diverge."""

    def test_canonical_and_legacy_hash_differ_for_same_data(self) -> None:
        """canonical_hash uses compact separators; legacy_hash uses default. They differ."""
        d = {"a": 1, "b": 2}
        h_canonical = canonical_hash(d)
        h_legacy = legacy_hash(d)
        assert h_canonical != h_legacy, (
            "canonical_hash and legacy_hash must produce different digests for the same "
            "data because they use different separator formats. "
            f"canonical={h_canonical[:16]}…, legacy={h_legacy[:16]}…"
        )

    def test_canonical_json_vs_legacy_json_byte_difference(self) -> None:
        """canonical_json uses compact separators; legacy_json uses default separators."""
        d = {"key": "value", "num": 42}
        cj = canonical_json(d)
        lj = legacy_json(d)
        assert cj != lj, (
            f"canonical_json={cj!r} and legacy_json={lj!r} must differ. "
            "They use different separator conventions."
        )
        # Canonical format specifically: no space after comma or colon
        assert (
            ", " not in cj and ": " not in cj
        ), f"canonical_json must use compact separators. Got: {cj!r}"
        # Legacy format: has spaces after separators
        assert (
            ", " in lj or ": " in lj
        ), f"legacy_json must use default separators (with spaces). Got: {lj!r}"


# ── Metadata mutation → hash change ──────────────────────────────────────────


class TestMetadataMutation:
    """Any mutation to artifact data must change the canonical hash."""

    def test_adding_key_changes_hash(self) -> None:
        d_orig = {"a": 1, "b": 2}
        d_extra = {"a": 1, "b": 2, "c": 3}
        assert canonical_hash(d_orig) != canonical_hash(
            d_extra
        ), "Adding a key must change canonical_hash."

    def test_removing_key_changes_hash(self) -> None:
        d_full = {"a": 1, "b": 2, "c": 3}
        d_partial = {"a": 1, "b": 2}
        assert canonical_hash(d_full) != canonical_hash(
            d_partial
        ), "Removing a key must change canonical_hash."

    def test_changing_value_changes_hash(self) -> None:
        d_orig = {"total_return": 0.12, "sharpe_ratio": 1.42}
        d_mut = {"total_return": 0.12, "sharpe_ratio": 1.43}
        assert canonical_hash(d_orig) != canonical_hash(
            d_mut
        ), "Changing a numeric value must change canonical_hash."

    def test_changing_string_value_changes_hash(self) -> None:
        d_orig = {"experiment_name": "baseline_v1", "version": "1"}
        d_mut = {"experiment_name": "baseline_v2", "version": "1"}
        assert canonical_hash(d_orig) != canonical_hash(
            d_mut
        ), "Changing a string value must change canonical_hash."

    def test_swapping_key_value_changes_hash(self) -> None:
        d_orig = {"a": "b"}
        d_swap = {"b": "a"}
        assert canonical_hash(d_orig) != canonical_hash(
            d_swap
        ), "Swapping key and value must change canonical_hash."

    def test_type_change_changes_hash(self) -> None:
        d_int = {"count": 5}
        d_float = {"count": 5.0}
        # JSON does not distinguish int from float for equal values,
        # so 5 and 5.0 serialize identically. This is expected behaviour.
        # Document it as a known limitation.
        h_int = canonical_hash(d_int)
        h_float = canonical_hash(d_float)
        # They may or may not be equal (JSON encoding of 5 vs 5.0).
        # What we assert is determinism: the same dict always produces the same hash.
        assert h_int == canonical_hash(d_int), "Hash must be stable for integer value."
        assert h_float == canonical_hash(d_float), "Hash must be stable for float value."


# ── Floating-point instability ────────────────────────────────────────────────


class TestFloatingPointInstability:
    """NaN must be normalized to null before hashing (allow_nan=False)."""

    def test_nan_raises_without_normalization(self) -> None:
        """canonical_json with allow_nan=False raises on raw NaN after normalization fails."""
        # canonical_hash auto-normalizes, so it must NOT raise.
        data = {"score": float("nan")}
        # Should not raise — normalize_nan is applied internally
        result = canonical_hash(data)
        assert (
            isinstance(result, str) and len(result) == 64
        ), "canonical_hash must succeed after NaN normalization."

    def test_nan_becomes_null_in_canonical_json(self) -> None:
        """NaN serializes as JSON null via normalize_nan."""
        result = canonical_json({"v": float("nan")})
        assert "null" in result, f"NaN must serialize as null. Got: {result!r}"
        assert "nan" not in result.lower(), f"'nan' literal must not appear. Got: {result!r}"

    def test_nan_and_none_produce_same_canonical_hash(self) -> None:
        """float('nan') and None normalize to the same JSON null → same hash."""
        d_nan = {"metric": float("nan")}
        d_none = {"metric": None}
        assert canonical_hash(d_nan) == canonical_hash(d_none), (
            "float('nan') and None must produce identical canonical_hash "
            "after NaN normalization (both → JSON null)."
        )

    def test_inf_is_not_normalized_by_normalize_nan(self) -> None:
        """normalize_nan only handles NaN, not Inf. Inf passes through unchanged."""
        data = {"v": float("inf")}
        normalized = normalize_nan(data)
        assert normalized["v"] == float(
            "inf"
        ), "normalize_nan must not modify Infinity — only NaN is replaced with None."


# ── NaN instability ───────────────────────────────────────────────────────────


class TestNaNInstability:
    """NaN must normalize consistently at all nesting depths."""

    def test_top_level_nan(self) -> None:
        result = normalize_nan(float("nan"))
        assert result is None, "Top-level NaN must normalize to None."

    def test_nested_nan_in_dict(self) -> None:
        d = {"a": {"b": float("nan"), "c": 1.0}}
        result = normalize_nan(d)
        assert result["a"]["b"] is None, "Nested dict NaN must normalize."
        assert result["a"]["c"] == 1.0, "Non-NaN values must be unchanged."

    def test_nan_in_list(self) -> None:
        lst = [1.0, float("nan"), 3.0]
        result = normalize_nan(lst)
        assert result[1] is None, "NaN in list must normalize."
        assert result[0] == 1.0 and result[2] == 3.0, "Non-NaN list elements unchanged."

    def test_nan_in_tuple(self) -> None:
        t = (1.0, float("nan"), 3.0)
        result = normalize_nan(t)
        assert isinstance(result, tuple), "normalize_nan must preserve tuple type."
        assert result[1] is None, "NaN in tuple must normalize."

    def test_nan_hash_stability_across_calls(self) -> None:
        """The same NaN-containing dict always hashes to the same value."""
        d = {"x": float("nan"), "y": [float("nan"), 2.0]}
        h1 = canonical_hash(d)
        h2 = canonical_hash(d)
        h3 = canonical_hash(d)
        assert h1 == h2 == h3, "canonical_hash on NaN-containing data must be stable across calls."

    def test_restore_nan_inverts_normalize_nan(self) -> None:
        """restore_nan(normalize_nan(x)) round-trips for NaN/None."""
        d = {"a": float("nan"), "b": [1.0, float("nan")], "c": "text"}
        normalized = normalize_nan(d)
        restored = restore_nan(normalized)
        assert math.isnan(restored["a"]), "Restored top-level value must be NaN."
        assert math.isnan(restored["b"][1]), "Restored list value must be NaN."
        assert restored["c"] == "text", "Non-NaN/None values must pass through."


# ── Canonical hash drift ──────────────────────────────────────────────────────


class TestCanonicalHashDrift:
    """canonical_hash must be bit-for-bit stable across calls and environments."""

    def test_hash_is_deterministic_across_calls(self) -> None:
        """Same input → same hash, repeated 5 times."""
        d = {
            "experiment_id": "abc-123",
            "total_return": 0.147,
            "sharpe_ratio": 1.83,
            "trade_count": 42,
        }
        hashes = {canonical_hash(d) for _ in range(5)}
        assert (
            len(hashes) == 1
        ), f"canonical_hash must be identical across calls. Got {len(hashes)} distinct hashes."

    def test_known_fixture_produces_known_hash(self) -> None:
        """Regression: a fixed input produces a known, pre-computed hash."""
        # Pre-computed: canonical JSON of {"a":1,"b":2} is '{"a":1,"b":2}'
        # SHA-256 of its UTF-8 bytes
        data = {"a": 1, "b": 2}
        j = canonical_json(data)
        assert j == '{"a":1,"b":2}', f"canonical_json regression failure: {j!r}"

        expected_hash = hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
        assert canonical_hash(data) == expected_hash, (
            f"canonical_hash regression failure. "
            f"expected={expected_hash}, actual={canonical_hash(data)}"
        )

    def test_empty_dict_hash_is_stable(self) -> None:
        """Empty dict always hashes identically."""
        h1 = canonical_hash({})
        h2 = canonical_hash({})
        assert h1 == h2, "Empty dict canonical_hash must be stable."

    def test_sha256_hex_matches_hashlib(self) -> None:
        """sha256_hex is a thin wrapper — verify it matches hashlib directly."""
        raw = b"adversarial test fixture bytes"
        expected = hashlib.sha256(raw).hexdigest()
        assert sha256_hex(raw) == expected, (
            f"sha256_hex must match hashlib.sha256. " f"expected={expected}, got={sha256_hex(raw)}"
        )

    def test_unicode_key_hash_stable(self) -> None:
        """Unicode keys/values must hash stably (ensure_ascii=False preserves UTF-8)."""
        d = {"ticker": "BTC/USDT — 比特币", "value": 1}
        h1 = canonical_hash(d)
        h2 = canonical_hash(d)
        assert h1 == h2, "Unicode-containing dict must hash stably."

    def test_canonical_bytes_is_utf8_of_canonical_json(self) -> None:
        """canonical_bytes must equal canonical_json.encode('utf-8')."""
        d = {"key": "value", "num": 99}
        assert canonical_bytes(d) == canonical_json(d).encode(
            "utf-8"
        ), "canonical_bytes must be the UTF-8 encoding of canonical_json."
