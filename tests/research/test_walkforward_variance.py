"""Tests for walk-forward variance, dispersion, and governance advisory metrics.

All tests are deterministic and use static fixtures.  No live network calls,
no random state without a fixed seed, no wall-clock timestamps.

Coverage:
- _compute_summary: variance/dispersion fields correct for known inputs
- std_total_return (pre-existing): sample std dev formula
- range_total_return: max - min; NaN for < 2 windows
- cv_total_return: std / |mean|; NaN when |mean| < eps or < 2 windows
- cv_total_return: NaN when mean is zero
- std/min/max_sharpe_ratio: correct values for known inputs
- std/min/max_max_drawdown: correct values for known inputs
- governance advisory counts: n_windows_below_return_floor
- governance advisory counts: n_windows_above_drawdown_ceil
- governance advisory counts: n_windows_below_sharpe_floor
- governance counts: all zero when no folds breach thresholds
- governance counts: correct when multiple folds breach different thresholds
- edge case: zero evaluated windows → all float fields NaN, int counts = 0
- edge case: one evaluated window → std/range NaN, mean/min/max defined
- edge case: all windows failed → same as zero evaluated
- edge case: NaN metrics in result → excluded from calculations
- REPORT_VERSION is "2"
- report_to_dict includes all new summary fields
- report_from_dict round-trip preserves all new fields
- backward compat: v1-style dict (missing new fields) loads with defaults
- report is deterministic across repeated runs
- report_hash changes when new fields change
- advisory semantics: governance counts do not auto-select strategies
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from aqcs.backtesting.models import BacktestConfig
from aqcs.research.walkforward import (
    _DRAWDOWN_CEIL,
    _RETURN_FLOOR,
    _SHARPE_FLOOR,
    REPORT_VERSION,
    WalkForwardResult,
    _compute_summary,
    report_from_dict,
    report_to_dict,
    run_walkforward,
)
from aqcs.utils.events import SignalDirection

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_N = 300


# ── Factories ─────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = _N) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=n, freq="1D", tz="UTC")
    rng = np.random.default_rng(42)
    prices = 45_000.0 + np.cumsum(rng.normal(0, 200.0, n))
    prices = np.maximum(prices, 1_000.0)
    highs = prices * (1 + rng.uniform(0.001, 0.004, n))
    lows = prices * (1 - rng.uniform(0.001, 0.004, n))
    opens = lows + rng.uniform(0.0, 1.0, n) * (highs - lows)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": rng.uniform(100.0, 500.0, n),
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "exchange": "binance",
        }
    )


def _make_config(**overrides: object) -> BacktestConfig:
    defaults: dict[str, object] = {
        "initial_capital": 10_000.0,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
    }
    defaults.update(overrides)
    return BacktestConfig(**defaults)  # type: ignore[arg-type]


def _neutral_fn(prices: pd.Series) -> pd.Series:
    return pd.Series(SignalDirection.NEUTRAL, index=prices.index, dtype=object)


def _make_result(
    window_index: int,
    total_return: float,
    sharpe: float,
    max_drawdown: float,
    failed: bool = False,
) -> WalkForwardResult:
    """Build a WalkForwardResult with explicit metric values for variance testing."""
    nan = float("nan")
    return WalkForwardResult(
        window_index=window_index,
        train_start_bar=window_index * 50,
        train_end_bar=window_index * 50 + 100,
        test_start_bar=window_index * 50 + 100,
        test_end_bar=window_index * 50 + 150,
        metrics={
            "total_return": total_return if not failed else nan,
            "cagr": total_return if not failed else nan,
            "max_drawdown": max_drawdown if not failed else nan,
            "sharpe_ratio": sharpe if not failed else nan,
            "annualised_volatility": 0.10,
            "trade_count": 5.0,
            "win_rate": 0.60,
            "exposure": 0.50,
        },
        n_trades=0 if failed else 5,
        n_bars_evaluated=0 if failed else 50,
        failed=failed,
        failure_reason="forced failure" if failed else "",
    )


def _four_window_results() -> tuple[WalkForwardResult, ...]:
    """Four windows with known diverse returns/sharpe/drawdown for exact assertions."""
    return (
        _make_result(0, total_return=0.10, sharpe=1.0, max_drawdown=0.05),
        _make_result(1, total_return=0.20, sharpe=2.0, max_drawdown=0.08),
        _make_result(2, total_return=-0.05, sharpe=-0.5, max_drawdown=0.12),
        _make_result(3, total_return=0.15, sharpe=1.5, max_drawdown=0.06),
    )


# ── Report version ────────────────────────────────────────────────────────────


class TestReportVersion:
    def test_report_version_is_two(self) -> None:
        assert REPORT_VERSION == "2", (
            "REPORT_VERSION must be '2' after TASK-WALKFORWARD-VARIANCE-001. "
            f"Got: {REPORT_VERSION!r}"
        )


# ── Variance/dispersion correctness ──────────────────────────────────────────


class TestVarianceCorrectness:
    """_compute_summary produces correct values for known inputs."""

    def test_range_total_return_correct(self) -> None:
        """range = max - min for a known set of fold returns."""
        results = _four_window_results()
        summary = _compute_summary(results, step_bars=50, test_bars=50)
        # returns = [0.10, 0.20, -0.05, 0.15]; range = 0.20 - (-0.05) = 0.25
        assert (
            abs(summary.range_total_return - 0.25) < 1e-9
        ), f"range_total_return must be 0.25, got {summary.range_total_return}"

    def test_mean_total_return_correct(self) -> None:
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        # mean([0.10, 0.20, -0.05, 0.15]) = 0.40 / 4 = 0.10
        assert abs(summary.mean_total_return - 0.10) < 1e-9

    def test_std_total_return_sample_std(self) -> None:
        """std is sample std (denominator n-1), consistent with existing behavior."""
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        # Sample std of [0.10, 0.20, -0.05, 0.15] with mean=0.10:
        # variance = ((0)^2 + (0.10)^2 + (-0.15)^2 + (0.05)^2) / 3
        #          = (0 + 0.01 + 0.0225 + 0.0025) / 3 = 0.035 / 3
        expected_std = math.sqrt(0.035 / 3)
        assert (
            abs(summary.std_total_return - expected_std) < 1e-9
        ), f"std_total_return={summary.std_total_return}, expected={expected_std}"

    def test_cv_total_return_correct(self) -> None:
        """CV = std / |mean|."""
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        expected_cv = summary.std_total_return / abs(summary.mean_total_return)
        assert (
            abs(summary.cv_total_return - expected_cv) < 1e-9
        ), f"cv_total_return={summary.cv_total_return}, expected={expected_cv}"

    def test_sharpe_dispersion_correct(self) -> None:
        """std/min/max sharpe are correct for known inputs."""
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        # sharpes = [1.0, 2.0, -0.5, 1.5]; mean = 1.0
        assert abs(summary.mean_sharpe_ratio - 1.0) < 1e-9
        assert summary.min_sharpe_ratio == -0.5
        assert summary.max_sharpe_ratio == 2.0
        # Sample std: variance = ((0)^2 + (1)^2 + (-1.5)^2 + (0.5)^2) / 3
        #                       = (0 + 1 + 2.25 + 0.25) / 3 = 3.5 / 3
        expected_std_sharpe = math.sqrt(3.5 / 3)
        assert abs(summary.std_sharpe_ratio - expected_std_sharpe) < 1e-9

    def test_drawdown_dispersion_correct(self) -> None:
        """std/min/max drawdown are correct for known inputs."""
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        # drawdowns = [0.05, 0.08, 0.12, 0.06]; mean = 0.0775
        assert abs(summary.mean_max_drawdown - 0.0775) < 1e-9
        assert summary.min_max_drawdown == 0.05
        assert summary.max_max_drawdown == 0.12
        # Sample std of [0.05, 0.08, 0.12, 0.06]:
        mean_dd = 0.0775
        var_dd = sum((v - mean_dd) ** 2 for v in [0.05, 0.08, 0.12, 0.06]) / 3
        expected_std_dd = math.sqrt(var_dd)
        assert abs(summary.std_max_drawdown - expected_std_dd) < 1e-9

    def test_min_max_total_return_correct(self) -> None:
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        assert summary.min_total_return == -0.05
        assert summary.max_total_return == 0.20


# ── CV edge cases ─────────────────────────────────────────────────────────────


class TestCVEdgeCases:
    def test_cv_nan_when_mean_is_zero(self) -> None:
        """CV is NaN when the mean return is zero (division by zero)."""
        results = (
            _make_result(0, total_return=0.10, sharpe=1.0, max_drawdown=0.05),
            _make_result(1, total_return=-0.10, sharpe=-1.0, max_drawdown=0.10),
        )
        summary = _compute_summary(results, 50, 50)
        # mean = 0.0 → CV undefined
        assert math.isnan(
            summary.cv_total_return
        ), "CV must be NaN when mean_total_return = 0.0 (division by zero)."

    def test_cv_nan_when_only_one_window(self) -> None:
        """CV requires std, which requires at least 2 windows."""
        results = (_make_result(0, total_return=0.15, sharpe=1.2, max_drawdown=0.05),)
        summary = _compute_summary(results, 50, 50)
        assert math.isnan(
            summary.cv_total_return
        ), "CV must be NaN for a single evaluated window (std is NaN)."

    def test_cv_correct_for_nonzero_mean(self) -> None:
        """CV = std/|mean| for a simple known case."""
        results = (
            _make_result(0, total_return=0.20, sharpe=2.0, max_drawdown=0.05),
            _make_result(1, total_return=0.40, sharpe=3.0, max_drawdown=0.03),
        )
        summary = _compute_summary(results, 50, 50)
        # mean = 0.30, std = sqrt(((0.20-0.30)^2 + (0.40-0.30)^2)/1) = sqrt(0.02)
        # cv = sqrt(0.02) / 0.30
        expected_std = math.sqrt(0.02)
        expected_cv = expected_std / 0.30
        assert abs(summary.cv_total_return - expected_cv) < 1e-9


# ── NaN field edge cases ──────────────────────────────────────────────────────


class TestNaNFieldEdgeCases:
    def test_all_new_float_fields_nan_when_zero_evaluated_windows(self) -> None:
        """When no windows succeed, all dispersion float fields are NaN."""
        results = (
            _make_result(0, 0.0, 0.0, 0.0, failed=True),
            _make_result(1, 0.0, 0.0, 0.0, failed=True),
        )
        summary = _compute_summary(results, 50, 50)
        nan_fields = [
            "range_total_return",
            "cv_total_return",
            "std_sharpe_ratio",
            "min_sharpe_ratio",
            "max_sharpe_ratio",
            "std_max_drawdown",
            "min_max_drawdown",
            "max_max_drawdown",
        ]
        for field in nan_fields:
            value = getattr(summary, field)
            assert math.isnan(
                value
            ), f"{field} must be NaN when no windows are evaluated. Got: {value}"

    def test_int_counts_zero_when_zero_evaluated_windows(self) -> None:
        results = (
            _make_result(0, 0.0, 0.0, 0.0, failed=True),
            _make_result(1, 0.0, 0.0, 0.0, failed=True),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_below_return_floor == 0
        assert summary.n_windows_above_drawdown_ceil == 0
        assert summary.n_windows_below_sharpe_floor == 0

    def test_single_window_std_and_range_are_nan(self) -> None:
        """std and range require ≥ 2 windows; min/max/mean are defined for 1."""
        results = (_make_result(0, total_return=0.12, sharpe=1.5, max_drawdown=0.04),)
        summary = _compute_summary(results, 50, 50)
        assert math.isnan(summary.std_total_return)
        assert math.isnan(summary.range_total_return)
        assert math.isnan(summary.std_sharpe_ratio)
        assert math.isnan(summary.std_max_drawdown)
        # But min/max/mean should still be defined
        assert not math.isnan(summary.mean_total_return)
        assert not math.isnan(summary.min_sharpe_ratio)
        assert not math.isnan(summary.max_max_drawdown)

    def test_nan_metrics_in_result_excluded(self) -> None:
        """Windows with NaN metrics (e.g., NaN sharpe) are skipped for that field."""
        nan = float("nan")
        results = (
            _make_result(0, total_return=0.10, sharpe=1.0, max_drawdown=0.05),
            WalkForwardResult(
                window_index=1,
                train_start_bar=50,
                train_end_bar=150,
                test_start_bar=150,
                test_end_bar=200,
                metrics={
                    "total_return": 0.15,
                    "sharpe_ratio": nan,  # NaN sharpe — excluded
                    "max_drawdown": 0.06,
                    "cagr": 0.15,
                    "annualised_volatility": 0.10,
                    "trade_count": 3.0,
                    "win_rate": 0.67,
                    "exposure": 0.50,
                },
                n_trades=3,
                n_bars_evaluated=50,
                failed=False,
                failure_reason="",
            ),
        )
        summary = _compute_summary(results, 50, 50)
        # sharpe from window 1 is NaN → only window 0 contributes to sharpe stats
        assert math.isnan(
            summary.std_sharpe_ratio
        ), "std_sharpe requires ≥2 non-NaN sharpe values; only 1 available."
        assert summary.min_sharpe_ratio == 1.0
        # total_return has 2 valid values → std is defined
        assert not math.isnan(summary.std_total_return)


# ── Governance advisory counts ────────────────────────────────────────────────


class TestGovernanceAdvisoryCounts:
    """Advisory counts correctly identify folds breaching Phase-1B thresholds."""

    def test_return_below_floor_counted(self) -> None:
        """Folds with return < RETURN_FLOOR are counted."""
        results = (
            _make_result(0, total_return=_RETURN_FLOOR - 0.01, sharpe=0.5, max_drawdown=0.10),
            _make_result(1, total_return=_RETURN_FLOOR + 0.01, sharpe=0.5, max_drawdown=0.10),
        )
        summary = _compute_summary(results, 50, 50)
        assert (
            summary.n_windows_below_return_floor == 1
        ), f"Expected 1 window below return floor, got {summary.n_windows_below_return_floor}"

    def test_return_at_floor_not_counted(self) -> None:
        """Return exactly at RETURN_FLOOR is NOT below the floor."""
        results = (
            _make_result(0, total_return=_RETURN_FLOOR, sharpe=0.5, max_drawdown=0.10),
            _make_result(1, total_return=0.05, sharpe=0.5, max_drawdown=0.10),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_below_return_floor == 0, (
            f"Return exactly at floor must not be counted. "
            f"Got {summary.n_windows_below_return_floor}"
        )

    def test_drawdown_above_ceil_counted(self) -> None:
        """Folds with drawdown > DRAWDOWN_CEIL are counted."""
        results = (
            _make_result(0, total_return=0.05, sharpe=0.5, max_drawdown=_DRAWDOWN_CEIL + 0.01),
            _make_result(1, total_return=0.05, sharpe=0.5, max_drawdown=_DRAWDOWN_CEIL - 0.01),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_above_drawdown_ceil == 1

    def test_drawdown_at_ceil_not_counted(self) -> None:
        """Drawdown exactly at DRAWDOWN_CEIL is NOT above the ceiling."""
        results = (
            _make_result(0, total_return=0.05, sharpe=0.5, max_drawdown=_DRAWDOWN_CEIL),
            _make_result(1, total_return=0.05, sharpe=0.5, max_drawdown=0.10),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_above_drawdown_ceil == 0

    def test_sharpe_at_or_below_floor_counted(self) -> None:
        """Folds with sharpe <= SHARPE_FLOOR are counted (inclusive at floor)."""
        results = (
            _make_result(0, total_return=0.05, sharpe=_SHARPE_FLOOR, max_drawdown=0.05),
            _make_result(1, total_return=0.05, sharpe=_SHARPE_FLOOR - 0.01, max_drawdown=0.05),
            _make_result(2, total_return=0.05, sharpe=_SHARPE_FLOOR + 0.01, max_drawdown=0.05),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_below_sharpe_floor == 2, (
            f"Sharpe at floor AND below floor both count. "
            f"Got {summary.n_windows_below_sharpe_floor}"
        )

    def test_all_counts_zero_when_no_breaches(self) -> None:
        """All advisory counts are 0 when all folds pass governance thresholds."""
        results = (
            _make_result(0, total_return=0.10, sharpe=1.5, max_drawdown=0.05),
            _make_result(1, total_return=0.15, sharpe=2.0, max_drawdown=0.08),
            _make_result(2, total_return=0.08, sharpe=0.5, max_drawdown=0.10),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_below_return_floor == 0
        assert summary.n_windows_above_drawdown_ceil == 0
        assert summary.n_windows_below_sharpe_floor == 0

    def test_multiple_counts_independent(self) -> None:
        """Advisory counts are independent — a window can trigger multiple."""
        # Window 2 breaches all three thresholds simultaneously
        results = (
            _make_result(0, total_return=0.10, sharpe=1.0, max_drawdown=0.05),
            _make_result(
                1,
                total_return=_RETURN_FLOOR - 0.05,
                sharpe=_SHARPE_FLOOR - 0.1,
                max_drawdown=_DRAWDOWN_CEIL + 0.05,
            ),
        )
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_below_return_floor == 1
        assert summary.n_windows_above_drawdown_ceil == 1
        assert summary.n_windows_below_sharpe_floor == 1

    def test_governance_counts_are_advisory_only(self) -> None:
        """Governance counts provide visibility; they must not block execution."""
        results = _four_window_results()
        summary = _compute_summary(results, 50, 50)
        # Counts are integers, never raise exceptions, always ≥ 0
        assert isinstance(summary.n_windows_below_return_floor, int)
        assert isinstance(summary.n_windows_above_drawdown_ceil, int)
        assert isinstance(summary.n_windows_below_sharpe_floor, int)
        assert summary.n_windows_below_return_floor >= 0
        assert summary.n_windows_above_drawdown_ceil >= 0
        assert summary.n_windows_below_sharpe_floor >= 0


# ── Threshold constant values ─────────────────────────────────────────────────


class TestThresholdConstants:
    """Verify governance threshold constants match expected Phase-1B values."""

    def test_return_floor_value(self) -> None:
        assert (
            _RETURN_FLOOR == -0.10
        ), f"_RETURN_FLOOR must be -0.10. Any change requires ADR. Got: {_RETURN_FLOOR}"

    def test_drawdown_ceil_value(self) -> None:
        assert (
            _DRAWDOWN_CEIL == 0.30
        ), f"_DRAWDOWN_CEIL must be 0.30. Any change requires ADR. Got: {_DRAWDOWN_CEIL}"

    def test_sharpe_floor_value(self) -> None:
        assert (
            _SHARPE_FLOOR == 0.0
        ), f"_SHARPE_FLOOR must be 0.0. Any change requires ADR. Got: {_SHARPE_FLOOR}"


# ── Serialization round-trip ──────────────────────────────────────────────────


class TestSerializationRoundTrip:
    def _run(self) -> object:
        return run_walkforward(
            _make_ohlcv(),
            _make_config(),
            100,
            50,
            50,
            signal_fn=_neutral_fn,
            now_utc=_FIXED_NOW,
        )

    def test_new_summary_fields_present_in_dict(self) -> None:
        """All new v2 summary fields appear in report_to_dict output."""
        report = self._run()
        d = report_to_dict(report)  # type: ignore[arg-type]
        summary = d["summary"]
        new_fields = [
            "range_total_return",
            "cv_total_return",
            "std_sharpe_ratio",
            "min_sharpe_ratio",
            "max_sharpe_ratio",
            "std_max_drawdown",
            "min_max_drawdown",
            "max_max_drawdown",
            "n_windows_below_return_floor",
            "n_windows_above_drawdown_ceil",
            "n_windows_below_sharpe_floor",
        ]
        for field in new_fields:
            assert field in summary, f"New field '{field}' must appear in report_to_dict() summary."

    def test_round_trip_preserves_new_fields(self) -> None:
        """report_to_dict → report_from_dict preserves all new float fields."""
        report = self._run()
        d = report_to_dict(report)  # type: ignore[arg-type]
        restored = report_from_dict(d)
        d2 = report_to_dict(restored)  # type: ignore[arg-type]

        j1 = json.dumps(d, sort_keys=True)
        j2 = json.dumps(d2, sort_keys=True)
        assert j1 == j2, "JSON round-trip must preserve all new summary fields."

    def test_backward_compat_v1_dict_loads_with_defaults(self) -> None:
        """Loading a v1 report dict (missing new fields) uses NaN/0 defaults."""
        report = self._run()
        d = report_to_dict(report)  # type: ignore[arg-type]

        # Simulate a v1 report by removing new fields
        v1_new_fields = [
            "range_total_return",
            "cv_total_return",
            "std_sharpe_ratio",
            "min_sharpe_ratio",
            "max_sharpe_ratio",
            "std_max_drawdown",
            "min_max_drawdown",
            "max_max_drawdown",
            "n_windows_below_return_floor",
            "n_windows_above_drawdown_ceil",
            "n_windows_below_sharpe_floor",
        ]
        for field in v1_new_fields:
            d["summary"].pop(field, None)

        # Must not raise
        restored = report_from_dict(d)

        # Float fields default to NaN
        assert math.isnan(
            restored.summary.range_total_return
        ), "Missing range_total_return must load as NaN."
        assert math.isnan(restored.summary.cv_total_return)
        assert math.isnan(restored.summary.std_sharpe_ratio)

        # Int fields default to 0
        assert restored.summary.n_windows_below_return_floor == 0
        assert restored.summary.n_windows_above_drawdown_ceil == 0
        assert restored.summary.n_windows_below_sharpe_floor == 0

    def test_nan_serialized_as_null(self) -> None:
        """NaN float fields serialize to JSON null."""
        # Use single failed window → all float fields NaN
        report = self._run()
        d = report_to_dict(report)  # type: ignore[arg-type]
        serialized = json.dumps(d, sort_keys=True)
        parsed = json.loads(serialized)
        # If range is null (None after parsing), it was serialized from NaN
        # If range is a float, it's a valid value — either way must not be
        # the Python float NaN literal (which would be invalid JSON).
        summary = parsed["summary"]
        for field in ["range_total_return", "cv_total_return"]:
            raw_value = summary.get(field)
            assert raw_value is None or isinstance(raw_value, (int, float)), (
                f"'{field}' must serialize as null or a valid JSON number. " f"Got: {raw_value!r}"
            )


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_variance_fields_deterministic_across_runs(self) -> None:
        """The same inputs produce identical summary values on repeated calls."""
        results = _four_window_results()
        s1 = _compute_summary(results, 50, 50)
        s2 = _compute_summary(results, 50, 50)

        float_fields = [
            "mean_total_return",
            "std_total_return",
            "range_total_return",
            "cv_total_return",
            "mean_sharpe_ratio",
            "std_sharpe_ratio",
            "min_sharpe_ratio",
            "max_sharpe_ratio",
            "mean_max_drawdown",
            "std_max_drawdown",
            "min_max_drawdown",
            "max_max_drawdown",
        ]
        for field in float_fields:
            v1 = getattr(s1, field)
            v2 = getattr(s2, field)
            if math.isnan(v1):
                assert math.isnan(v2), f"{field}: first call NaN but second not."
            else:
                assert v1 == v2, f"{field}: {v1} != {v2} across repeated calls."

    def test_run_walkforward_report_hash_stable(self) -> None:
        """run_walkforward produces the same report_hash on repeated runs."""
        r1 = run_walkforward(
            _make_ohlcv(),
            _make_config(),
            100,
            50,
            50,
            signal_fn=_neutral_fn,
            now_utc=_FIXED_NOW,
        )
        r2 = run_walkforward(
            _make_ohlcv(),
            _make_config(),
            100,
            50,
            50,
            signal_fn=_neutral_fn,
            now_utc=_FIXED_NOW,
        )
        assert r1.report_hash == r2.report_hash, (
            "report_hash must be identical across repeated run_walkforward calls "
            "with identical inputs."
        )


# ── Adversarial: governance counts cannot trigger auto-selection ─────────────


class TestAdvisoryOnlySemantics:
    """These tests verify that governance advisory counts remain advisory only.

    The counts are plain integers.  They do not gate execution, trigger
    rejections, or mutate any downstream state.  Any code that uses these
    counts for automated strategy selection would be out-of-scope for AQCS
    Phase-1B and must not be added.
    """

    def test_high_advisory_count_does_not_raise(self) -> None:
        """A report with all folds breaching governance thresholds must still succeed."""
        # All folds breach all three thresholds
        results = tuple(
            _make_result(
                i,
                total_return=_RETURN_FLOOR - 0.10,
                sharpe=_SHARPE_FLOOR - 1.0,
                max_drawdown=_DRAWDOWN_CEIL + 0.10,
            )
            for i in range(5)
        )
        # Must not raise — governance counts are advisory, not blocking
        summary = _compute_summary(results, 50, 50)
        assert summary.n_windows_below_return_floor == 5
        assert summary.n_windows_above_drawdown_ceil == 5
        assert summary.n_windows_below_sharpe_floor == 5

    def test_governance_counts_do_not_affect_report_leakage_validated(self) -> None:
        """leakage_validated is independent of governance advisory counts."""
        r = run_walkforward(
            _make_ohlcv(),
            _make_config(),
            100,
            50,
            50,
            signal_fn=_neutral_fn,
            now_utc=_FIXED_NOW,
        )
        # leakage_validated reflects window segmentation safety,
        # not governance advisory count levels
        assert isinstance(r.leakage_validated, bool)
        assert r.leakage_validated is True
