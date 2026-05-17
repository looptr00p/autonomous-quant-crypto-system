"""Tests for the AQCS feature layer — purity, correctness, no lookahead."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from aqcs.features import (
    distance_from_moving_average,
    exponential_moving_average,
    log_return,
    rolling_return,
    rolling_volatility,
    simple_moving_average,
    simple_return,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prices(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def _returns(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


# ── simple_return ─────────────────────────────────────────────────────────────

class TestSimpleReturn:
    def test_basic_computation(self) -> None:
        r = simple_return(_prices([100.0, 110.0, 99.0]))
        assert pd.isna(r.iloc[0])
        assert r.iloc[1] == pytest.approx(0.10, rel=1e-9)
        assert r.iloc[2] == pytest.approx(-0.10, rel=1e-6)

    def test_first_element_is_nan(self) -> None:
        r = simple_return(_prices([100.0, 105.0]))
        assert pd.isna(r.iloc[0])

    def test_preserves_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=3, freq="1D")
        p = pd.Series([100.0, 110.0, 121.0], index=idx)
        r = simple_return(p)
        assert list(r.index) == list(idx)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            simple_return(pd.Series([], dtype=float))

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(TypeError):
            simple_return(pd.Series(["a", "b"]))

    def test_not_series_raises(self) -> None:
        with pytest.raises(TypeError):
            simple_return([100.0, 110.0])  # type: ignore[arg-type]

    def test_single_element_returns_nan(self) -> None:
        r = simple_return(_prices([100.0]))
        assert pd.isna(r.iloc[0])

    def test_no_lookahead(self) -> None:
        prices = _prices([100.0, 110.0, 120.0, 115.0, 125.0])
        full = simple_return(prices)
        for t in range(1, len(prices)):
            partial = simple_return(prices.iloc[: t + 1])
            assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-9)


# ── log_return ────────────────────────────────────────────────────────────────

class TestLogReturn:
    def test_basic_computation(self) -> None:
        r = log_return(_prices([100.0, math.e * 100.0]))
        assert pd.isna(r.iloc[0])
        assert r.iloc[1] == pytest.approx(1.0, rel=1e-9)

    def test_first_element_is_nan(self) -> None:
        r = log_return(_prices([100.0, 110.0]))
        assert pd.isna(r.iloc[0])

    def test_preserves_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=3, freq="1D")
        p = pd.Series([100.0, 110.0, 121.0], index=idx)
        r = log_return(p)
        assert list(r.index) == list(idx)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            log_return(pd.Series([], dtype=float))

    def test_no_lookahead(self) -> None:
        prices = _prices([100.0, 110.0, 120.0, 115.0, 125.0])
        full = log_return(prices)
        for t in range(1, len(prices)):
            partial = log_return(prices.iloc[: t + 1])
            assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-9)


# ── rolling_return ────────────────────────────────────────────────────────────

class TestRollingReturn:
    def test_basic_computation(self) -> None:
        r = rolling_return(_prices([100.0, 110.0, 121.0, 133.1]), window=2)
        assert pd.isna(r.iloc[0])
        assert pd.isna(r.iloc[1])
        assert r.iloc[2] == pytest.approx(0.21, rel=1e-6)

    def test_warm_up_nans(self) -> None:
        r = rolling_return(_prices([100.0, 110.0, 120.0, 130.0]), window=3)
        assert pd.isna(r.iloc[0])
        assert pd.isna(r.iloc[1])
        assert pd.isna(r.iloc[2])
        assert not pd.isna(r.iloc[3])

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError):
            rolling_return(_prices([100.0, 110.0]), window=0)

    def test_negative_window_raises(self) -> None:
        with pytest.raises(ValueError):
            rolling_return(_prices([100.0, 110.0]), window=-1)

    def test_non_integer_window_raises(self) -> None:
        with pytest.raises(ValueError):
            rolling_return(_prices([100.0, 110.0]), window=1.5)  # type: ignore[arg-type]

    def test_no_lookahead(self) -> None:
        prices = _prices([100.0, 110.0, 121.0, 115.0, 125.0, 130.0])
        window = 3
        full = rolling_return(prices, window)
        for t in range(window, len(prices)):
            partial = rolling_return(prices.iloc[: t + 1], window)
            assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-9)


# ── rolling_volatility ────────────────────────────────────────────────────────

class TestRollingVolatility:
    def test_basic_computation(self) -> None:
        returns = _returns([0.01, -0.02, 0.015, -0.01, 0.02, 0.005, -0.015, 0.01])
        vol = rolling_volatility(returns, window=4, annualise=False)
        assert pd.isna(vol.iloc[0])
        assert pd.isna(vol.iloc[2])
        assert not pd.isna(vol.iloc[3])

    def test_annualisation(self) -> None:
        # Non-constant returns so std is non-zero
        returns = _returns([0.01, -0.01, 0.02, -0.02, 0.015] * 4)
        vol_daily = rolling_volatility(returns, window=5, annualise=False)
        vol_annual = rolling_volatility(returns, window=5, annualise=True, periods_per_year=252)
        daily_valid = vol_daily.dropna()
        annual_valid = vol_annual.dropna()
        assert not daily_valid.empty
        ratio = annual_valid.iloc[0] / daily_valid.iloc[0]
        assert ratio == pytest.approx(math.sqrt(252), rel=1e-6)

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError):
            rolling_volatility(_returns([0.01, 0.02]), window=0)

    def test_negative_periods_per_year_raises(self) -> None:
        with pytest.raises(ValueError):
            rolling_volatility(_returns([0.01] * 5), window=3, annualise=True, periods_per_year=-1)

    def test_no_lookahead(self) -> None:
        returns = _returns([0.01, -0.02, 0.015, -0.01, 0.02, 0.005, -0.015, 0.01])
        window = 4
        full = rolling_volatility(returns, window, annualise=False)
        for t in range(window - 1, len(returns)):
            partial = rolling_volatility(returns.iloc[: t + 1], window, annualise=False)
            if not pd.isna(full.iloc[t]):
                assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-9)


# ── simple_moving_average ─────────────────────────────────────────────────────

class TestSimpleMovingAverage:
    def test_basic_computation(self) -> None:
        sma = simple_moving_average(_prices([10.0, 20.0, 30.0, 40.0]), window=3)
        assert pd.isna(sma.iloc[0])
        assert pd.isna(sma.iloc[1])
        assert sma.iloc[2] == pytest.approx(20.0)
        assert sma.iloc[3] == pytest.approx(30.0)

    def test_warm_up_nans(self) -> None:
        sma = simple_moving_average(_prices(list(range(1, 11))), window=5)
        assert all(pd.isna(sma.iloc[i]) for i in range(4))
        assert not pd.isna(sma.iloc[4])

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError):
            simple_moving_average(_prices([1.0, 2.0]), window=0)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            simple_moving_average(pd.Series([], dtype=float), window=3)

    def test_preserves_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=5, freq="1D")
        prices = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
        sma = simple_moving_average(prices, window=3)
        assert list(sma.index) == list(idx)

    def test_no_lookahead(self) -> None:
        prices = _prices([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        window = 3
        full = simple_moving_average(prices, window)
        for t in range(window - 1, len(prices)):
            partial = simple_moving_average(prices.iloc[: t + 1], window)
            if not pd.isna(full.iloc[t]):
                assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-9)


# ── exponential_moving_average ────────────────────────────────────────────────

class TestExponentialMovingAverage:
    def test_warm_up_nans(self) -> None:
        ema = exponential_moving_average(_prices([1.0, 2.0, 3.0, 4.0, 5.0]), span=3)
        assert all(pd.isna(ema.iloc[i]) for i in range(2))
        assert not pd.isna(ema.iloc[2])

    def test_ema_tracks_price(self) -> None:
        # Constant price → EMA equals price
        prices = _prices([100.0] * 10)
        ema = exponential_moving_average(prices, span=3)
        for val in ema.dropna():
            assert val == pytest.approx(100.0, rel=1e-6)

    def test_zero_span_raises(self) -> None:
        with pytest.raises(ValueError):
            exponential_moving_average(_prices([1.0, 2.0]), span=0)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            exponential_moving_average(pd.Series([], dtype=float), span=3)

    def test_no_lookahead(self) -> None:
        prices = _prices([10.0, 20.0, 15.0, 25.0, 18.0, 22.0, 30.0])
        span = 3
        full = exponential_moving_average(prices, span)
        for t in range(span - 1, len(prices)):
            partial = exponential_moving_average(prices.iloc[: t + 1], span)
            if not pd.isna(full.iloc[t]):
                assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-6)


# ── distance_from_moving_average ──────────────────────────────────────────────

class TestDistanceFromMovingAverage:
    def test_above_sma_is_positive(self) -> None:
        prices = _prices([10.0, 10.0, 10.0, 15.0])
        d = distance_from_moving_average(prices, window=3)
        assert d.iloc[3] > 0

    def test_below_sma_is_negative(self) -> None:
        prices = _prices([10.0, 10.0, 10.0, 5.0])
        d = distance_from_moving_average(prices, window=3)
        assert d.iloc[3] < 0

    def test_at_sma_is_zero(self) -> None:
        prices = _prices([10.0, 10.0, 10.0])
        d = distance_from_moving_average(prices, window=3)
        assert d.iloc[2] == pytest.approx(0.0, abs=1e-12)

    def test_warm_up_nans(self) -> None:
        prices = _prices([10.0, 20.0, 15.0, 25.0])
        d = distance_from_moving_average(prices, window=3)
        assert pd.isna(d.iloc[0])
        assert pd.isna(d.iloc[1])

    def test_normalisation(self) -> None:
        # Window=3 at index 3: SMA uses prices[1], prices[2], prices[3]
        prices = _prices([10.0, 10.0, 10.0, 12.0])
        d = distance_from_moving_average(prices, window=3)
        sma_at_3 = (10.0 + 10.0 + 12.0) / 3  # trailing window includes current bar
        expected = (12.0 - sma_at_3) / sma_at_3
        assert d.iloc[3] == pytest.approx(expected, rel=1e-9)

    def test_no_lookahead(self) -> None:
        prices = _prices([10.0, 12.0, 11.0, 13.0, 14.0, 12.0])
        window = 3
        full = distance_from_moving_average(prices, window)
        for t in range(window - 1, len(prices)):
            partial = distance_from_moving_average(prices.iloc[: t + 1], window)
            if not pd.isna(full.iloc[t]):
                assert full.iloc[t] == pytest.approx(partial.iloc[-1], rel=1e-9)
