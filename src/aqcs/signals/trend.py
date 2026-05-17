"""Trend-following signals — deterministic, no lookahead, no portfolio logic."""

from __future__ import annotations

import pandas as pd

from aqcs.features.trend import simple_moving_average
from aqcs.signals.types import SignalDirection


def _require_series(series: pd.Series, name: str = "input") -> None:
    if not isinstance(series, pd.Series):
        raise TypeError(f"{name} must be a pd.Series, got {type(series).__name__}")
    if series.empty:
        raise ValueError(f"{name} must not be empty")
    if not pd.api.types.is_numeric_dtype(series):
        raise TypeError(f"{name} must have a numeric dtype, got {series.dtype}")


def _require_window(window: int, name: str = "window") -> None:
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"{name} must be a positive integer, got {window!r}")


def trend_filter_signal(
    prices: pd.Series,
    short_window: int,
    long_window: int,
) -> pd.Series:
    """Generate a moving-average crossover trend signal.

    LONG when short-term MA > long-term MA (uptrend).
    SHORT when short-term MA < long-term MA (downtrend).
    NEUTRAL when either MA is undefined (warm-up) or they are equal.

    No lookahead: both MAs use only prices[0..t] to compute MA[t].

    Args:
        prices: Series of prices.
        short_window: Fast (short) MA lookback window.
        long_window: Slow (long) MA lookback window.
    """
    _require_series(prices, "prices")
    _require_window(short_window, "short_window")
    _require_window(long_window, "long_window")
    if short_window >= long_window:
        raise ValueError(
            f"short_window ({short_window}) must be less than "
            f"long_window ({long_window})"
        )

    short_ma = simple_moving_average(prices, short_window)
    long_ma = simple_moving_average(prices, long_window)

    result = pd.Series(SignalDirection.NEUTRAL, index=prices.index, dtype=object)
    result[short_ma > long_ma] = SignalDirection.LONG
    result[short_ma < long_ma] = SignalDirection.SHORT
    return result
