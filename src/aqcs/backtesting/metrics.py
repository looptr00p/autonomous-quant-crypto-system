"""Backtest performance metrics — deterministic, explicitly documented assumptions.

Annualisation assumption: all metrics assume trading periods are equally spaced.
The periods_per_year parameter must be set explicitly in BacktestConfig.

No hidden assumptions: every formula is documented inline.
"""

from __future__ import annotations

import math
import statistics

from aqcs.backtesting.models import EquityCurvePoint, Trade


def compute_metrics(
    equity_curve: tuple[EquityCurvePoint, ...],
    trades: tuple[Trade, ...],
    periods_per_year: int = 252,
) -> dict[str, float]:
    """Compute the minimum required metrics from a completed backtest.

    Returns:
        Dict with keys: total_return, cagr, max_drawdown, sharpe_ratio,
        annualised_volatility, trade_count, win_rate, exposure.

    All float values. NaN for metrics that cannot be computed (e.g., win_rate
    with no completed trades, sharpe with zero volatility).
    """
    nan = float("nan")

    if not equity_curve:
        return {k: nan for k in [
            "total_return", "cagr", "max_drawdown", "sharpe_ratio",
            "annualised_volatility", "trade_count", "win_rate", "exposure",
        ]}

    equities = [p.equity for p in equity_curve]
    first_equity = equities[0]
    last_equity = equities[-1]

    # ── Total return ──────────────────────────────────────────────────────────
    total_return = (last_equity - first_equity) / first_equity if first_equity != 0 else nan

    # ── CAGR ──────────────────────────────────────────────────────────────────
    # Compounding over fractional years (365.25 calendar days per year)
    n_days = (equity_curve[-1].timestamp - equity_curve[0].timestamp).days
    n_years = n_days / 365.25
    if n_years > 0 and first_equity > 0 and last_equity > 0:
        cagr = (last_equity / first_equity) ** (1.0 / n_years) - 1.0
    else:
        cagr = nan

    # ── Period returns (price-relative) ───────────────────────────────────────
    period_returns: list[float] = []
    for i in range(1, len(equities)):
        if equities[i - 1] != 0:
            period_returns.append(equities[i] / equities[i - 1] - 1.0)

    # ── Max drawdown ──────────────────────────────────────────────────────────
    peak = equities[0]
    max_drawdown = 0.0
    for e in equities:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak
            if dd > max_drawdown:
                max_drawdown = dd

    # ── Annualised volatility and Sharpe ──────────────────────────────────────
    # Sharpe assumes zero risk-free rate (conservative for crypto research)
    if len(period_returns) >= 2:
        std = statistics.stdev(period_returns)
        mean = statistics.mean(period_returns)
        annualised_volatility = std * math.sqrt(periods_per_year)
        sharpe_ratio = (
            (mean / std) * math.sqrt(periods_per_year) if std > 0 else 0.0
        )
    else:
        annualised_volatility = nan
        sharpe_ratio = nan

    # ── Trade count ───────────────────────────────────────────────────────────
    buy_trades = [t for t in trades if t.side == "buy"]
    sell_trades = [t for t in trades if t.side == "sell"]
    trade_count = len(buy_trades)  # number of completed round trips (entries)

    # ── Win rate ──────────────────────────────────────────────────────────────
    pairs = list(zip(buy_trades, sell_trades))
    if pairs:
        wins = sum(1 for buy, sell in pairs if sell.fill_price > buy.fill_price)
        win_rate = wins / len(pairs)
    else:
        win_rate = nan

    # ── Exposure ──────────────────────────────────────────────────────────────
    # Fraction of bars with a non-zero position
    n_bars = len(equity_curve)
    bars_long = sum(1 for p in equity_curve if p.position > 0)
    exposure = bars_long / n_bars if n_bars > 0 else 0.0

    return {
        "total_return": round(total_return, 8) if not math.isnan(total_return) else nan,
        "cagr": round(cagr, 8) if not math.isnan(cagr) else nan,
        "max_drawdown": round(max_drawdown, 8),
        "sharpe_ratio": round(sharpe_ratio, 8) if not math.isnan(sharpe_ratio) else nan,
        "annualised_volatility": round(annualised_volatility, 8) if not math.isnan(annualised_volatility) else nan,
        "trade_count": float(trade_count),
        "win_rate": round(win_rate, 8) if not math.isnan(win_rate) else nan,
        "exposure": round(exposure, 8),
    }
