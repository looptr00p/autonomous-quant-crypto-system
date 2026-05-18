"""Deterministic replay certification for AQCS research experiments.

A ReplayCertificate formally certifies that a research experiment can be
reproduced identically.  It captures cryptographic hashes of every
deterministic output of the research pipeline:

  - dataset_content_hash  — hash of the OHLCV data values (from DatasetManifest)
  - dataset_schema_hash   — hash of the Parquet column schema (from DatasetManifest)
  - config_hash           — hash of the BacktestConfig fields
  - parameters_hash       — hash of the ExperimentRecord.parameters dict
  - metrics_hash          — hash of the backtest metrics
  - trades_hash           — hash of the trade list (chronological, canonical bytes)
  - equity_hash           — hash of the equity curve (chronological, canonical bytes)
  - signals_hash          — hash of the signal series (chronological, canonical bytes)

A replay is certified when all eight hashes from a fresh run match the
reference certificate exactly.

Design constraints
------------------
- No wall-clock dependence in hash computation.  ``generation_timestamp_utc``
  is informational only; inject ``now_utc`` in tests.
- Stable byte-level encoding: timestamps as int64 milliseconds-since-epoch
  (little-endian), floats as float64 little-endian, strings as UTF-8 followed
  by a null separator byte.
- All ordered collections use chronological order (already guaranteed by the
  engine).  Unordered collections (metrics, parameters) use sorted keys.
- Row/item counts are hashed as fixed-width uint64 prefixes to guard against
  length-extension attacks.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.models import ExperimentRecord
from aqcs.utils.events import SignalDirection

# ── Constants ─────────────────────────────────────────────────────────────────

CERTIFICATE_VERSION: str = "1"

# Canonical encoding for SignalDirection values in signals_hash.
_DIRECTION_BYTE: dict[SignalDirection, int] = {
    SignalDirection.LONG: 1,
    SignalDirection.NEUTRAL: 0,
    SignalDirection.SHORT: -1,
}


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplayCertificate:
    """Immutable replay identity certificate for a single research experiment.

    All hash fields are lowercase hex SHA-256 digests (64 characters).
    Timestamp fields are ISO-8601 UTC strings.

    ``dataset_content_hash`` and ``dataset_schema_hash`` are the corresponding
    hash fields from ``DatasetManifest`` (or any equivalent content/schema
    hash computed by the caller).
    """

    certificate_version: str
    experiment_id: str
    experiment_name: str
    git_commit_hash: str
    dataset_content_hash: str
    dataset_schema_hash: str
    config_hash: str
    parameters_hash: str
    metrics_hash: str
    trades_hash: str
    equity_hash: str
    signals_hash: str
    generation_timestamp_utc: str
    certified_bars: int
    certified_trades: int


@dataclass(frozen=True)
class CertificationVerificationResult:
    """Outcome of verifying a replay against a reference ReplayCertificate.

    ``verified`` is True only when all hash fields match exactly.
    ``mismatches`` lists ``(field_name, expected_hash, actual_hash)`` triples
    for every field that differs.
    """

    verified: bool
    mismatches: list[tuple[str, str, str]]


# ── Public API ────────────────────────────────────────────────────────────────


def certify_result(
    result: BacktestResult,
    signals: pd.Series,
    dataset_content_hash: str,
    dataset_schema_hash: str,
    experiment: ExperimentRecord,
    *,
    now_utc: datetime | None = None,
) -> ReplayCertificate:
    """Generate a deterministic replay certificate from a completed research run.

    Args:
        result: Complete ``BacktestResult`` from ``run_backtest``.
        signals: Full signal ``pd.Series`` (SignalDirection values, UTC index)
                 as produced by the signal generator — before date filtering.
        dataset_content_hash: Content hash of the input dataset (e.g.
            ``DatasetManifest.content_hash``).  Identifies the exact data used.
        dataset_schema_hash: Schema hash of the input dataset (e.g.
            ``DatasetManifest.schema_hash``).  Detects column drift.
        experiment: Completed ``ExperimentRecord`` with parameters and metrics.
        now_utc: Reference UTC datetime for ``generation_timestamp_utc``.
                 Defaults to ``datetime.now(UTC)``.  Inject a fixed value in
                 tests to obtain fully deterministic certificates.

    Returns:
        ``ReplayCertificate`` with all hash fields populated.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)

    return ReplayCertificate(
        certificate_version=CERTIFICATE_VERSION,
        experiment_id=str(experiment.experiment_id),
        experiment_name=experiment.experiment_name,
        git_commit_hash=experiment.git_commit_hash,
        dataset_content_hash=dataset_content_hash,
        dataset_schema_hash=dataset_schema_hash,
        config_hash=_hash_config(result.config),
        parameters_hash=_hash_parameters(experiment.parameters),
        metrics_hash=_hash_metrics(result.metrics),
        trades_hash=_hash_trades(result.trades),
        equity_hash=_hash_equity_curve(result.equity_curve),
        signals_hash=_hash_signals(signals),
        generation_timestamp_utc=_now.isoformat(),
        certified_bars=result.n_bars,
        certified_trades=len(result.trades),
    )


def verify_certificate(
    result: BacktestResult,
    signals: pd.Series,
    dataset_content_hash: str,
    dataset_schema_hash: str,
    experiment: ExperimentRecord,
    reference: ReplayCertificate,
) -> CertificationVerificationResult:
    """Verify a replay result against a reference ReplayCertificate.

    Re-certifies the result using the reference ``generation_timestamp_utc``
    (so the informational timestamp field does not cause a spurious mismatch)
    and compares every hash field.

    Returns:
        ``CertificationVerificationResult``.  ``verified`` is True only when
        all checked fields match.  ``mismatches`` is empty when verified.
    """
    try:
        gen_ts = datetime.fromisoformat(reference.generation_timestamp_utc)
    except ValueError:
        gen_ts = datetime.now(UTC)

    fresh = certify_result(
        result,
        signals,
        dataset_content_hash,
        dataset_schema_hash,
        experiment,
        now_utc=gen_ts,
    )

    checked_fields = (
        "certificate_version",
        "dataset_content_hash",
        "dataset_schema_hash",
        "config_hash",
        "parameters_hash",
        "metrics_hash",
        "trades_hash",
        "equity_hash",
        "signals_hash",
        "certified_bars",
        "certified_trades",
    )

    mismatches: list[tuple[str, str, str]] = []
    for field in checked_fields:
        expected = str(getattr(reference, field))
        actual = str(getattr(fresh, field))
        if expected != actual:
            mismatches.append((field, expected, actual))

    return CertificationVerificationResult(
        verified=len(mismatches) == 0,
        mismatches=mismatches,
    )


def certificate_to_dict(cert: ReplayCertificate) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``ReplayCertificate``.

    Output is deterministic when ``json.dumps(..., sort_keys=True)`` is used.
    """
    return {
        "certificate_version": cert.certificate_version,
        "experiment_id": cert.experiment_id,
        "experiment_name": cert.experiment_name,
        "git_commit_hash": cert.git_commit_hash,
        "dataset_content_hash": cert.dataset_content_hash,
        "dataset_schema_hash": cert.dataset_schema_hash,
        "config_hash": cert.config_hash,
        "parameters_hash": cert.parameters_hash,
        "metrics_hash": cert.metrics_hash,
        "trades_hash": cert.trades_hash,
        "equity_hash": cert.equity_hash,
        "signals_hash": cert.signals_hash,
        "generation_timestamp_utc": cert.generation_timestamp_utc,
        "certified_bars": cert.certified_bars,
        "certified_trades": cert.certified_trades,
    }


def certificate_from_dict(d: dict[str, Any]) -> ReplayCertificate:
    """Reconstruct a ``ReplayCertificate`` from a dict (e.g. loaded from JSON).

    Raises:
        KeyError: If any required field is missing from ``d``.
        TypeError: If a field has an incompatible type.
    """
    return ReplayCertificate(
        certificate_version=str(d["certificate_version"]),
        experiment_id=str(d["experiment_id"]),
        experiment_name=str(d["experiment_name"]),
        git_commit_hash=str(d["git_commit_hash"]),
        dataset_content_hash=str(d["dataset_content_hash"]),
        dataset_schema_hash=str(d["dataset_schema_hash"]),
        config_hash=str(d["config_hash"]),
        parameters_hash=str(d["parameters_hash"]),
        metrics_hash=str(d["metrics_hash"]),
        trades_hash=str(d["trades_hash"]),
        equity_hash=str(d["equity_hash"]),
        signals_hash=str(d["signals_hash"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        certified_bars=int(d["certified_bars"]),
        certified_trades=int(d["certified_trades"]),
    )


def save_certificate(cert: ReplayCertificate, path: Path) -> None:
    """Write a certificate to a JSON file at ``path``.

    Keys are sorted for deterministic output.
    """
    path = Path(path)
    path.write_text(
        json.dumps(certificate_to_dict(cert), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_certificate(path: Path) -> ReplayCertificate:
    """Load a certificate from a JSON file written by ``save_certificate``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in certificate file '{path}': {exc}") from exc
    return certificate_from_dict(raw)


# ── Internal hash helpers ─────────────────────────────────────────────────────


def _ts_to_ms(dt: datetime) -> int:
    """Convert a UTC-aware datetime to milliseconds since epoch (int64)."""
    return int(pd.Timestamp(dt).value // 1_000_000)


def _hash_config(config: BacktestConfig) -> str:
    """SHA-256 of the BacktestConfig fields as sorted JSON."""
    config_json = json.dumps(config.model_dump(), sort_keys=True).encode("utf-8")
    return hashlib.sha256(config_json).hexdigest()


def _hash_parameters(parameters: dict[str, Any]) -> str:
    """SHA-256 of the experiment parameters dict as sorted JSON."""
    params_json = json.dumps(parameters, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(params_json).hexdigest()


def _hash_metrics(metrics: dict[str, float]) -> str:
    """SHA-256 over sorted (key, float64 little-endian) metric pairs.

    Uses binary float encoding rather than JSON to avoid float-to-string
    precision ambiguity for computed values like sharpe_ratio.
    """
    h = hashlib.sha256()
    h.update(len(metrics).to_bytes(8, byteorder="little"))
    for key in sorted(metrics):
        h.update(key.encode("utf-8"))
        h.update(b"\x00")
        h.update(struct.pack("<d", float(metrics[key])))
    return h.hexdigest()


def _hash_trades(trades: tuple[Trade, ...]) -> str:
    """SHA-256 over the trade list in chronological order.

    Encoding per trade:
      timestamp (int64 ms, little-endian) | side (UTF-8) | NUL |
      fill_price | quantity | fee | slippage_amount | value  (all float64 LE)
    """
    h = hashlib.sha256()
    h.update(len(trades).to_bytes(8, byteorder="little"))
    for trade in trades:
        h.update(_ts_to_ms(trade.timestamp).to_bytes(8, byteorder="little", signed=True))
        h.update(trade.side.encode("utf-8"))
        h.update(b"\x00")
        h.update(struct.pack("<d", trade.fill_price))
        h.update(struct.pack("<d", trade.quantity))
        h.update(struct.pack("<d", trade.fee))
        h.update(struct.pack("<d", trade.slippage_amount))
        h.update(struct.pack("<d", trade.value))
    return h.hexdigest()


def _hash_equity_curve(equity_curve: tuple[EquityCurvePoint, ...]) -> str:
    """SHA-256 over equity curve points in chronological order.

    Encoding per point:
      timestamp (int64 ms, little-endian) |
      equity | cash | position | price  (all float64 LE)
    """
    h = hashlib.sha256()
    h.update(len(equity_curve).to_bytes(8, byteorder="little"))
    for pt in equity_curve:
        h.update(_ts_to_ms(pt.timestamp).to_bytes(8, byteorder="little", signed=True))
        h.update(struct.pack("<d", pt.equity))
        h.update(struct.pack("<d", pt.cash))
        h.update(struct.pack("<d", pt.position))
        h.update(struct.pack("<d", pt.price))
    return h.hexdigest()


def _hash_signals(signals: pd.Series) -> str:
    """SHA-256 over the signal series in chronological (index) order.

    The series index must be a UTC-aware DatetimeIndex.
    Encoding per bar:
      timestamp (int64 ms, little-endian) | direction byte (signed int8)

    Direction encoding: LONG=1, NEUTRAL=0, SHORT=-1.
    Unknown directions are treated as NEUTRAL (0).
    """
    h = hashlib.sha256()
    sorted_signals = signals.sort_index()
    h.update(len(sorted_signals).to_bytes(8, byteorder="little"))
    # Iterate over the DatetimeIndex directly for clean types.
    idx: pd.DatetimeIndex = sorted_signals.index  # type: ignore[assignment]
    for i, direction in enumerate(sorted_signals):
        ts_ms = int(idx[i].value // 1_000_000)
        h.update(ts_ms.to_bytes(8, byteorder="little", signed=True))
        direction_byte = _DIRECTION_BYTE.get(direction, 0)
        h.update(struct.pack("<b", direction_byte))
    return h.hexdigest()
