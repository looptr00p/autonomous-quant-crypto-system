"""AQCS Signal Layer — deterministic, pure, no portfolio or execution logic.

Signal functions accept feature Series and return SignalDirection Series.
They never size positions, compute weights, or interact with exchanges.
"""

from aqcs.signals.combined import combined_momentum_trend_signal
from aqcs.signals.momentum import momentum_rank_signal
from aqcs.signals.trend import trend_filter_signal
from aqcs.signals.types import SignalDirection

__all__ = [
    "SignalDirection",
    "momentum_rank_signal",
    "trend_filter_signal",
    "combined_momentum_trend_signal",
]
