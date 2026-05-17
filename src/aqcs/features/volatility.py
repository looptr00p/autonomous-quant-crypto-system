"""Volatility features — pure, deterministic, no lookahead."""

from __future__ import annotations

import math

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


def rolling_volatility(
    returns: pd.Series,
    window: int,
    *,
    annualise: bool = True,
    periods_per_year: int = 252,
) -> pd.Series:
    """Compute rolling standard deviation of returns.

    Uses a trailing window of `window` returns to estimate annualised
    volatility. Elements 0 through window-1 are NaN (insufficient history).

    No lookahead: at time t, only returns[0..t] are used.

    Args:
        returns: Series of per-period returns (not prices).
        window: Rolling window length in periods.
        annualise: If True, multiply by sqrt(periods_per_year).
        periods_per_year: Used only when annualise=True.
                          Daily data → 252, hourly → 8760, etc.
    """
    _require_series(returns, "returns")
    _require_window(window)
    if annualise and periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year}")

    vol = returns.rolling(window=window, min_periods=window).std()
    if annualise:
        vol = vol * math.sqrt(periods_per_year)
    return vol
