"""Time-series momentum signals — deterministic, no lookahead, no portfolio logic.

Signal functions:
- Accept feature Series as inputs
- Return a Series of SignalDirection values
- Use only current and past data
- Do not size positions
- Do not compute weights
- Do not submit orders
"""

from __future__ import annotations

import pandas as pd

from aqcs.features.returns import rolling_return
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


def _require_quantile(q: float, name: str) -> None:
    if not 0.0 < q < 1.0:
        raise ValueError(f"{name} must be in (0, 1), got {q!r}")


def momentum_rank_signal(
    returns: pd.Series,
    window: int,
    *,
    long_quantile: float = 0.7,
    short_quantile: float = 0.3,
) -> pd.Series:
    """Generate a time-series momentum signal from rolling return rankings.

    At each timestamp T, computes the percentile rank of the current rolling
    return within the expanding history of rolling returns seen so far (0..T).
    This avoids lookahead: the rank at T uses only data available at T.

    Args:
        returns: Series of per-period returns (not prices).
        window: Lookback window for rolling return computation.
        long_quantile: Ranks at or above this threshold → LONG.
        short_quantile: Ranks at or below this threshold → SHORT.

    Returns:
        Series of SignalDirection values aligned to input index.
        NaN periods (warm-up) are filled with NEUTRAL.
    """
    _require_series(returns, "returns")
    _require_window(window)
    _require_quantile(long_quantile, "long_quantile")
    _require_quantile(short_quantile, "short_quantile")
    if long_quantile <= short_quantile:
        raise ValueError(
            f"long_quantile ({long_quantile}) must be greater than "
            f"short_quantile ({short_quantile})"
        )

    rolling = rolling_return(returns, window)
    # Expanding percentile rank: rank of current value within history 0..t
    # min_periods=window ensures we have a full window before ranking starts
    rank = rolling.expanding(min_periods=window).rank(pct=True)

    result = pd.Series(SignalDirection.NEUTRAL, index=returns.index, dtype=object)
    result[rank >= long_quantile] = SignalDirection.LONG
    result[rank <= short_quantile] = SignalDirection.SHORT
    return result
