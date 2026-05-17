"""AQCS Feature Layer — pure, deterministic, no lookahead.

All feature functions are pure: given the same input, they produce the
same output with no side effects. They do not read files, call APIs,
emit events, or use future data.
"""

from aqcs.features.returns import log_return, rolling_return, simple_return
from aqcs.features.trend import (
    distance_from_moving_average,
    exponential_moving_average,
    simple_moving_average,
)
from aqcs.features.volatility import rolling_volatility

__all__ = [
    "simple_return",
    "log_return",
    "rolling_return",
    "rolling_volatility",
    "simple_moving_average",
    "exponential_moving_average",
    "distance_from_moving_average",
]
