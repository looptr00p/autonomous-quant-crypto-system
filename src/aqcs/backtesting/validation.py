"""Backtest input validation — fail fast with clear error messages."""

from __future__ import annotations

import pandas as pd

from aqcs.backtesting.models import BacktestConfig

_REQUIRED_OHLCV_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


def validate_backtest_inputs(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    config: BacktestConfig,
) -> None:
    """Validate all inputs before the simulation loop begins.

    Raises ValueError or TypeError with a clear message on any violation.
    All checks run unconditionally (no early return on first failure) so
    the caller sees all problems at once.
    """
    errors: list[str] = []

    # ── OHLCV checks ──────────────────────────────────────────────────────────
    if not isinstance(ohlcv, pd.DataFrame):
        errors.append(f"ohlcv must be a pd.DataFrame, got {type(ohlcv).__name__}")
    elif ohlcv.empty:
        errors.append("ohlcv is empty — nothing to backtest")
    else:
        missing = _REQUIRED_OHLCV_COLUMNS - set(ohlcv.columns)
        if missing:
            errors.append(f"ohlcv is missing required columns: {sorted(missing)}")
        elif not ohlcv["timestamp"].is_monotonic_increasing:
            errors.append(
                "ohlcv timestamps must be strictly monotonically increasing. "
                "Run the data validator before passing data to the engine."
            )
        elif ohlcv["timestamp"].duplicated().any():
            errors.append("ohlcv contains duplicate timestamps")

    # ── Signal checks ─────────────────────────────────────────────────────────
    if not isinstance(signals, pd.Series):
        errors.append(f"signals must be a pd.Series, got {type(signals).__name__}")
    elif signals.empty:
        errors.append("signals is empty")

    # ── Overlap check (only if both are valid so far) ─────────────────────────
    if (
        not errors
        and isinstance(ohlcv, pd.DataFrame)
        and not ohlcv.empty
        and isinstance(signals, pd.Series)
        and not signals.empty
    ):
        ohlcv_ts = set(ohlcv["timestamp"].tolist())
        signal_ts = set(signals.index.tolist())
        overlap = ohlcv_ts & signal_ts
        if not overlap:
            errors.append(
                "Signals and OHLCV share no common timestamps. "
                "Ensure signals are indexed by the same UTC timestamps as ohlcv['timestamp']."
            )

    if errors:
        raise ValueError(
            "Backtest input validation failed:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )
