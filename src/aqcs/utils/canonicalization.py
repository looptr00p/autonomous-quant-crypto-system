"""Canonical serialization and hashing utilities for AQCS deterministic artifacts.

This module defines ONE canonical serialization format used for deterministic
hashing across all AQCS research artifact systems.

Canonical format
----------------
- JSON with ``sort_keys=True``
- Compact separators: ``(",", ":")``
- ``ensure_ascii=False``  — preserves UTF-8 faithfully
- ``allow_nan=False``     — NaN must be normalized to ``None`` before serialization
- UTF-8 encoding for all byte operations

Usage for new artifact modules
-------------------------------

    from aqcs.utils.canonicalization import canonical_hash, normalize_nan

    data = normalize_nan({"key": float("nan"), "other": 1.2})
    h = canonical_hash(data)

Backward compatibility note
----------------------------
Artifact modules written before 2026-05-19 use ``json.dumps(..., sort_keys=True)``
with **default** separators (``", "`` and ``": "``).  These modules preserve their
existing hash format to avoid breaking stored artifacts:

- ``aqcs.data.manifest``             — schema_hash, content_hash
- ``aqcs.data.dataset_registry``     — registry hashes
- ``aqcs.monitoring.fleet_monitoring`` — registry_hash, registry_entries_hash
- ``aqcs.research.baseline_report``  — report_hash (metrics_hash uses struct.pack)
- ``aqcs.research.walkforward``      — report_hash
- ``aqcs.research.replay_certificate`` — config/params hash; binary hashes

``aqcs.research.campaign`` uses the canonical (compact-separator) format for its
own ``campaign_hash``.  When verifying external artifact hashes, it uses the
``legacy_hash`` helper to match the default-separator format those artifacts were
written with.

Migration path
--------------
Any NEW artifact schema introduced after 2026-05-19 SHOULD use ``canonical_hash``
for self-certifying hashes.  Existing schemas MUST NOT be changed without an ADR
and explicit human approval (hash-breaking change).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

# ── Canonical format constants ────────────────────────────────────────────────

CANONICAL_SEPARATORS: tuple[str, str] = (",", ":")
CANONICAL_ENCODING: str = "utf-8"

# Default-separator format — used by legacy artifact modules for backward compat.
_LEGACY_SEPARATORS: tuple[str, str] = (", ", ": ")


# ── NaN normalization ─────────────────────────────────────────────────────────


def normalize_nan(value: Any) -> Any:
    """Recursively replace ``float("nan")`` with ``None`` in any structure.

    Must be applied before ``canonical_hash`` or any JSON serialization that
    uses ``allow_nan=False``.

    Handles: dict, list, tuple, float.  Other types pass through unchanged.
    """
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: normalize_nan(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        normalized = [normalize_nan(v) for v in value]
        return type(value)(normalized)
    return value


def restore_nan(value: Any) -> Any:
    """Recursively replace ``None`` with ``float("nan")`` in any structure.

    Inverse of ``normalize_nan``.  Used when loading serialized artifacts
    back into in-memory representations that use NaN for undefined metrics.
    """
    if value is None:
        return float("nan")
    if isinstance(value, dict):
        return {k: restore_nan(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        restored = [restore_nan(v) for v in value]
        return type(value)(restored)
    return value


# ── Canonical serialization ───────────────────────────────────────────────────


def canonical_json(data: Any) -> str:
    """Serialize ``data`` to canonical JSON string.

    Applies ``normalize_nan`` before serialization so that NaN floats become
    JSON ``null`` values.  The output uses:
    - ``sort_keys=True``
    - compact separators ``(",", ":")``
    - ``ensure_ascii=False``
    - ``allow_nan=False``

    Raises:
        ValueError: If any non-normalized NaN or Infinity is encountered after
                    normalization (should not happen under normal use).
    """
    safe = normalize_nan(data)
    return json.dumps(
        safe,
        sort_keys=True,
        separators=CANONICAL_SEPARATORS,
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(data: Any) -> bytes:
    """Return the UTF-8 encoded canonical JSON bytes for ``data``."""
    return canonical_json(data).encode(CANONICAL_ENCODING)


def canonical_hash(data: Any) -> str:
    """Return the SHA-256 hex digest of the canonical JSON representation.

    This is the recommended hash function for NEW AQCS artifact schemas
    introduced after 2026-05-19.

    See the module docstring for the backward-compatibility note on existing
    artifact schemas.
    """
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


# ── Legacy serialization (backward-compatible) ────────────────────────────────


def legacy_json(data: Any, *, normalize: bool = True) -> str:
    """Serialize ``data`` using the legacy default-separator format.

    This matches the format used by artifact modules written before 2026-05-19:
    ``json.dumps(..., sort_keys=True)`` with default separators ``(", ", ": ")``.

    Use this ONLY when you must match an existing stored hash.  New artifact
    schemas should use ``canonical_json`` instead.

    Args:
        data: The data to serialize.
        normalize: When True (default), apply ``normalize_nan`` first.
    """
    safe = normalize_nan(data) if normalize else data
    return json.dumps(safe, sort_keys=True, ensure_ascii=True)


def legacy_bytes(data: Any, *, normalize: bool = True) -> bytes:
    """Return UTF-8 encoded legacy-format JSON bytes."""
    return legacy_json(data, normalize=normalize).encode(CANONICAL_ENCODING)


def legacy_hash(data: Any, *, normalize: bool = True) -> str:
    """SHA-256 of the legacy JSON representation.

    Use this ONLY to verify or reproduce hashes created by artifact modules
    that predate the canonical format (see module docstring).
    """
    return hashlib.sha256(legacy_bytes(data, normalize=normalize)).hexdigest()


# ── Raw byte hashing ──────────────────────────────────────────────────────────


def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()
