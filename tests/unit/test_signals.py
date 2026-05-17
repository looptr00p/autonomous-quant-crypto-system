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


def _returns(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _up_trend(n: int = 30) -> pd.Series:
    """Monotonically increasing prices."""
    return _prices([float(100 + i) for i in range(n)])


def _down_trend(n: int = 30) -> pd.Series:
    """Monotonically decreasing prices."""
    return _prices([float(100 - i) for i in range(n)])


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
    def test_returns_series(self) -> None:
        returns = _returns([0.01] * 25)
        sig = momentum_rank_signal(returns, window=10)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(returns)

    def test_output_values_are_signal_directions(self) -> None:
        returns = _returns([0.01, -0.01] * 15)
        sig = momentum_rank_signal(returns, window=5)
        valid = set(SignalDirection)
        for val in sig:
            assert val in valid

    def test_warm_up_period_is_neutral(self) -> None:
        returns = _returns([0.01] * 20)
        sig = momentum_rank_signal(returns, window=10)
        # First window-1 elements: rolling_return is NaN → NEUTRAL
        for i in range(9):
            assert sig.iloc[i] == SignalDirection.NEUTRAL

    def test_consistent_positive_returns_becomes_long(self) -> None:
        # Consistently positive returns → high rank → LONG
        returns = _returns([0.02] * 50)
        sig = momentum_rank_signal(returns, window=5, long_quantile=0.6)
        non_neutral = sig[sig != SignalDirection.NEUTRAL]
        if not non_neutral.empty:
            assert (non_neutral == SignalDirection.LONG).any()

    def test_consistent_negative_returns_becomes_short(self) -> None:
        returns = _returns([-0.02] * 50)
        sig = momentum_rank_signal(returns, window=5, short_quantile=0.4)
        non_neutral = sig[sig != SignalDirection.NEUTRAL]
        if not non_neutral.empty:
            assert (non_neutral == SignalDirection.SHORT).any()

    def test_invalid_long_quantile_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_returns([0.01] * 10), window=5, long_quantile=1.5)

    def test_invalid_short_quantile_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_returns([0.01] * 10), window=5, short_quantile=-0.1)

    def test_long_quantile_must_exceed_short(self) -> None:
        with pytest.raises(ValueError, match="greater than"):
            momentum_rank_signal(
                _returns([0.01] * 10),
                window=5,
                long_quantile=0.3,
                short_quantile=0.7,
            )

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError):
            momentum_rank_signal(_returns([0.01] * 10), window=0)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            momentum_rank_signal(pd.Series([], dtype=float), window=5)

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(TypeError):
            momentum_rank_signal(pd.Series(["a", "b"]), window=1)

    def test_preserves_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=20, freq="1D")
        returns = pd.Series([0.01] * 20, index=idx)
        sig = momentum_rank_signal(returns, window=5)
        assert list(sig.index) == list(idx)

    def test_no_lookahead_signal_at_T_uses_only_data_through_T(self) -> None:
        returns = _returns([0.01, -0.02, 0.015, -0.01, 0.02, 0.005, -0.015,
                            0.01, 0.02, -0.005, 0.01, 0.015, -0.02, 0.01, 0.02])
        window = 5
        full = momentum_rank_signal(returns, window)
        for t in range(window, len(returns)):
            partial = momentum_rank_signal(returns.iloc[: t + 1], window)
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
    def _make_uptrend(self, n: int = 60) -> tuple[pd.Series, pd.Series]:
        prices = _up_trend(n)
        returns = prices.pct_change().fillna(0.0)
        return prices, returns

    def test_returns_series(self) -> None:
        prices, returns = self._make_uptrend()
        sig = combined_momentum_trend_signal(
            prices, returns, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(prices)

    def test_output_values_are_signal_directions(self) -> None:
        prices, returns = self._make_uptrend()
        sig = combined_momentum_trend_signal(
            prices, returns, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        valid = set(SignalDirection)
        for val in sig:
            assert val in valid

    def test_uptrend_produces_long_when_both_agree(self) -> None:
        prices, returns = self._make_uptrend(60)
        sig = combined_momentum_trend_signal(
            prices, returns, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        non_neutral = sig[sig != SignalDirection.NEUTRAL]
        if not non_neutral.empty:
            assert (non_neutral == SignalDirection.LONG).any()

    def test_disagreement_produces_neutral(self) -> None:
        # Mix uptrend (trend=LONG) with flat returns (momentum neutral/mixed)
        prices = _up_trend(40)
        returns = _returns([0.0] * 40)  # zero returns → momentum NEUTRAL
        sig = combined_momentum_trend_signal(
            prices, returns, momentum_window=5,
            trend_short_window=3, trend_long_window=10,
        )
        # With flat returns, momentum stays near 0.5 rank → NEUTRAL
        # Combined must then be NEUTRAL even if trend says LONG
        non_neutral_longs = sig[sig == SignalDirection.LONG]
        assert non_neutral_longs.empty, "No LONG expected when momentum is NEUTRAL"

    def test_warm_up_is_neutral(self) -> None:
        prices, returns = self._make_uptrend(60)
        sig = combined_momentum_trend_signal(
            prices, returns, momentum_window=10,
            trend_short_window=5, trend_long_window=20,
        )
        # Warm-up = max(momentum_window, long_window) = 20 bars
        for i in range(19):
            assert sig.iloc[i] == SignalDirection.NEUTRAL

    def test_no_lookahead(self) -> None:
        prices, returns = self._make_uptrend(50)
        mom_w, short_w, long_w = 10, 5, 20
        full = combined_momentum_trend_signal(
            prices, returns, momentum_window=mom_w,
            trend_short_window=short_w, trend_long_window=long_w,
        )
        for t in range(long_w, len(prices)):
            p_partial = prices.iloc[: t + 1]
            r_partial = returns.iloc[: t + 1]
            partial = combined_momentum_trend_signal(
                p_partial, r_partial, momentum_window=mom_w,
                trend_short_window=short_w, trend_long_window=long_w,
            )
            assert full.iloc[t] == partial.iloc[-1], (
                f"Lookahead at T={t}: full={full.iloc[t]}, partial={partial.iloc[-1]}"
            )
