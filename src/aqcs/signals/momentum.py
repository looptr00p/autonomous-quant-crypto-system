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
    prices: pd.Series,
    window: int,
    *,
    long_quantile: float = 0.7,
    short_quantile: float = 0.3,
) -> pd.Series:
    """Generate a time-series momentum signal from rolling price-return rankings.

    Computes the N-period rolling return from prices (not from per-period
    returns), then ranks each value within the expanding history of rolling
    returns seen so far. Passing pre-computed per-period returns would produce
    "returns of returns" — a semantic error this design avoids.

    Rolling return at T: r_T = (price_T - price_{T-N}) / price_{T-N}

    Warm-up: the first 2*window - 1 bars are always NEUTRAL — rolling_return
    needs `window` bars before its first value, and the expanding rank then
    needs `window` non-NaN rolling returns before producing a valid rank.

    Args:
        prices: Series of asset prices (not per-period returns).
        window: Lookback N for rolling N-period return. Must be a positive int.
        long_quantile: Rank at or above this threshold → LONG.
        short_quantile: Rank at or below this threshold → SHORT.

    Returns:
        Series of SignalDirection values aligned to the input index.
    """
    _require_series(prices, "prices")
    _require_window(window)
    _require_quantile(long_quantile, "long_quantile")
    _require_quantile(short_quantile, "short_quantile")
    if long_quantile <= short_quantile:
        raise ValueError(
            f"long_quantile ({long_quantile}) must be greater than "
            f"short_quantile ({short_quantile})"
        )

    # N-period rolling price return — causal, no future data
    rolling = rolling_return(prices, window)

    # Expanding percentile rank within all rolling returns seen up to T.
    # min_periods=window: NaN until `window` non-NaN rolling returns exist.
    rank = rolling.expanding(min_periods=window).rank(pct=True)

    result = pd.Series(SignalDirection.NEUTRAL, index=prices.index, dtype=object)
    result[rank >= long_quantile] = SignalDirection.LONG
    result[rank <= short_quantile] = SignalDirection.SHORT
    return result
