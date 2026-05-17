"""Deterministic execution model — fee and slippage computation.

Phase 1 assumptions (see docs/architecture/backtesting-standards.md):
- All fills occur at the OPEN of the next bar after signal generation
- Buy fill price = open * (1 + slippage_factor)
- Sell fill price = open * (1 - slippage_factor)
- Fee = fill_value * fee_factor, deducted at fill time
- No partial fills, no intrabar simulation, no leverage
"""

from __future__ import annotations

from aqcs.backtesting.models import BacktestConfig


def buy_fill_price(open_price: float, config: BacktestConfig) -> float:
    """Compute the fill price for a buy order.

    fill_price = open_price * (1 + slippage_factor)
    Slippage always increases the buy cost (conservative assumption).
    """
    return float(open_price * (1.0 + config.slippage_factor()))


def sell_fill_price(open_price: float, config: BacktestConfig) -> float:
    """Compute the fill price for a sell order.

    fill_price = open_price * (1 - slippage_factor)
    Slippage always decreases the sell proceeds (conservative assumption).
    """
    return float(open_price * (1.0 - config.slippage_factor()))


def compute_fee(value: float, config: BacktestConfig) -> float:
    """Compute the fee on a transaction.

    fee = value * fee_factor
    Fee is charged on the gross transaction value (fill_price * quantity).
    """
    return float(value * config.fee_factor())


def compute_buy_quantity(
    available_cash: float,
    fill_price: float,
    config: BacktestConfig,
) -> float:
    """Compute the quantity to buy given available cash and fill price.

    quantity = (available_cash * position_size_fraction) / fill_price_with_fee

    Accounts for the fee so we don't overspend available cash.
    If allow_fractional=False, quantity is floored to an integer.
    """
    max_spend = available_cash * config.position_size_fraction
    # The effective cost per unit including fee: fill_price * (1 + fee_factor)
    cost_per_unit = fill_price * (1.0 + config.fee_factor())
    quantity = max_spend / cost_per_unit if cost_per_unit > 0 else 0.0
    if not config.allow_fractional:
        quantity = float(int(quantity))
    return quantity
