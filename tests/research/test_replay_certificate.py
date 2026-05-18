"""Deterministic replay certification tests.

Coverage:
- certify_result: all required fields populated
- certify_result: generation_timestamp_utc uses now_utc injection
- certify_result: default wall-clock now_utc when not injected
- config_hash is deterministic for same BacktestConfig
- config_hash changes when config differs
- parameters_hash is deterministic
- parameters_hash changes when parameters differ
- metrics_hash is deterministic
- metrics_hash changes when one metric value changes
- trades_hash is deterministic
- trades_hash changes when a trade value changes
- trades_hash changes when a trade timestamp changes
- equity_hash is deterministic
- equity_hash changes when an equity value changes
- signals_hash is deterministic
- signals_hash is order-stable (sorted index)
- signals_hash changes when a direction changes
- signals_hash changes when a timestamp changes
- dataset_content_hash passthrough verified
- dataset_schema_hash passthrough verified
- verify_certificate: clean pass
- verify_certificate: metrics_hash mismatch detected
- verify_certificate: trades_hash mismatch detected
- verify_certificate: equity_hash mismatch detected
- verify_certificate: signals_hash mismatch detected
- verify_certificate: config_hash mismatch detected
- verify_certificate: dataset_content_hash mismatch detected
- verify_certificate: dataset_schema_hash mismatch detected
- verify_certificate: certified_bars mismatch detected
- verify_certificate: certified_trades mismatch detected
- verify_certificate: mismatch lists expected and actual values
- JSON round-trip: certificate_to_dict / certificate_from_dict
- save_certificate / load_certificate round-trip
- load_certificate: invalid JSON raises ValueError
- certificate_from_dict: missing field raises KeyError
- certificate_dataclass: immutable (frozen=True)
- empty trades: hash is deterministic and does not crash
- empty equity curve: hash is deterministic
- empty signals: hash is deterministic
- two independent certify_result calls produce identical cert
- full pipeline integration: certify → verify → pass
- no-lookahead regression: signals_hash changes when lookahead bar is injected
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.models import ExperimentRecord, ExperimentStatus
from aqcs.research.replay_certificate import (
    CERTIFICATE_VERSION,
    CertificationVerificationResult,
    ReplayCertificate,
    _hash_config,
    _hash_equity_curve,
    _hash_metrics,
    _hash_signals,
    _hash_trades,
    certificate_from_dict,
    certificate_to_dict,
    certify_result,
    load_certificate,
    save_certificate,
    verify_certificate,
)
from aqcs.utils.events import SignalDirection

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_BASE_TS = datetime(2024, 1, 1, tzinfo=UTC)
_CONTENT_HASH = "a" * 64
_SCHEMA_HASH = "b" * 64
_N = 30  # bars
_FIXED_UUID = UUID("00000000-0000-0000-0000-000000000042")


# ── Fixtures / factories ──────────────────────────────────────────────────────


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
            else SignalDirection.NEUTRAL if i % 3 == 1 else SignalDirection.SHORT
        )
        for i in range(n)
    ]
    return pd.Series(directions, index=tss)


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


def _make_result(
    config: BacktestConfig | None = None,
    trades: tuple[Trade, ...] | None = None,
    equity_curve: tuple[EquityCurvePoint, ...] | None = None,
    metrics: dict[str, float] | None = None,
) -> BacktestResult:
    return BacktestResult(
        config=config or _make_config(),
        trades=trades if trades is not None else _make_trades(),
        equity_curve=equity_curve if equity_curve is not None else _make_equity(),
        metrics=metrics if metrics is not None else _make_metrics(),
        n_bars=_N,
        experiment_id="test-exp-id",
    )


def _make_experiment(parameters: dict | None = None) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=_FIXED_UUID,
        experiment_name="test_experiment",
        timestamp_started_utc=_BASE_TS,
        status=ExperimentStatus.COMPLETED,
        git_commit_hash="deadbeef",
        parameters=parameters or {"fee_bps": 10.0, "slippage_bps": 2.0},
    )


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
        now_utc=_FIXED_NOW,
    )


# ── certify_result: success path ──────────────────────────────────────────────


class TestCertifyResult:
    def test_all_required_fields_present(self) -> None:
        cert = _certify()
        assert cert.certificate_version == CERTIFICATE_VERSION
        assert cert.experiment_name == "test_experiment"
        assert cert.git_commit_hash == "deadbeef"
        assert cert.dataset_content_hash == _CONTENT_HASH
        assert cert.dataset_schema_hash == _SCHEMA_HASH
        assert len(cert.config_hash) == 64
        assert len(cert.parameters_hash) == 64
        assert len(cert.metrics_hash) == 64
        assert len(cert.trades_hash) == 64
        assert len(cert.equity_hash) == 64
        assert len(cert.signals_hash) == 64
        assert cert.certified_bars == _N
        assert cert.certified_trades == len(_make_trades())

    def test_generation_timestamp_uses_injection(self) -> None:
        cert = _certify()
        assert cert.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_default_now_utc_when_not_injected(self) -> None:
        before = datetime.now(UTC)
        cert = certify_result(
            _make_result(),
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
        )
        after = datetime.now(UTC)
        gen_ts = datetime.fromisoformat(cert.generation_timestamp_utc)
        assert before <= gen_ts <= after

    def test_dataset_hashes_are_passthrough(self) -> None:
        cert = certify_result(
            _make_result(),
            _make_signals(),
            "custom_content_hash",
            "custom_schema_hash",
            _make_experiment(),
            now_utc=_FIXED_NOW,
        )
        assert cert.dataset_content_hash == "custom_content_hash"
        assert cert.dataset_schema_hash == "custom_schema_hash"

    def test_certified_bars_matches_result_n_bars(self) -> None:
        result = _make_result()
        cert = _certify(result=result)
        assert cert.certified_bars == result.n_bars

    def test_certified_trades_matches_trade_count(self) -> None:
        trades = _make_trades(6)
        result = _make_result(trades=trades)
        cert = _certify(result=result)
        assert cert.certified_trades == 6


# ── config_hash ───────────────────────────────────────────────────────────────


class TestConfigHash:
    def test_deterministic(self) -> None:
        config = _make_config()
        assert _hash_config(config) == _hash_config(config)

    def test_same_config_same_hash(self) -> None:
        c1 = _make_config()
        c2 = _make_config()
        assert _hash_config(c1) == _hash_config(c2)

    def test_different_fee_different_hash(self) -> None:
        c1 = _make_config(fee_bps=10.0)
        c2 = _make_config(fee_bps=20.0)
        assert _hash_config(c1) != _hash_config(c2)

    def test_different_capital_different_hash(self) -> None:
        c1 = _make_config(initial_capital=10_000.0)
        c2 = _make_config(initial_capital=50_000.0)
        assert _hash_config(c1) != _hash_config(c2)

    def test_hex_length(self) -> None:
        assert len(_hash_config(_make_config())) == 64


# ── metrics_hash ──────────────────────────────────────────────────────────────


class TestMetricsHash:
    def test_deterministic(self) -> None:
        m = _make_metrics()
        assert _hash_metrics(m) == _hash_metrics(m)

    def test_value_change_detected(self) -> None:
        m1 = _make_metrics()
        m2 = {**m1, "sharpe_ratio": 9.99}
        assert _hash_metrics(m1) != _hash_metrics(m2)

    def test_key_addition_detected(self) -> None:
        m1 = _make_metrics()
        m2 = {**m1, "extra_metric": 1.0}
        assert _hash_metrics(m1) != _hash_metrics(m2)

    def test_empty_metrics_deterministic(self) -> None:
        assert _hash_metrics({}) == _hash_metrics({})

    def test_key_ordering_irrelevant(self) -> None:
        m1 = {"a": 1.0, "b": 2.0}
        m2 = {"b": 2.0, "a": 1.0}
        assert _hash_metrics(m1) == _hash_metrics(m2)


# ── trades_hash ───────────────────────────────────────────────────────────────


class TestTradesHash:
    def test_deterministic(self) -> None:
        t = _make_trades()
        assert _hash_trades(t) == _hash_trades(t)

    def test_value_corruption_detected(self) -> None:
        trades = _make_trades(2)
        corrupted = (
            Trade(
                timestamp=trades[0].timestamp,
                side=trades[0].side,
                fill_price=trades[0].fill_price + 1.0,  # changed
                quantity=trades[0].quantity,
                fee=trades[0].fee,
                slippage_amount=trades[0].slippage_amount,
                value=trades[0].value,
            ),
            trades[1],
        )
        assert _hash_trades(trades) != _hash_trades(corrupted)

    def test_timestamp_change_detected(self) -> None:
        trades = _make_trades(2)
        altered = (
            Trade(
                timestamp=trades[0].timestamp + timedelta(days=1),  # shifted
                side=trades[0].side,
                fill_price=trades[0].fill_price,
                quantity=trades[0].quantity,
                fee=trades[0].fee,
                slippage_amount=trades[0].slippage_amount,
                value=trades[0].value,
            ),
            trades[1],
        )
        assert _hash_trades(trades) != _hash_trades(altered)

    def test_extra_trade_detected(self) -> None:
        t2 = _make_trades(2)
        t3 = _make_trades(3)
        assert _hash_trades(t2) != _hash_trades(t3)

    def test_empty_trades_deterministic(self) -> None:
        assert _hash_trades(()) == _hash_trades(())

    def test_empty_and_nonempty_differ(self) -> None:
        assert _hash_trades(()) != _hash_trades(_make_trades(1))


# ── equity_hash ───────────────────────────────────────────────────────────────


class TestEquityHash:
    def test_deterministic(self) -> None:
        eq = _make_equity()
        assert _hash_equity_curve(eq) == _hash_equity_curve(eq)

    def test_equity_value_change_detected(self) -> None:
        eq = list(_make_equity())
        pt = eq[0]
        altered = (
            EquityCurvePoint(
                timestamp=pt.timestamp,
                equity=pt.equity + 1.0,  # corrupted
                cash=pt.cash,
                position=pt.position,
                price=pt.price,
            ),
            *eq[1:],
        )
        assert _hash_equity_curve(_make_equity()) != _hash_equity_curve(tuple(altered))

    def test_empty_equity_deterministic(self) -> None:
        assert _hash_equity_curve(()) == _hash_equity_curve(())


# ── signals_hash ──────────────────────────────────────────────────────────────


class TestSignalsHash:
    def test_deterministic(self) -> None:
        s = _make_signals()
        assert _hash_signals(s) == _hash_signals(s)

    def test_shuffled_index_same_hash(self) -> None:
        s = _make_signals()
        s_shuffled = s.sample(frac=1, random_state=42)
        assert _hash_signals(s) == _hash_signals(s_shuffled)

    def test_direction_change_detected(self) -> None:
        s1 = _make_signals()
        s2 = s1.copy()
        s2.iloc[0] = SignalDirection.SHORT  # was LONG
        assert _hash_signals(s1) != _hash_signals(s2)

    def test_timestamp_shift_detected(self) -> None:
        s = _make_signals()
        s_shifted = s.copy()
        s_shifted.index = s_shifted.index + pd.Timedelta(days=1)
        assert _hash_signals(s) != _hash_signals(s_shifted)

    def test_extra_bar_detected(self) -> None:
        s1 = _make_signals(_N)
        s2 = _make_signals(_N + 1)
        assert _hash_signals(s1) != _hash_signals(s2)

    def test_empty_signals_deterministic(self) -> None:
        empty = pd.Series(dtype=object)
        assert _hash_signals(empty) == _hash_signals(empty)


# ── verify_certificate ────────────────────────────────────────────────────────


class TestVerifyCertificate:
    def test_clean_pass(self) -> None:
        cert = _certify()
        result = verify_certificate(
            _make_result(),
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert isinstance(result, CertificationVerificationResult)
        assert result.verified is True
        assert result.mismatches == []

    def test_metrics_mismatch_detected(self) -> None:
        cert = _certify()
        bad_metrics = {**_make_metrics(), "sharpe_ratio": 9.99}
        result_corrupted = _make_result(metrics=bad_metrics)
        vresult = verify_certificate(
            result_corrupted,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "metrics_hash" in fields

    def test_trades_mismatch_detected(self) -> None:
        trades = _make_trades()
        cert = _certify(result=_make_result(trades=trades))
        corrupted_trade = Trade(
            timestamp=trades[0].timestamp,
            side=trades[0].side,
            fill_price=trades[0].fill_price * 2,
            quantity=trades[0].quantity,
            fee=trades[0].fee,
            slippage_amount=trades[0].slippage_amount,
            value=trades[0].value,
        )
        bad_result = _make_result(trades=(corrupted_trade,) + trades[1:])
        vresult = verify_certificate(
            bad_result,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "trades_hash" in fields

    def test_equity_mismatch_detected(self) -> None:
        eq = _make_equity()
        cert = _certify(result=_make_result(equity_curve=eq))
        eq_list = list(eq)
        pt = eq_list[0]
        corrupted = (
            EquityCurvePoint(
                timestamp=pt.timestamp,
                equity=pt.equity * 2,
                cash=pt.cash,
                position=pt.position,
                price=pt.price,
            ),
            *eq_list[1:],
        )
        bad_result = _make_result(equity_curve=tuple(corrupted))
        vresult = verify_certificate(
            bad_result,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "equity_hash" in fields

    def test_signals_mismatch_detected(self) -> None:
        signals = _make_signals()
        cert = _certify(signals=signals)
        bad_signals = signals.copy()
        bad_signals.iloc[0] = SignalDirection.SHORT
        vresult = verify_certificate(
            _make_result(),
            bad_signals,
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "signals_hash" in fields

    def test_config_mismatch_detected(self) -> None:
        cert = _certify(result=_make_result(config=_make_config(fee_bps=10.0)))
        bad_result = _make_result(config=_make_config(fee_bps=20.0))
        vresult = verify_certificate(
            bad_result,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "config_hash" in fields

    def test_dataset_content_hash_mismatch_detected(self) -> None:
        cert = _certify(content_hash="original" + "a" * 57)
        vresult = verify_certificate(
            _make_result(),
            _make_signals(),
            "different" + "b" * 55,  # different content hash
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "dataset_content_hash" in fields

    def test_dataset_schema_hash_mismatch_detected(self) -> None:
        cert = _certify(schema_hash="original" + "a" * 56)
        vresult = verify_certificate(
            _make_result(),
            _make_signals(),
            _CONTENT_HASH,
            "different" + "b" * 55,  # different schema hash
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "dataset_schema_hash" in fields

    def test_certified_bars_mismatch_detected(self) -> None:
        cert = _certify()
        # Provide a result with a different n_bars
        bad_result = BacktestResult(
            config=_make_result().config,
            trades=_make_trades(),
            equity_curve=_make_equity(),
            metrics=_make_metrics(),
            n_bars=_N + 10,  # different
            experiment_id="test-exp-id",
        )
        vresult = verify_certificate(
            bad_result,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "certified_bars" in fields

    def test_mismatch_contains_expected_and_actual(self) -> None:
        cert = _certify()
        bad_metrics = {**_make_metrics(), "total_return": 999.0}
        vresult = verify_certificate(
            _make_result(metrics=bad_metrics),
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        mmap = {f: (e, a) for f, e, a in vresult.mismatches}
        expected_h, actual_h = mmap["metrics_hash"]
        assert expected_h == cert.metrics_hash
        assert actual_h != cert.metrics_hash


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_dict(self) -> None:
        cert = _certify()
        d = certificate_to_dict(cert)
        restored = certificate_from_dict(d)
        assert cert == restored

    def test_json_dumps_deterministic(self) -> None:
        cert = _certify()
        j1 = json.dumps(certificate_to_dict(cert), sort_keys=True)
        j2 = json.dumps(certificate_to_dict(cert), sort_keys=True)
        assert j1 == j2

    def test_all_fields_json_serializable(self) -> None:
        cert = _certify()
        serialized = json.dumps(certificate_to_dict(cert), sort_keys=True)
        parsed = json.loads(serialized)
        assert parsed["certificate_version"] == CERTIFICATE_VERSION

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        cert = _certify()
        path = tmp_path / "cert.json"
        save_certificate(cert, path)
        loaded = load_certificate(path)
        assert cert == loaded

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_certificate(bad)

    def test_from_dict_missing_field_raises(self) -> None:
        cert = _certify()
        d = certificate_to_dict(cert)
        del d["metrics_hash"]
        with pytest.raises(KeyError):
            certificate_from_dict(d)

    def test_certificate_is_immutable(self) -> None:
        cert = _certify()
        assert isinstance(cert, ReplayCertificate)
        with pytest.raises((AttributeError, TypeError)):
            cert.metrics_hash = "tampered"  # type: ignore[misc]


# ── Deterministic replay ──────────────────────────────────────────────────────


class TestDeterministicReplay:
    def test_two_calls_identical(self) -> None:
        c1 = _certify()
        c2 = _certify()
        assert c1 == c2

    def test_json_replay_identical(self) -> None:
        c1 = _certify()
        c2 = _certify()
        j1 = json.dumps(certificate_to_dict(c1), sort_keys=True)
        j2 = json.dumps(certificate_to_dict(c2), sort_keys=True)
        assert j1 == j2

    def test_stable_after_save_load(self, tmp_path: Path) -> None:
        cert = _certify()
        path = tmp_path / "c.json"
        save_certificate(cert, path)
        loaded = load_certificate(path)
        assert loaded.metrics_hash == cert.metrics_hash
        assert loaded.trades_hash == cert.trades_hash
        assert loaded.signals_hash == cert.signals_hash


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_trades(self) -> None:
        result = _make_result(trades=())
        cert = certify_result(
            result,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            now_utc=_FIXED_NOW,
        )
        assert cert.certified_trades == 0
        assert len(cert.trades_hash) == 64

    def test_empty_equity_curve(self) -> None:
        result = BacktestResult(
            config=_make_config(),
            trades=(),
            equity_curve=(),
            metrics=_make_metrics(),
            n_bars=0,
            experiment_id="",
        )
        cert = certify_result(
            result,
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            now_utc=_FIXED_NOW,
        )
        assert len(cert.equity_hash) == 64

    def test_empty_signals(self) -> None:
        empty = pd.Series(dtype=object)
        cert = certify_result(
            _make_result(),
            empty,
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            now_utc=_FIXED_NOW,
        )
        assert len(cert.signals_hash) == 64

    def test_empty_parameters(self) -> None:
        exp = _make_experiment(parameters={})
        cert = certify_result(
            _make_result(),
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            exp,
            now_utc=_FIXED_NOW,
        )
        assert len(cert.parameters_hash) == 64


# ── No-lookahead regression ───────────────────────────────────────────────────


class TestNoLookaheadRegression:
    def test_signals_hash_changes_when_lookahead_bar_injected(self) -> None:
        """Injecting a signal at T=0 (before any data) must change signals_hash.

        This guards against a scenario where a lookahead bar is silently
        prepended to the signal series — the certification must detect it.
        """
        signals = _make_signals()
        cert_clean = _certify(signals=signals)

        # Inject a lookahead bar one day before the first bar
        pre_ts = signals.index[0] - pd.Timedelta(days=1)
        lookahead_signals = pd.concat(
            [
                pd.Series([SignalDirection.LONG], index=[pre_ts]),
                signals,
            ]
        )
        cert_lookahead = _certify(signals=lookahead_signals)

        assert cert_clean.signals_hash != cert_lookahead.signals_hash

    def test_metric_change_invalidates_certificate(self) -> None:
        """A single metric change must be detected by the certification."""
        cert = _certify()
        bad = {**_make_metrics(), "max_drawdown": -0.99}
        vresult = verify_certificate(
            _make_result(metrics=bad),
            _make_signals(),
            _CONTENT_HASH,
            _SCHEMA_HASH,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False

    def test_dataset_swap_detected(self) -> None:
        """Swapping dataset hashes must be detected during verification."""
        cert = _certify(content_hash="aaa" + "a" * 61, schema_hash="bbb" + "b" * 61)
        vresult = verify_certificate(
            _make_result(),
            _make_signals(),
            "ccc" + "c" * 61,  # different dataset
            "bbb" + "b" * 61,
            _make_experiment(),
            cert,
        )
        assert vresult.verified is False
        fields = [f for f, _, _ in vresult.mismatches]
        assert "dataset_content_hash" in fields


# ── Full pipeline integration ─────────────────────────────────────────────────


class TestPipelineIntegration:
    def test_certify_then_verify_passes(self) -> None:
        """End-to-end: certify a result, verify it immediately, expect pass."""
        result = _make_result()
        signals = _make_signals()
        experiment = _make_experiment()

        cert = certify_result(
            result,
            signals,
            _CONTENT_HASH,
            _SCHEMA_HASH,
            experiment,
            now_utc=_FIXED_NOW,
        )
        vresult = verify_certificate(
            result,
            signals,
            _CONTENT_HASH,
            _SCHEMA_HASH,
            experiment,
            cert,
        )
        assert vresult.verified is True
        assert vresult.mismatches == []

    def test_certify_save_load_verify(self, tmp_path: Path) -> None:
        """Save certificate to disk, reload, verify — all hashes survive round-trip."""
        result = _make_result()
        signals = _make_signals()
        experiment = _make_experiment()

        cert = certify_result(
            result, signals, _CONTENT_HASH, _SCHEMA_HASH, experiment, now_utc=_FIXED_NOW
        )
        cert_path = tmp_path / "cert.json"
        save_certificate(cert, cert_path)
        loaded_cert = load_certificate(cert_path)

        vresult = verify_certificate(
            result,
            signals,
            _CONTENT_HASH,
            _SCHEMA_HASH,
            experiment,
            loaded_cert,
        )
        assert vresult.verified is True

    def test_any_mutation_fails_verification(self) -> None:
        """Mutating ANY deterministic field must fail verification."""
        result = _make_result()
        signals = _make_signals()
        experiment = _make_experiment()

        cert = certify_result(
            result, signals, _CONTENT_HASH, _SCHEMA_HASH, experiment, now_utc=_FIXED_NOW
        )

        # Mutate metrics
        bad_result = _make_result(metrics={**_make_metrics(), "trade_count": 99.0})
        vresult = verify_certificate(
            bad_result, signals, _CONTENT_HASH, _SCHEMA_HASH, experiment, cert
        )
        assert vresult.verified is False
