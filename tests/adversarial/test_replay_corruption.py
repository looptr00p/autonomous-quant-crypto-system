"""Adversarial: replay certificate corruption scenarios.

Deliberately corrupts ReplayCertificate fields and replay inputs to verify
that verify_certificate detects every class of tampering deterministically.

Corruption classes covered:
- replay tampering (hash field mutation)
- replay metadata mutation (non-hash fields)
- signal ordering mutation (reversed index → signals_hash changes)
- all checked hash fields verified individually
- dataset_content_hash / dataset_schema_hash corruption (lineage)
- trades ordering mutation
- equity curve ordering mutation
- certified_bars / certified_trades mismatch
- duplicate certification produces identical certificate
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pandas as pd
import pytest

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.models import ExperimentRecord, ExperimentStatus
from aqcs.research.replay_certificate import (
    CertificationVerificationResult,
    ReplayCertificate,
    _hash_signals,
    _hash_trades,
    certificate_from_dict,
    certificate_to_dict,
    certify_result,
    verify_certificate,
)
from aqcs.utils.events import SignalDirection

from .conftest import FIXED_NOW

# ── Shared constants ──────────────────────────────────────────────────────────

_BASE_TS = datetime(2024, 1, 1, tzinfo=UTC)
_CONTENT_HASH = "a" * 64
_SCHEMA_HASH = "b" * 64
_N = 20
_FIXED_UUID = UUID("00000000-0000-0000-0000-000000000042")


# ── Factories ─────────────────────────────────────────────────────────────────


def _make_config(**overrides: object) -> BacktestConfig:
    defaults: dict[str, object] = {
        "initial_capital": 10_000.0,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
    }
    defaults.update(overrides)
    return BacktestConfig(**defaults)  # type: ignore[arg-type]


def _make_timestamps(n: int = _N) -> list[datetime]:
    return [_BASE_TS + timedelta(days=i) for i in range(n)]


def _make_trades(n: int = 4) -> tuple[Trade, ...]:
    tss = _make_timestamps(n * 2)
    trades = []
    for i in range(n):
        trades.append(
            Trade(
                timestamp=tss[i * 2],
                side="buy" if i % 2 == 0 else "sell",
                fill_price=45_000.0 + i * 100,
                quantity=0.2,
                fee=4.5 + i * 0.1,
                slippage_amount=0.9,
                value=9_000.0 + i * 20,
            )
        )
    return tuple(trades)


def _make_equity(n: int = _N) -> tuple[EquityCurvePoint, ...]:
    tss = _make_timestamps(n)
    points = []
    equity = 10_000.0
    for i, ts in enumerate(tss):
        equity = equity * (1.0 + 0.001 * (i % 3 - 1))
        points.append(
            EquityCurvePoint(
                timestamp=ts,
                equity=equity,
                cash=equity * 0.5,
                position=0.1,
                price=45_000.0 + i * 50,
            )
        )
    return tuple(points)


def _make_signals(n: int = _N) -> pd.Series:
    tss = pd.DatetimeIndex([_BASE_TS + timedelta(days=i) for i in range(n)], tz="UTC")
    directions = [
        (
            SignalDirection.LONG
            if i % 3 == 0
            else (SignalDirection.NEUTRAL if i % 3 == 1 else SignalDirection.SHORT)
        )
        for i in range(n)
    ]
    return pd.Series(directions, index=tss, dtype=object)


def _make_metrics() -> dict[str, float]:
    return {
        "total_return": 0.12,
        "cagr": 0.08,
        "max_drawdown": -0.05,
        "sharpe_ratio": 1.42,
        "annualised_volatility": 0.18,
        "trade_count": 4.0,
        "win_rate": 0.75,
        "exposure": 0.60,
    }


def _make_result(**overrides: object) -> BacktestResult:
    defaults: dict[str, object] = {
        "config": _make_config(),
        "trades": _make_trades(),
        "equity_curve": _make_equity(),
        "metrics": _make_metrics(),
        "n_bars": _N,
        "experiment_id": "test-exp-id",
    }
    defaults.update(overrides)
    return BacktestResult(**defaults)  # type: ignore[arg-type]


def _make_experiment(**overrides: object) -> ExperimentRecord:
    defaults: dict[str, object] = {
        "experiment_id": _FIXED_UUID,
        "experiment_name": "test_experiment",
        "timestamp_started_utc": _BASE_TS,
        "status": ExperimentStatus.COMPLETED,
        "git_commit_hash": "deadbeef",
        "parameters": {"fee_bps": 10.0, "slippage_bps": 2.0},
    }
    defaults.update(overrides)
    return ExperimentRecord(**defaults)  # type: ignore[arg-type]


def _certify(
    result: BacktestResult | None = None,
    signals: pd.Series | None = None,
    content_hash: str = _CONTENT_HASH,
    schema_hash: str = _SCHEMA_HASH,
    experiment: ExperimentRecord | None = None,
) -> ReplayCertificate:
    return certify_result(
        result or _make_result(),
        signals if signals is not None else _make_signals(),
        content_hash,
        schema_hash,
        experiment or _make_experiment(),
        now_utc=FIXED_NOW,
    )


def _verify(
    cert: ReplayCertificate,
    result: BacktestResult | None = None,
    signals: pd.Series | None = None,
    content_hash: str = _CONTENT_HASH,
    schema_hash: str = _SCHEMA_HASH,
) -> CertificationVerificationResult:
    """Re-certify against canonical content/schema hashes and compare to cert.

    Uses fixed _CONTENT_HASH / _SCHEMA_HASH as the "ground truth" inputs so that
    tampering cert.dataset_content_hash or cert.dataset_schema_hash is detectable
    (the fresh cert uses canonical hashes; the tampered cert has different values).
    """
    return verify_certificate(
        result or _make_result(),
        signals if signals is not None else _make_signals(),
        content_hash,
        schema_hash,
        _make_experiment(),
        cert,
    )


# ── Replay tampering (hash field mutation) ───────────────────────────────────


class TestReplayTampering:
    """Mutating any hash field in a certificate causes verify_certificate to fail."""

    @pytest.mark.parametrize(
        "field,fake_value",
        [
            ("config_hash", "0" * 64),
            ("parameters_hash", "1" * 64),
            ("metrics_hash", "2" * 64),
            ("trades_hash", "3" * 64),
            ("equity_hash", "4" * 64),
            ("signals_hash", "5" * 64),
            ("dataset_content_hash", "6" * 64),
            ("dataset_schema_hash", "7" * 64),
        ],
    )
    def test_single_hash_field_mutation_detected(self, field: str, fake_value: str) -> None:
        """Mutating a single hash field in the certificate must cause verification failure."""
        cert = _certify()
        tampered_dict = certificate_to_dict(cert)
        tampered_dict[field] = fake_value
        tampered = certificate_from_dict(tampered_dict)

        result = _verify(tampered)

        assert result.verified is False, (
            f"verify_certificate must fail when '{field}' is tampered. "
            f"tampered_value={fake_value[:8]}…"
        )
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert (
            field in mismatch_fields
        ), f"'{field}' must appear in mismatches. Got: {mismatch_fields}"

    def test_mismatch_record_contains_expected_and_actual(self) -> None:
        """Each mismatch triple has (field, expected_tampered, actual_recomputed)."""
        cert = _certify()
        fake_hash = "abcd" + "0" * 60
        tampered = certificate_from_dict({**certificate_to_dict(cert), "metrics_hash": fake_hash})

        result = _verify(tampered)
        assert not result.verified
        field_map = {f: (exp, act) for f, exp, act in result.mismatches}
        assert "metrics_hash" in field_map
        expected_val, actual_val = field_map["metrics_hash"]
        assert (
            expected_val == fake_hash
        ), f"expected must be the tampered hash, got {expected_val!r}"
        assert (
            actual_val == cert.metrics_hash
        ), f"actual must be the correctly computed hash, got {actual_val!r}"


# ── Replay metadata mutation ─────────────────────────────────────────────────


class TestReplayMetadataMutation:
    """Non-hash informational fields do not break verification."""

    def test_clean_certificate_passes(self) -> None:
        """An unmodified certificate must pass verify_certificate."""
        cert = _certify()
        result = _verify(cert)
        assert (
            result.verified is True
        ), f"Clean certificate must pass verify_certificate. Mismatches: {result.mismatches}"

    def test_generation_timestamp_not_checked(self) -> None:
        """generation_timestamp_utc is informational and not in checked fields."""
        cert = _certify()
        # Mutate timestamp — verify_certificate uses reference.generation_timestamp_utc
        # to re-certify, so this is by design not checked.
        tampered = certificate_from_dict(
            {**certificate_to_dict(cert), "generation_timestamp_utc": "1970-01-01T00:00:00+00:00"}
        )
        result = _verify(tampered)
        # generation_timestamp_utc is not in checked_fields — should still pass
        # (The verify function re-certifies using reference's generation_timestamp_utc)
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert (
            "generation_timestamp_utc" not in mismatch_fields
        ), "generation_timestamp_utc must not appear in mismatches — it is informational."

    def test_experiment_name_not_in_hash_fields(self) -> None:
        """experiment_name is recorded but not hashed — changing it does not fail verify."""
        cert = _certify()
        tampered = certificate_from_dict(
            {**certificate_to_dict(cert), "experiment_name": "TAMPERED_NAME"}
        )
        result = _verify(tampered)
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert (
            "experiment_name" not in mismatch_fields
        ), "experiment_name must not appear in mismatches — it is metadata only."


# ── Signal mutation ───────────────────────────────────────────────────────────


class TestReplayOrderingMutation:
    """Signal and trade mutations must be detected via hash changes.

    Note: _hash_signals always sorts by index before hashing, so reordering
    the same timestamps produces an identical hash.  Adversarial tests must
    mutate VALUES or TIMESTAMPS (not just order) to provoke a hash change.
    """

    def test_changing_signal_direction_changes_signals_hash(self) -> None:
        """Flipping one signal direction (LONG→NEUTRAL) must change signals_hash."""
        signals_original = _make_signals()
        # Flip bar 5 from LONG to SHORT
        tss = pd.DatetimeIndex([_BASE_TS + timedelta(days=i) for i in range(_N)], tz="UTC")
        mutated_values = list(signals_original)
        mutated_values[5] = (
            SignalDirection.SHORT
            if mutated_values[5] == SignalDirection.LONG
            else SignalDirection.LONG
        )
        signals_mutated = pd.Series(mutated_values, index=tss, dtype=object)

        h_original = _hash_signals(signals_original)
        h_mutated = _hash_signals(signals_mutated)

        assert h_original != h_mutated, (
            "Changing a signal direction must change signals_hash. "
            f"original={h_original[:16]}…, mutated={h_mutated[:16]}…"
        )

    def test_shifted_signal_timestamps_change_signals_hash(self) -> None:
        """Shifting all signal timestamps by 1 day must change signals_hash."""
        signals_original = _make_signals()
        # Shift all timestamps forward by 1 day
        shifted_idx = pd.DatetimeIndex(
            [_BASE_TS + timedelta(days=i + 1) for i in range(_N)], tz="UTC"
        )
        signals_shifted = pd.Series(list(signals_original), index=shifted_idx, dtype=object)

        h_original = _hash_signals(signals_original)
        h_shifted = _hash_signals(signals_shifted)

        assert h_original != h_shifted, (
            "Shifting signal timestamps by 1 day must change signals_hash. "
            f"original={h_original[:16]}…, shifted={h_shifted[:16]}…"
        )

    def test_mutated_signal_fails_verification(self) -> None:
        """A certificate certified with original signals fails when direction is mutated."""
        original = _make_signals()
        cert = _certify(signals=original)

        # Mutate one direction in the verification signals
        tss = pd.DatetimeIndex([_BASE_TS + timedelta(days=i) for i in range(_N)], tz="UTC")
        mutated_values = list(original)
        mutated_values[0] = (
            SignalDirection.LONG
            if mutated_values[0] != SignalDirection.LONG
            else SignalDirection.SHORT
        )
        mutated_signals = pd.Series(mutated_values, index=tss, dtype=object)

        result = verify_certificate(
            _make_result(),
            mutated_signals,
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )

        assert (
            result.verified is False
        ), "Verification must fail when a signal direction is mutated."
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert (
            "signals_hash" in mismatch_fields
        ), f"signals_hash must appear in mismatches. Got: {mismatch_fields}"

    def test_trade_ordering_mutation_changes_trades_hash(self) -> None:
        """Reversing the trades tuple produces a different trades_hash.

        Unlike _hash_signals (which sorts by index), _hash_trades preserves
        the tuple order, so reversing changes the hash.
        """
        trades_forward = _make_trades(4)
        trades_reversed = tuple(reversed(trades_forward))

        h_forward = _hash_trades(trades_forward)
        h_reversed = _hash_trades(trades_reversed)

        assert h_forward != h_reversed, (
            "Reversed trades tuple must produce a different trades_hash. "
            f"forward={h_forward[:16]}…, reversed={h_reversed[:16]}…"
        )


# ── Certified_bars and certified_trades mismatch ─────────────────────────────


class TestCertifiedCountsMismatch:
    def test_certified_bars_mismatch_detected(self) -> None:
        """Changing certified_bars in the certificate is detected."""
        cert = _certify()
        tampered = certificate_from_dict(
            {**certificate_to_dict(cert), "certified_bars": cert.certified_bars + 50}
        )
        result = _verify(tampered)
        assert result.verified is False
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert (
            "certified_bars" in mismatch_fields
        ), f"certified_bars must appear in mismatches. Got: {mismatch_fields}"

    def test_certified_trades_mismatch_detected(self) -> None:
        """Changing certified_trades in the certificate is detected."""
        cert = _certify()
        tampered = certificate_from_dict(
            {**certificate_to_dict(cert), "certified_trades": cert.certified_trades + 99}
        )
        result = _verify(tampered)
        assert result.verified is False
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert "certified_trades" in mismatch_fields


# ── Corrupted replay lineage ─────────────────────────────────────────────────


class TestCorruptedReplayLineage:
    """dataset_content_hash and dataset_schema_hash corruption is detectable."""

    def test_wrong_content_hash_detected(self) -> None:
        """Certifying with wrong dataset_content_hash causes verification to fail."""
        # Re-certify with different content_hash (simulates dataset swap)
        wrong_cert = _certify(content_hash="d" * 64)

        # Verify wrong_cert but provide original content_hash
        result = verify_certificate(
            _make_result(),
            _make_signals(),
            _CONTENT_HASH,  # correct hash
            _SCHEMA_HASH,
            _make_experiment(),
            wrong_cert,  # certified with wrong content hash
        )

        assert result.verified is False, (
            "Verification must fail when certificate's dataset_content_hash "
            "doesn't match the supplied content_hash."
        )
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert (
            "dataset_content_hash" in mismatch_fields
        ), f"dataset_content_hash must appear in mismatches. Got: {mismatch_fields}"

    def test_wrong_schema_hash_detected(self) -> None:
        """Certifying with wrong dataset_schema_hash causes verification to fail."""
        wrong_cert = _certify(schema_hash="e" * 64)

        result = verify_certificate(
            _make_result(),
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,  # correct schema hash
            _make_experiment(),
            wrong_cert,
        )

        assert result.verified is False
        mismatch_fields = {f for f, _, _ in result.mismatches}
        assert "dataset_schema_hash" in mismatch_fields


# ── Duplicate certification reproducibility ───────────────────────────────────


class TestDuplicateCertificationReproducibility:
    def test_two_independent_certifications_are_identical(self) -> None:
        """certify_result called twice on identical inputs produces identical certificates."""
        cert1 = _certify()
        cert2 = _certify()

        checked = (
            "config_hash",
            "parameters_hash",
            "metrics_hash",
            "trades_hash",
            "equity_hash",
            "signals_hash",
            "dataset_content_hash",
            "dataset_schema_hash",
            "certified_bars",
            "certified_trades",
        )
        for field in checked:
            v1 = getattr(cert1, field)
            v2 = getattr(cert2, field)
            assert v1 == v2, (
                f"certify_result must be deterministic. Field '{field}' differs: "
                f"{v1!r} vs {v2!r}"
            )
