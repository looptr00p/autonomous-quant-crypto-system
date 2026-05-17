"""Combined signals — deterministic compositions of momentum and trend."""

from __future__ import annotations

import pandas as pd

from aqcs.signals.momentum import momentum_rank_signal
from aqcs.signals.trend import trend_filter_signal
from aqcs.signals.types import SignalDirection


def combined_momentum_trend_signal(
    prices: pd.Series,
    returns: pd.Series,
    momentum_window: int,
    trend_short_window: int,
    trend_long_window: int,
    *,
    momentum_long_quantile: float = 0.7,
    momentum_short_quantile: float = 0.3,
) -> pd.Series:
    """Generate a signal that requires both momentum and trend to agree.

    LONG only when momentum_rank_signal is LONG AND trend_filter_signal is LONG.
    SHORT only when both signals are SHORT.
    NEUTRAL in all other cases (disagreement, warm-up, or flat signals).

    This conservative combination reduces noise and false signals.
    No lookahead: each component signal respects its own lookahead constraints.

    Args:
        prices: Series of prices (for trend computation).
        returns: Series of per-period returns (for momentum computation).
        momentum_window: Lookback window for rolling return in momentum signal.
        trend_short_window: Fast MA window for trend filter.
        trend_long_window: Slow MA window for trend filter.
        momentum_long_quantile: Rank threshold above which momentum is LONG.
        momentum_short_quantile: Rank threshold below which momentum is SHORT.

    Returns:
        Series of SignalDirection values aligned to input index.
    """
    if prices.index is not returns.index and not prices.index.equals(returns.index):
        raise ValueError("prices and returns must share the same index")

    mom = momentum_rank_signal(
        returns,
        momentum_window,
        long_quantile=momentum_long_quantile,
        short_quantile=momentum_short_quantile,
    )
    trend = trend_filter_signal(prices, trend_short_window, trend_long_window)

    result = pd.Series(SignalDirection.NEUTRAL, index=prices.index, dtype=object)
    long_mask = (mom == SignalDirection.LONG) & (trend == SignalDirection.LONG)
    short_mask = (mom == SignalDirection.SHORT) & (trend == SignalDirection.SHORT)
    result[long_mask] = SignalDirection.LONG
    result[short_mask] = SignalDirection.SHORT
    return result
