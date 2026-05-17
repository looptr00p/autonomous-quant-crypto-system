"""Trend features — pure, deterministic, no lookahead."""

from __future__ import annotations

import pandas as pd


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


def simple_moving_average(prices: pd.Series, window: int) -> pd.Series:
    """Compute simple (equal-weight) moving average.

    Elements 0 through window-1 are NaN (insufficient history).
    No lookahead: SMA[t] = mean(prices[t-window+1 .. t]).
    """
    _require_series(prices, "prices")
    _require_window(window)
    return prices.rolling(window=window, min_periods=window).mean()


def exponential_moving_average(prices: pd.Series, span: int) -> pd.Series:
    """Compute exponential moving average using a causal IIR filter.

    alpha = 2 / (span + 1)
    EMA[t] = alpha * prices[t] + (1 - alpha) * EMA[t-1]

    Uses adjust=False (causal/recursive form) to guarantee no lookahead.
    Elements 0 through span-1 are NaN.

    Args:
        prices: Series of prices.
        span: EMA span — controls the decay rate.
    """
    _require_series(prices, "prices")
    _require_window(span, "span")
    return prices.ewm(span=span, min_periods=span, adjust=False).mean()


def distance_from_moving_average(prices: pd.Series, window: int) -> pd.Series:
    """Compute normalised distance of price from its simple moving average.

    distance[t] = (prices[t] - SMA[t]) / SMA[t]

    A positive value means price is above SMA (bullish context).
    A negative value means price is below SMA (bearish context).

    Elements where SMA is NaN or zero are NaN.
    No lookahead.
    """
    _require_series(prices, "prices")
    _require_window(window)
    sma = simple_moving_average(prices, window)
    with_sma = sma.copy()
    with_sma[with_sma == 0] = float("nan")
    return (prices - with_sma) / with_sma
