"""Backtesting data models — typed, immutable, Pydantic-validated where user-facing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# ── Input model (Pydantic — user-facing, validates at construction) ────────────


class BacktestConfig(BaseModel):
    """Configuration for a single backtest run.

    All assumptions are explicit. No hidden defaults.
    Fee and slippage are mandatory (cannot be implicitly zero).
    """

    initial_capital: float = Field(..., gt=0, description="Starting capital in quote currency")
    fee_bps: float = Field(..., ge=0, description="Taker fee in basis points (e.g., 10 = 0.10%)")
    slippage_bps: float = Field(..., ge=0, description="Half-spread slippage in bps per side")
    position_size_fraction: float = Field(
        default=1.0,
        gt=0,
        le=1.0,
        description="Fraction of equity deployed per trade (1.0 = fully invested)",
    )
    allow_fractional: bool = Field(
        default=True,
        description="Allow fractional position sizes (standard for crypto spot)",
    )
    start_date: str = Field(
        default="",
        description="Start date YYYY-MM-DD (UTC). Empty = use all available data.",
    )
    end_date: str = Field(
        default="",
        description="End date YYYY-MM-DD (UTC, inclusive). Empty = use all data.",
    )
    periods_per_year: int = Field(
        default=252,
        gt=0,
        description="Trading periods per year for annualisation (daily=252, hourly=8760)",
    )

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def validate_dates(self) -> BacktestConfig:
        for field_name, date_str in [("start_date", self.start_date), ("end_date", self.end_date)]:
            if date_str:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                    raise ValueError(
                        f"{field_name} must be in exact YYYY-MM-DD format, got '{date_str}'"
                    )
                try:
                    _date.fromisoformat(date_str)
                except ValueError:
                    raise ValueError(
                        f"{field_name} must be in exact YYYY-MM-DD format, got '{date_str}'"
                    ) from None
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must not be after end_date ({self.end_date})"
            )
        return self

    def fee_factor(self) -> float:
        return self.fee_bps / 10_000

    def slippage_factor(self) -> float:
        return self.slippage_bps / 10_000


# ── Result models (frozen dataclasses — internal, built by the engine) ────────


@dataclass(frozen=True)
class Trade:
    """Record of a single executed order."""

    timestamp: datetime
    side: str  # "buy" or "sell"
    fill_price: float  # execution price after slippage
    quantity: float
    fee: float  # total fee paid
    slippage_amount: float  # total slippage cost (fill_price vs open_price) * quantity
    value: float  # fill_price * quantity (before fee)


@dataclass(frozen=True)
class EquityCurvePoint:
    """Snapshot of portfolio state at the close of a single bar."""

    timestamp: datetime
    equity: float  # cash + position * close_price
    cash: float
    position: float  # units of asset held
    price: float  # close price of the bar


@dataclass(frozen=True)
class BacktestResult:
    """Complete result of a single backtest run."""

    config: BacktestConfig
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityCurvePoint, ...]
    metrics: dict[str, float]
    n_bars: int
    experiment_id: str = ""  # UUID string if ExperimentTracker was provided
