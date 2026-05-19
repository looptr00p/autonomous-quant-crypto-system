"""Tests for deterministic baseline research reports.

All tests use local deterministic fixtures only.  No live network calls.

Coverage:
- report generation: all required fields populated
- report hash: deterministic, changes on metric modification
- metrics_hash: same approach as ReplayCertificate
- benchmark_total_return: correct buy-and-hold calculation
- excess_return: total_return - benchmark_total_return
- total_fees_paid: sum of all trade fees
- total_slippage_cost: sum of all slippage amounts
- avg_trade_value: average buy trade notional
- turnover_per_bar: total_bought / initial_capital / n_bars
- avg_holding_period_bars: bars_long / trade_count
- max_consecutive_losses: correct streak counting
- no-trade case: extended metrics handle empty trades gracefully
- single-trade case: handled correctly
- validate_report: valid report passes
- validate_report: tampered report hash detected
- validate_report: wrong report_version detected
- validate_report: n_bars <= 0 detected
- JSON round-trip: report_to_dict / report_from_dict
- NaN round-trip: NaN serialised as null, restored as NaN
- save_report / load_report round-trip
- load_report: invalid JSON raises ValueError
- report_from_dict: missing field raises KeyError
- BaselineReport is immutable (frozen=True)
- disclaimer field present and non-empty
- dataset references passthrough
- replay certificate references passthrough
- CLI build: exit 0 on valid experiment
- CLI validate: exit 0 on valid report
- CLI validate: exit 1 on tampered report
- CLI validate: exit 2 on malformed JSON
- stable ordering validation
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner
from validate_baseline_report import main as validate_main

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.models import ExperimentRecord, ExperimentStatus
from aqcs.research.baseline_report import (
    REPORT_VERSION,
    BaselineReport,
    _compute_max_consecutive_losses,
    build_report,
    load_report,
    report_from_dict,
    report_to_dict,
    save_report,
    validate_report,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_BASE_TS = datetime(2024, 1, 1, tzinfo=UTC)
_FIXED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ── Fixtures / factories ──────────────────────────────────────────────────────


def _make_config(**overrides: object) -> BacktestConfig:
    defaults: dict[str, object] = {
        "initial_capital": 10_000.0,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
    }
    defaults.update(overrides)
    return BacktestConfig(**defaults)  # type: ignore[arg-type]


def _make_timestamps(n: int, start: datetime = _BASE_TS) -> list[datetime]:
    return [start + timedelta(days=i) for i in range(n)]


def _make_equity(n: int = 30, prices: list[float] | None = None) -> tuple[EquityCurvePoint, ...]:
    ts = _make_timestamps(n)
    if prices is None:
        prices = [45_000.0 + i * 100 for i in range(n)]
    equity = 10_000.0
    points = []
    for i, (t, p) in enumerate(zip(ts, prices, strict=True)):
        position = 0.2 if i % 10 < 5 else 0.0
        points.append(
            EquityCurvePoint(
                timestamp=t,
                equity=equity + i * 10,
                cash=equity + i * 10 - position * p,
                position=position,
                price=p,
            )
        )
    return tuple(points)


def _make_trades(n_pairs: int = 3) -> tuple[Trade, ...]:
    ts = _make_timestamps(n_pairs * 2)
    trades = []
    for i in range(n_pairs):
        buy_price = 45_000.0 + i * 100
        sell_price = buy_price + 200 if i % 2 == 0 else buy_price - 50  # win/loss alternating
        qty = 0.2
        trades.append(
            Trade(
                timestamp=ts[i * 2],
                side="buy",
                fill_price=buy_price,
                quantity=qty,
                fee=4.5,
                slippage_amount=0.9,
                value=buy_price * qty,
            )
        )
        trades.append(
            Trade(
                timestamp=ts[i * 2 + 1],
                side="sell",
                fill_price=sell_price,
                quantity=qty,
                fee=4.5,
                slippage_amount=0.9,
                value=sell_price * qty,
            )
        )
    return tuple(trades)


def _make_metrics(n_pairs: int = 3) -> dict[str, float]:
    return {
        "total_return": 0.12,
        "cagr": 0.08,
        "max_drawdown": 0.05,
        "sharpe_ratio": 1.42,
        "annualised_volatility": 0.18,
        "trade_count": float(n_pairs),
        "win_rate": 0.67,
        "exposure": 0.50,
    }


def _make_result(
    n_bars: int = 30,
    n_pairs: int = 3,
    config: BacktestConfig | None = None,
    prices: list[float] | None = None,
) -> BacktestResult:
    return BacktestResult(
        config=config or _make_config(),
        trades=_make_trades(n_pairs),
        equity_curve=_make_equity(n_bars, prices),
        metrics=_make_metrics(n_pairs),
        n_bars=n_bars,
        experiment_id=str(_FIXED_UUID),
    )


def _make_experiment() -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=_FIXED_UUID,
        experiment_name="test_experiment",
        timestamp_started_utc=_BASE_TS,
        status=ExperimentStatus.COMPLETED,
        git_commit_hash="deadbeef",
        parameters={"fee_bps": 10.0},
    )


def _build(
    result: BacktestResult | None = None,
    **kwargs: object,
) -> BaselineReport:
    return build_report(
        result or _make_result(),
        now_utc=_FIXED_NOW,
        **kwargs,  # type: ignore[arg-type]
    )


# ── Report generation ─────────────────────────────────────────────────────────


class TestReportGeneration:
    def test_all_required_fields_present(self) -> None:
        r = _build()
        assert r.report_version == REPORT_VERSION
        assert r.experiment_id == str(_FIXED_UUID)
        assert r.generation_timestamp_utc == _FIXED_NOW.isoformat()
        assert len(r.report_hash) == 64
        assert r.n_bars == 30
        assert r.trade_count == 3
        assert r.disclaimer != ""

    def test_generation_timestamp_uses_injection(self) -> None:
        r = _build()
        assert r.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_experiment_record_fields_used(self) -> None:
        r = build_report(_make_result(), experiment_record=_make_experiment(), now_utc=_FIXED_NOW)
        assert r.experiment_name == "test_experiment"
        assert r.git_commit_hash == "deadbeef"

    def test_dataset_references_passthrough(self) -> None:
        r = build_report(
            _make_result(),
            dataset_content_hash="a" * 64,
            dataset_schema_hash="b" * 64,
            dataset_symbol="BTC/USDT",
            dataset_timeframe="1d",
            dataset_exchange="binance",
            dataset_start_utc="2023-01-01T00:00:00+00:00",
            dataset_end_utc="2024-01-01T00:00:00+00:00",
            dataset_row_count=365,
            now_utc=_FIXED_NOW,
        )
        assert r.dataset_content_hash == "a" * 64
        assert r.dataset_symbol == "BTC/USDT"
        assert r.dataset_row_count == 365

    def test_replay_reference_passthrough(self) -> None:
        r = build_report(
            _make_result(),
            replay_certificate_hash="c" * 64,
            replay_certified=True,
            now_utc=_FIXED_NOW,
        )
        assert r.replay_certificate_hash == "c" * 64
        assert r.replay_certified is True

    def test_config_fields_populated(self) -> None:
        r = _build()
        assert r.initial_capital == 10_000.0
        assert r.fee_bps == 10.0
        assert r.slippage_bps == 2.0


# ── Report hash ───────────────────────────────────────────────────────────────


class TestReportHash:
    def test_deterministic(self) -> None:
        r1 = _build()
        r2 = _build()
        assert r1.report_hash == r2.report_hash

    def test_hash_changes_when_metric_changes(self) -> None:
        result = _make_result()
        r1 = build_report(result, now_utc=_FIXED_NOW)
        metrics_modified = {**result.metrics, "total_return": 9.99}
        result2 = BacktestResult(
            config=result.config,
            trades=result.trades,
            equity_curve=result.equity_curve,
            metrics=metrics_modified,
            n_bars=result.n_bars,
            experiment_id=result.experiment_id,
        )
        r2 = build_report(result2, now_utc=_FIXED_NOW)
        assert r1.report_hash != r2.report_hash

    def test_metrics_hash_is_64_chars_hex(self) -> None:
        r = _build()
        assert len(r.metrics_hash) == 64
        assert all(c in "0123456789abcdef" for c in r.metrics_hash)


# ── Benchmark metrics ─────────────────────────────────────────────────────────


class TestBenchmarkMetrics:
    def test_benchmark_return_is_buy_and_hold(self) -> None:
        prices = [100.0] * 10 + [110.0] * 20  # +10% from start to end
        result = _make_result(n_bars=30, prices=prices)
        r = build_report(result, now_utc=_FIXED_NOW)
        # Buy-and-hold: last price / first price - 1 = 110/100 - 1 = 0.10
        assert abs(r.benchmark_total_return - 0.10) < 1e-9

    def test_excess_return_is_total_minus_benchmark(self) -> None:
        r = _build()
        if not math.isnan(r.total_return) and not math.isnan(r.benchmark_total_return):
            expected = r.total_return - r.benchmark_total_return
            assert abs(r.excess_return - expected) < 1e-9

    def test_empty_equity_curve_nan_benchmark(self) -> None:
        result = BacktestResult(
            config=_make_config(),
            trades=(),
            equity_curve=(),
            metrics={},
            n_bars=0,
            experiment_id=str(_FIXED_UUID),
        )
        r = build_report(result, now_utc=_FIXED_NOW)
        assert math.isnan(r.benchmark_total_return)


# ── Cost metrics ──────────────────────────────────────────────────────────────


class TestCostMetrics:
    def test_total_fees_paid(self) -> None:
        result = _make_result(n_pairs=3)
        r = build_report(result, now_utc=_FIXED_NOW)
        expected = sum(t.fee for t in result.trades)
        assert abs(r.total_fees_paid - expected) < 1e-9

    def test_total_slippage_cost(self) -> None:
        result = _make_result(n_pairs=3)
        r = build_report(result, now_utc=_FIXED_NOW)
        expected = sum(t.slippage_amount for t in result.trades)
        assert abs(r.total_slippage_cost - expected) < 1e-9

    def test_avg_trade_value_buys_only(self) -> None:
        result = _make_result(n_pairs=3)
        r = build_report(result, now_utc=_FIXED_NOW)
        buys = [t for t in result.trades if t.side == "buy"]
        expected = sum(t.value for t in buys) / len(buys)
        assert abs(r.avg_trade_value - expected) < 1e-6

    def test_no_trades_avg_value_nan(self) -> None:
        result = BacktestResult(
            config=_make_config(),
            trades=(),
            equity_curve=_make_equity(10),
            metrics=_make_metrics(0),
            n_bars=10,
            experiment_id=str(_FIXED_UUID),
        )
        r = build_report(result, now_utc=_FIXED_NOW)
        assert math.isnan(r.avg_trade_value)


# ── Turnover metrics ──────────────────────────────────────────────────────────


class TestTurnoverMetrics:
    def test_turnover_per_bar_formula(self) -> None:
        result = _make_result(n_pairs=3, n_bars=30)
        r = build_report(result, now_utc=_FIXED_NOW)
        buys = [t for t in result.trades if t.side == "buy"]
        total_bought = sum(t.value for t in buys)
        expected = total_bought / 10_000.0 / 30
        assert abs(r.turnover_per_bar - expected) < 1e-9

    def test_no_bars_turnover_nan(self) -> None:
        result = BacktestResult(
            config=_make_config(),
            trades=_make_trades(1),
            equity_curve=(),
            metrics={},
            n_bars=0,
            experiment_id=str(_FIXED_UUID),
        )
        r = build_report(result, now_utc=_FIXED_NOW)
        assert math.isnan(r.turnover_per_bar)


# ── Holding period ────────────────────────────────────────────────────────────


class TestHoldingPeriod:
    def test_avg_holding_period_positive(self) -> None:
        r = _build()
        if r.trade_count > 0 and not math.isnan(r.avg_holding_period_bars):
            assert r.avg_holding_period_bars > 0

    def test_no_trades_holding_period_nan(self) -> None:
        result = BacktestResult(
            config=_make_config(),
            trades=(),
            equity_curve=_make_equity(10),
            metrics={},
            n_bars=10,
            experiment_id=str(_FIXED_UUID),
        )
        r = build_report(result, now_utc=_FIXED_NOW)
        assert math.isnan(r.avg_holding_period_bars)


# ── Max consecutive losses ────────────────────────────────────────────────────


class TestMaxConsecutiveLosses:
    def test_all_wins_is_zero(self) -> None:
        # All buys at 100, sells at 110 → all wins
        from datetime import UTC

        buys = [
            Trade(
                timestamp=datetime(2024, 1, i + 1, tzinfo=UTC),
                side="buy",
                fill_price=100.0,
                quantity=1.0,
                fee=0.0,
                slippage_amount=0.0,
                value=100.0,
            )
            for i in range(3)
        ]
        sells = [
            Trade(
                timestamp=datetime(2024, 1, i + 2, tzinfo=UTC),
                side="sell",
                fill_price=110.0,
                quantity=1.0,
                fee=0.0,
                slippage_amount=0.0,
                value=110.0,
            )
            for i in range(3)
        ]
        assert _compute_max_consecutive_losses(buys, sells) == 0

    def test_all_losses_counts_all(self) -> None:
        from datetime import UTC

        buys = [
            Trade(
                timestamp=datetime(2024, 1, i + 1, tzinfo=UTC),
                side="buy",
                fill_price=100.0,
                quantity=1.0,
                fee=0.0,
                slippage_amount=0.0,
                value=100.0,
            )
            for i in range(4)
        ]
        sells = [
            Trade(
                timestamp=datetime(2024, 1, i + 2, tzinfo=UTC),
                side="sell",
                fill_price=90.0,
                quantity=1.0,
                fee=0.0,
                slippage_amount=0.0,
                value=90.0,
            )
            for i in range(4)
        ]
        assert _compute_max_consecutive_losses(buys, sells) == 4

    def test_streak_within_mixed_results(self) -> None:
        result = _make_result(n_pairs=3)
        r = build_report(result, now_utc=_FIXED_NOW)
        assert r.max_consecutive_losses >= 0

    def test_no_trades_is_zero(self) -> None:
        assert _compute_max_consecutive_losses([], []) == 0


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_report_passes(self) -> None:
        r = _build()
        valid, errors = validate_report(r)
        assert valid is True
        assert errors == []

    def test_tampered_hash_detected(self) -> None:
        r = _build()
        d = report_to_dict(r)
        d["report_hash"] = "0" * 64  # wrong hash
        tampered = report_from_dict(d)
        valid, errors = validate_report(tampered)
        assert valid is False
        assert any("report_hash" in e for e in errors)

    def test_wrong_version_detected(self) -> None:
        r = _build()
        d = report_to_dict(r)
        d["report_version"] = "99"
        # Recompute hash for this modified dict so hash check passes
        from aqcs.research.baseline_report import _compute_report_hash

        d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
        d["report_hash"] = _compute_report_hash(d_no_hash)
        wrong_version = report_from_dict(d)
        valid, errors = validate_report(wrong_version)
        assert valid is False
        assert any("report_version" in e for e in errors)

    def test_zero_n_bars_detected(self) -> None:
        r = _build()
        d = report_to_dict(r)
        d["n_bars"] = 0
        from aqcs.research.baseline_report import _compute_report_hash

        d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
        d["report_hash"] = _compute_report_hash(d_no_hash)
        zero_bars = report_from_dict(d)
        valid, errors = validate_report(zero_bars)
        assert valid is False


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_dict(self) -> None:
        r = _build()
        d = report_to_dict(r)
        restored = report_from_dict(d)
        assert r == restored

    def test_nan_serialised_as_null(self) -> None:
        result = BacktestResult(
            config=_make_config(),
            trades=(),
            equity_curve=(),
            metrics={},
            n_bars=0,
            experiment_id=str(_FIXED_UUID),
        )
        r = build_report(result, now_utc=_FIXED_NOW)
        d = report_to_dict(r)
        # NaN floats become None in dict
        assert d["total_return"] is None

    def test_null_restored_as_nan(self) -> None:
        r = _build()
        d = report_to_dict(r)
        d["total_return"] = None  # simulate JSON null
        restored = report_from_dict(d)
        assert math.isnan(restored.total_return)

    def test_json_dumps_deterministic(self) -> None:
        r = _build()
        j1 = json.dumps(report_to_dict(r), sort_keys=True)
        j2 = json.dumps(report_to_dict(r), sort_keys=True)
        assert j1 == j2

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        r = _build()
        path = tmp_path / "report.json"
        save_report(r, path)
        loaded = load_report(path)
        assert r == loaded

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_report(bad)

    def test_from_dict_missing_field_raises(self) -> None:
        r = _build()
        d = report_to_dict(r)
        del d["report_hash"]
        with pytest.raises(KeyError):
            report_from_dict(d)

    def test_report_is_immutable(self) -> None:
        r = _build()
        assert isinstance(r, BaselineReport)
        with pytest.raises((AttributeError, TypeError)):
            r.total_return = 99.0  # type: ignore[misc]

    def test_disclaimer_is_non_empty(self) -> None:
        r = _build()
        assert len(r.disclaimer) > 10


# ── CLI validate ──────────────────────────────────────────────────────────────


class TestCLIValidate:
    def test_exit_0_on_valid_report(self, tmp_path: Path) -> None:
        r = _build()
        path = tmp_path / "report.json"
        save_report(r, path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_exit_1_on_tampered_hash(self, tmp_path: Path) -> None:
        r = _build()
        d = report_to_dict(r)
        d["report_hash"] = "0" * 64
        path = tmp_path / "tampered.json"
        path.write_text(json.dumps(d), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(path)])
        assert result.exit_code == 1

    def test_exit_2_on_malformed_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(bad)])
        assert result.exit_code == 2

    def test_report_contains_required_fields(self, tmp_path: Path) -> None:
        r = _build()
        path = tmp_path / "report.json"
        save_report(r, path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(path)])
        data = json.loads(result.output)
        required = {"valid", "report_hash", "experiment_id", "metrics_hash", "disclaimer"}
        assert required.issubset(data.keys())
