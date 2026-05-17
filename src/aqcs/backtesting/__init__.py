"""AQCS Backtesting Engine — minimal, deterministic, auditable.

Phase 1: daily bars, long-only, single asset, next-bar execution.
See docs/architecture/minimal-backtesting-engine.md for full assumptions.
"""

from aqcs.backtesting.engine import run_backtest
from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade

__all__ = ["run_backtest", "BacktestConfig", "BacktestResult", "EquityCurvePoint", "Trade"]
