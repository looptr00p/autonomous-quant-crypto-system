"""Return computation — pure, deterministic, no lookahead.

All functions:
- Accept a pd.Series of prices or returns
- Return a pd.Series aligned to the same index
- Use only current and past data (no future values)
- Do not modify the input Series
"""

from __future__ import annotations

import numpy as np
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


def simple_return(prices: pd.Series) -> pd.Series:
    """Compute period-over-period simple (arithmetic) return.

    r_t = (p_t - p_{t-1}) / p_{t-1}

    The first element is NaN (no prior price available).
    No lookahead: uses only prices[0..t] to compute return[t].
    """
    _require_series(prices, "prices")
    return prices.pct_change()


def log_return(prices: pd.Series) -> pd.Series:
    """Compute period-over-period log (continuously compounded) return.

    r_t = ln(p_t / p_{t-1})

    The first element is NaN. No lookahead.

    Raises:
        ValueError: If any price is zero or negative. log(0) is -inf and
                    log of a negative number is undefined; both indicate
                    corrupt or invalid price data.
    """
    _require_series(prices, "prices")
    if (prices <= 0).any():
        n_bad = int((prices <= 0).sum())
        raise ValueError(
            f"log_return requires strictly positive prices. "
            f"Found {n_bad} non-positive value(s). "
            f"Check the input for zero or negative prices."
        )
    return pd.Series(np.log(prices / prices.shift(1)), index=prices.index, name=prices.name)


def rolling_return(prices: pd.Series, window: int) -> pd.Series:
    """Compute n-period rolling simple return.

    r_t = (p_t - p_{t-n}) / p_{t-n}

    Elements 0 through window-1 are NaN.
    No lookahead: uses only prices[0..t] to compute rolling_return[t].
    """
    _require_series(prices, "prices")
    _require_window(window)
    return prices.pct_change(periods=window)
