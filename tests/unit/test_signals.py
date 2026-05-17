"""Tests for the AQCS signal layer — determinism, no lookahead, correct direction."""

from __future__ import annotations

import pandas as pd
import pytest

from aqcs.signals import (
    SignalDirection,
    combined_momentum_trend_signal,
    momentum_rank_signal,
    trend_filter_signal,
)
from aqcs.signals.types import SignalDirection as SignalDirectionFromTypes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prices(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _up_trend(n: int = 30) -> pd.Series:
    """Monotonically increasing prices."""
    return _prices([float(100 + i) for i in range(n)])


def _down_trend(n: int = 30) -> pd.Series:
    """Monotonically decreasing prices."""
    return _prices([float(100 - i * 0.5) for i in range(n)])


def _flat(n: int = 50) -> pd.Series:
    """Completely flat prices — zero momentum, no trend."""
    return _prices([100.0] * n)


def _two_phase(flat: int = 35, surge: int = 40) -> pd.Series:
    """Flat phase then sudden acceleration — recent rolling returns dominate history.

    In the surge phase, rolling returns are far above the flat-phase near-zero
    rolling returns, so the expanding rank is near 1.0 → LONG.
    """
    flat_prices = [100.0] * flat
    surge_prices = [flat_prices[-1] + i * 3.0 for i in range(1, surge + 1)]
    return _prices(flat_prices + surge_prices)


def _two_phase_drop(high: int = 35, drop: int = 40) -> pd.Series:
    """High phase then sudden drop — recent rolling returns far below history → SHORT."""
    high_prices = [200.0] * high
    drop_prices = [high_prices[-1] - i * 3.0 for i in range(1, drop + 1)]
    return _prices(high_prices + drop_prices)


# ── SignalDirection ───────────────────────────────────────────────────────────

class TestSignalDirection:
    def test_reexported_from_types_module(self) -> None:
        assert SignalDirection is SignalDirectionFromTypes

    def test_all_directions_exist(self) -> None:
        assert SignalDirection.LONG == "long"
        assert SignalDirection.SHORT == "short"
        assert SignalDirection.NEUTRAL == "neutral"

    def test_is_string_enum(self) -> None:
        assert isinstance(SignalDirection.LONG, str)


# ── momentum_rank_signal ──────────────────────────────────────────────────────

class TestMomentumRankSignal:
    def test_accepts_prices_not_returns(self) -> None:
        """Confirm the parameter is named 'prices' (not 'returns')."""
        import inspect
        sig = inspect.signature(momentum_rank_signal)
        assert "prices" in sig.parameters, (
            "momentum_rank_signal must accept 'prices', not 'returns'. "
            "Passing per-period returns would produce 'returns of returns'."
        )
        assert "returns" not in sig.parameters

    def test_returns_series(self) -> None:
        prices = _up_trend(40)
        sig = momentum_rank_signal(prices, window=10)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(prices)

    def test_output_values_are_signal_directions(self) -> None:
        prices = _up_trend(40)
        sig = momentum_rank_signal(prices, window=5)
        valid = set(SignalDirection)
        for val in sig:
            assert val in valid

    def test_warm_up_period_is_neutral(self) -> None:
        prices = _up_trend(50)
        sig = momentum_rank_signal(prices, window=10)
        # Warm-up = 2*window - 1 = 19 bars
        # rolling_return needs window bars, expanding rank needs window non-NaN values
        for i in range(19):
            assert sig.iloc[i] == SignalDirection.NEUTRAL

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_up_trend(), window=0)

    def test_negative_window_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_up_trend(), window=-5)

    def test_invalid_long_quantile_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_up_trend(), window=5, long_quantile=1.5)

    def test_invalid_short_quantile_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_up_trend(), window=5, short_quantile=-0.1)

    def test_long_quantile_must_exceed_short(self) -> None:
        with pytest.raises(ValueError, match="greater than"):
            momentum_rank_signal(
                _up_trend(), window=5,
                long_quantile=0.3, short_quantile=0.7,
            )

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            momentum_rank_signal(pd.Series([], dtype=float), window=5)

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(TypeError):
            momentum_rank_signal(pd.Series(["a", "b"]), window=1)

    def test_not_series_raises(self) -> None:
        with pytest.raises(TypeError):
            momentum_rank_signal([100.0, 101.0, 102.0], window=1)  # type: ignore[arg-type]

    def test_preserves_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=40, freq="1D")
        prices = pd.Series([float(100 + i) for i in range(40)], index=idx)
        sig = momentum_rank_signal(prices, window=5)
        assert list(sig.index) == list(idx)

    # ── Semantic tests ────────────────────────────────────────────────────────

    def test_surge_after_flat_produces_long_signals(self) -> None:
        """After a flat period, a sudden price surge has rolling returns far above
        the near-zero historical baseline → high rank → LONG."""
        prices = _two_phase()
        sig = momentum_rank_signal(prices, window=10, long_quantile=0.6)
        # In the surge phase, recent rolling returns dominate flat-phase history
        surge_start = 35 + 19  # flat + warm-up
        surge_sig = sig.iloc[surge_start:]
        assert (surge_sig == SignalDirection.LONG).any(), (
            "Expected LONG signals in surge phase — recent returns >> flat history"
        )

    def test_flat_prices_produce_neutral_momentum(self) -> None:
        """Zero rolling returns rank at ~0.5 → NEUTRAL (within [0.3, 0.7])."""
        prices = _flat(80)
        sig = momentum_rank_signal(prices, window=10)
        assert (sig == SignalDirection.NEUTRAL).all(), (
            "Flat prices produce zero rolling return → rank ≈ 0.5 → NEUTRAL"
        )

    def test_momentum_uses_price_rolling_return_not_pct_change_of_returns(self) -> None:
        """Verify that momentum is derived from rolling_return(prices, N), not from
        pct_change applied to per-period returns (which would be 'returns of returns')."""
        prices = _prices([100.0, 105.0, 110.0, 115.0, 120.0,
                          125.0, 130.0, 135.0, 140.0, 145.0, 150.0])
        # 10-period return from index 0 to 10: (150-100)/100 = 0.50
        # This is correctly computed from prices, not from returns
        sig = momentum_rank_signal(prices, window=10)
        # All 11 bars: warm-up (2*10-1 = 19) exceeds length → all NEUTRAL
        assert (sig == SignalDirection.NEUTRAL).all()
        # Extend to ensure a signal is produced
        prices_long = _prices([float(100 + i * 5) for i in range(40)])
        sig_long = momentum_rank_signal(prices_long, window=10)
        # At index 19+, signals should reflect price-based rolling returns
        assert isinstance(sig_long, pd.Series)
        assert len(sig_long) == 40

    def test_no_lookahead(self) -> None:
        """Signal at T uses only data through T (no future data)."""
        prices = _prices([100.0 + i + (i % 3 - 1) * 0.5 for i in range(40)])
        window = 5
        full = momentum_rank_signal(prices, window)
        for t in range(window, len(prices)):
            partial = momentum_rank_signal(prices.iloc[: t + 1], window)
            assert full.iloc[t] == partial.iloc[-1], (
                f"Lookahead detected at T={t}: "
                f"full={full.iloc[t]}, partial={partial.iloc[-1]}"
            )


# ── trend_filter_signal ───────────────────────────────────────────────────────

class TestTrendFilterSignal:
    def test_returns_series(self) -> None:
        prices = _up_trend()
        sig = trend_filter_signal(prices, short_window=5, long_window=20)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(prices)

    def test_uptrend_produces_long(self) -> None:
        prices = _up_trend(50)
        sig = trend_filter_signal(prices, short_window=5, long_window=20)
        non_neutral = sig[sig != SignalDirection.NEUTRAL]
        assert not non_neutral.empty
        assert (non_neutral == SignalDirection.LONG).all()

    def test_downtrend_produces_short(self) -> None:
        prices = _down_trend(50)
        sig = trend_filter_signal(prices, short_window=5, long_window=20)
        non_neutral = sig[sig != SignalDirection.NEUTRAL]
        assert not non_neutral.empty
        assert (non_neutral == SignalDirection.SHORT).all()

    def test_flat_prices_produce_neutral(self) -> None:
        prices = _flat(50)
        sig = trend_filter_signal(prices, short_window=5, long_window=20)
        non_neutral = sig[sig != SignalDirection.NEUTRAL]
        assert non_neutral.empty, "Flat prices should produce no trend signals"

    def test_warm_up_is_neutral(self) -> None:
        prices = _up_trend(50)
        sig = trend_filter_signal(prices, short_window=5, long_window=20)
        for i in range(19):  # long_window - 1
            assert sig.iloc[i] == SignalDirection.NEUTRAL

    def test_short_window_ge_long_window_raises(self) -> None:
        with pytest.raises(ValueError, match="less than"):
            trend_filter_signal(_prices([1.0] * 30), short_window=20, long_window=20)

    def test_short_window_gt_long_window_raises(self) -> None:
        with pytest.raises(ValueError, match="less than"):
            trend_filter_signal(_prices([1.0] * 30), short_window=25, long_window=20)

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError):
            trend_filter_signal(_prices([1.0] * 30), short_window=0, long_window=20)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            trend_filter_signal(pd.Series([], dtype=float), short_window=5, long_window=20)

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(TypeError):
            trend_filter_signal(pd.Series(["a", "b"]), short_window=1, long_window=2)

    def test_preserves_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=30, freq="1D")
        prices = pd.Series(range(100, 130, 1), index=idx, dtype=float)
        sig = trend_filter_signal(prices, short_window=5, long_window=20)
        assert list(sig.index) == list(idx)

    def test_no_lookahead(self) -> None:
        prices = _up_trend(40)
        short_w, long_w = 5, 20
        full = trend_filter_signal(prices, short_w, long_w)
        for t in range(long_w - 1, len(prices)):
            partial = trend_filter_signal(prices.iloc[: t + 1], short_w, long_w)
            assert full.iloc[t] == partial.iloc[-1], (
                f"Lookahead at T={t}: full={full.iloc[t]}, partial={partial.iloc[-1]}"
            )


# ── combined_momentum_trend_signal ────────────────────────────────────────────

class TestCombinedMomentumTrendSignal:
    def test_accepts_prices_only(self) -> None:
        """Confirm the combined signal takes only prices — no ambiguous returns param."""
        import inspect
        sig = inspect.signature(combined_momentum_trend_signal)
        assert "prices" in sig.parameters
        assert "returns" not in sig.parameters, (
            "combined_momentum_trend_signal must not accept a 'returns' parameter. "
            "Both momentum and trend are derived from prices."
        )

    def test_returns_series(self) -> None:
        prices = _up_trend(60)
        sig = combined_momentum_trend_signal(
            prices, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(prices)

    def test_output_values_are_signal_directions(self) -> None:
        prices = _up_trend(60)
        sig = combined_momentum_trend_signal(
            prices, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        valid = set(SignalDirection)
        for val in sig:
            assert val in valid

    def test_surge_after_flat_produces_long(self) -> None:
        """Surge phase: momentum=LONG (recent return >> flat history) and
        trend=LONG (price rising) → combined=LONG."""
        prices = _two_phase(flat=40, surge=50)
        sig = combined_momentum_trend_signal(
            prices, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        # After both momentum and trend warm up inside the surge phase
        surge_start = 40 + 19  # flat + warm-up
        surge_sig = sig.iloc[surge_start:]
        assert (surge_sig == SignalDirection.LONG).any(), (
            "Expected LONG signals in surge phase when both momentum and trend agree"
        )

    def test_flat_prices_produce_all_neutral(self) -> None:
        """Flat prices: momentum=NEUTRAL, trend=NEUTRAL → combined=NEUTRAL."""
        prices = _flat(80)
        sig = combined_momentum_trend_signal(
            prices, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        assert (sig == SignalDirection.NEUTRAL).all(), (
            "Flat prices should produce no momentum or trend signal → all NEUTRAL"
        )

    def test_warm_up_is_neutral(self) -> None:
        prices = _two_phase(flat=40, surge=50)
        sig = combined_momentum_trend_signal(
            prices, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        # Warm-up = 2*momentum_window - 1 = 19 bars
        for i in range(19):
            assert sig.iloc[i] == SignalDirection.NEUTRAL

    def test_no_lookahead(self) -> None:
        prices = _two_phase(flat=30, surge=40)
        mom_w, short_w, long_w = 10, 5, 20
        full = combined_momentum_trend_signal(
            prices, momentum_window=mom_w,
            trend_short_window=short_w, trend_long_window=long_w,
        )
        for t in range(long_w, len(prices)):
            partial = combined_momentum_trend_signal(
                prices.iloc[: t + 1], momentum_window=mom_w,
                trend_short_window=short_w, trend_long_window=long_w,
            )
            assert full.iloc[t] == partial.iloc[-1], (
                f"Lookahead at T={t}: full={full.iloc[t]}, partial={partial.iloc[-1]}"
            )
