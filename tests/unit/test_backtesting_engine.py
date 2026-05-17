"""Tests for the AQCS minimal backtesting engine.

Critical invariants verified:
- Signal at T executes at T+1 (next-bar execution)
- Signal at T CANNOT execute at T (no same-bar fills)
- No lookahead: signal uses only data available at T
- Fees and slippage always applied (cannot be bypassed)
- Repeated runs produce identical results (determinism)
- Long-only: no short positions
- No pyramiding: only one position at a time
"""

from __future__ import annotations

import math
from datetime import timezone

import pandas as pd
import pytest

from aqcs.backtesting import BacktestConfig, BacktestResult, run_backtest
from aqcs.backtesting.metrics import compute_metrics
from aqcs.backtesting.models import EquityCurvePoint, Trade
from aqcs.backtesting.validation import validate_backtest_inputs
from aqcs.utils.events import SignalDirection

_UTC = timezone.utc


# ── OHLCV fixture helpers ─────────────────────────────────────────────────────

def _make_ohlcv(
    closes: list[float],
    opens: list[float] | None = None,
    start: str = "2024-01-01",
) -> pd.DataFrame:
    """Create minimal validated OHLCV DataFrame."""
    n = len(closes)
    if opens is None:
        opens = [closes[0]] + closes[:-1]  # open = previous close
    dates = pd.date_range(start=start, periods=n, freq="1D", tz="UTC")
    return pd.DataFrame({
        "timestamp": dates,
        "open": opens,
        "high": [max(o, c) * 1.005 for o, c in zip(opens, closes)],
        "low": [min(o, c) * 0.995 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": [1_000_000.0] * n,
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "exchange": "binance",
    })


def _signals(ohlcv: pd.DataFrame, values: list) -> pd.Series:
    """Create signal Series aligned to OHLCV timestamps."""
    timestamps = pd.DatetimeIndex(ohlcv["timestamp"])
    return pd.Series(values, index=timestamps, dtype=object)


def _config(**kwargs) -> BacktestConfig:
    defaults = dict(initial_capital=10_000.0, fee_bps=10.0, slippage_bps=5.0)
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def _zero_cost_config(**kwargs) -> BacktestConfig:
    defaults = dict(initial_capital=10_000.0, fee_bps=0.0, slippage_bps=0.0)
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


# ── BacktestConfig validation ─────────────────────────────────────────────────

class TestBacktestConfig:
    def test_valid_config_accepted(self) -> None:
        cfg = _config()
        assert cfg.initial_capital == 10_000.0

    def test_zero_initial_capital_rejected(self) -> None:
        with pytest.raises(Exception):
            BacktestConfig(initial_capital=0.0, fee_bps=10.0, slippage_bps=5.0)

    def test_negative_initial_capital_rejected(self) -> None:
        with pytest.raises(Exception):
            BacktestConfig(initial_capital=-1000.0, fee_bps=10.0, slippage_bps=5.0)

    def test_negative_fee_rejected(self) -> None:
        with pytest.raises(Exception):
            BacktestConfig(initial_capital=10_000.0, fee_bps=-1.0, slippage_bps=5.0)

    def test_negative_slippage_rejected(self) -> None:
        with pytest.raises(Exception):
            BacktestConfig(initial_capital=10_000.0, fee_bps=10.0, slippage_bps=-1.0)

    def test_zero_position_fraction_rejected(self) -> None:
        with pytest.raises(Exception):
            BacktestConfig(initial_capital=10_000.0, fee_bps=0.0, slippage_bps=0.0,
                           position_size_fraction=0.0)

    def test_position_fraction_above_one_rejected(self) -> None:
        with pytest.raises(Exception):
            BacktestConfig(initial_capital=10_000.0, fee_bps=0.0, slippage_bps=0.0,
                           position_size_fraction=1.5)

    def test_fee_factor_computation(self) -> None:
        cfg = BacktestConfig(initial_capital=10_000.0, fee_bps=10.0, slippage_bps=0.0)
        assert cfg.fee_factor() == pytest.approx(0.001)

    def test_slippage_factor_computation(self) -> None:
        cfg = BacktestConfig(initial_capital=10_000.0, fee_bps=0.0, slippage_bps=5.0)
        assert cfg.slippage_factor() == pytest.approx(0.0005)


# ── Input validation ──────────────────────────────────────────────────────────

class TestValidation:
    def test_empty_ohlcv_raises(self) -> None:
        ohlcv = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        sig = _signals(_make_ohlcv([100.0, 101.0]), [SignalDirection.NEUTRAL] * 2)
        with pytest.raises(ValueError, match="empty"):
            validate_backtest_inputs(ohlcv, sig, _config())

    def test_missing_column_raises(self) -> None:
        ohlcv = _make_ohlcv([100.0, 101.0]).drop(columns=["open"])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 2)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="missing"):
            validate_backtest_inputs(ohlcv, sig, _config())

    def test_non_monotonic_timestamps_raises(self) -> None:
        ohlcv = _make_ohlcv([100.0, 101.0, 102.0])
        # Reverse to make non-monotonic
        ohlcv["timestamp"] = ohlcv["timestamp"].iloc[::-1].values
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        with pytest.raises(ValueError, match="monotonic"):
            validate_backtest_inputs(ohlcv, sig, _config())

    def test_no_overlap_raises(self) -> None:
        ohlcv = _make_ohlcv([100.0, 101.0], start="2024-01-01")
        # Signals with completely different timestamps
        dates = pd.date_range("2025-01-01", periods=2, freq="1D", tz="UTC")
        sig = pd.Series([SignalDirection.NEUTRAL] * 2, index=dates, dtype=object)
        with pytest.raises(ValueError, match="timestamp"):
            validate_backtest_inputs(ohlcv, sig, _config())

    def test_valid_inputs_do_not_raise(self) -> None:
        ohlcv = _make_ohlcv([100.0, 101.0, 102.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        validate_backtest_inputs(ohlcv, sig, _config())  # must not raise


# ── Execution timing — critical correctness invariants ────────────────────────

class TestNextBarExecution:
    def test_signal_at_T_executes_at_T_plus_1(self) -> None:
        """Signal LONG at bar index 1 → buy at open of bar index 2."""
        closes = [100.0, 100.0, 105.0, 110.0, 110.0]
        opens  = [100.0, 100.0, 105.0, 110.0, 110.0]
        ohlcv = _make_ohlcv(closes, opens)
        # Signal LONG at bar 1 (index 1)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL,
            SignalDirection.LONG,    # bar 1 → execute at bar 2
            SignalDirection.LONG,
            SignalDirection.LONG,
            SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 1
        # Buy must occur at bar 2 (the next bar after signal bar 1)
        expected_buy_ts = pd.Timestamp("2024-01-03", tz="UTC").to_pydatetime()
        assert buys[0].timestamp == expected_buy_ts
        # Fill price = open of bar 2 = 105.0 (no fees/slippage in this test)
        assert buys[0].fill_price == pytest.approx(105.0)

    def test_no_same_bar_execution(self) -> None:
        """Signal at bar T must NOT execute at bar T."""
        closes = [100.0, 105.0, 110.0]
        ohlcv = _make_ohlcv(closes)
        # LONG at bar 0 — should NOT execute at bar 0
        sig = _signals(ohlcv, [
            SignalDirection.LONG,    # bar 0 signal
            SignalDirection.LONG,
            SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 1
        # Must be at bar 1 (the next bar), not bar 0
        bar_0_ts = pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime()
        assert buys[0].timestamp != bar_0_ts, (
            "Same-bar execution detected: buy occurred at the same bar as the signal"
        )

    def test_first_bar_signal_cannot_execute_same_bar(self) -> None:
        """Even if the very first bar is LONG, no execution can happen at bar 0."""
        ohlcv = _make_ohlcv([100.0, 105.0])
        sig = _signals(ohlcv, [SignalDirection.LONG, SignalDirection.LONG])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        # Shifted signals: shifted[0] = NaN, shifted[1] = LONG
        # So no buy at bar 0, buy at bar 1
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 1
        assert buys[0].fill_price == pytest.approx(100.0)  # open of bar 1 = prev close = 100

    def test_sell_also_executes_at_next_bar(self) -> None:
        """EXIT signal at bar T → sell at open of bar T+1."""
        closes = [100.0, 100.0, 110.0, 110.0, 110.0]
        opens  = [100.0, 100.0, 110.0, 120.0, 120.0]
        ohlcv = _make_ohlcv(closes, opens)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL,
            SignalDirection.LONG,    # buy at bar 2 open = 110
            SignalDirection.LONG,
            SignalDirection.NEUTRAL, # sell at bar 4 open = 120
            SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        sells = [t for t in result.trades if t.side == "sell"]
        assert len(sells) == 1
        assert sells[0].fill_price == pytest.approx(120.0)  # open of bar 4


# ── Fee and slippage enforcement ──────────────────────────────────────────────

class TestFeeAndSlippage:
    def test_buy_price_includes_slippage(self) -> None:
        opens = [100.0, 100.0, 200.0, 200.0]
        closes = [100.0, 100.0, 200.0, 200.0]
        ohlcv = _make_ohlcv(closes, opens)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.NEUTRAL, SignalDirection.NEUTRAL,
        ])
        # slippage_bps=50 (0.5%) → fill = 200 * 1.005 = 201.0
        cfg = BacktestConfig(initial_capital=100_000.0, fee_bps=0.0, slippage_bps=50.0)
        result = run_backtest(ohlcv, sig, cfg)
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 1
        assert buys[0].fill_price == pytest.approx(200.0 * 1.005)

    def test_sell_price_includes_slippage(self) -> None:
        opens = [100.0, 100.0, 200.0, 200.0, 200.0]
        closes = [100.0, 100.0, 200.0, 200.0, 200.0]
        ohlcv = _make_ohlcv(closes, opens)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.NEUTRAL,
            SignalDirection.NEUTRAL,
        ])
        cfg = BacktestConfig(initial_capital=100_000.0, fee_bps=0.0, slippage_bps=50.0)
        result = run_backtest(ohlcv, sig, cfg)
        sells = [t for t in result.trades if t.side == "sell"]
        assert len(sells) == 1
        assert sells[0].fill_price == pytest.approx(200.0 * (1 - 0.005))

    def test_fee_deducted_on_buy(self) -> None:
        ohlcv = _make_ohlcv([100.0, 100.0, 100.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL, SignalDirection.LONG, SignalDirection.NEUTRAL])
        cfg = BacktestConfig(initial_capital=10_000.0, fee_bps=100.0, slippage_bps=0.0)
        result = run_backtest(ohlcv, sig, cfg)
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 1
        # fee = fill_price * quantity * 0.01
        assert buys[0].fee > 0.0
        # fee should be approximately 1% of transaction value
        expected_fee_rate = buys[0].fee / buys[0].value
        assert expected_fee_rate == pytest.approx(0.01, rel=1e-3)

    def test_zero_fee_and_slippage_only_when_explicitly_set(self) -> None:
        """fee_bps=0 and slippage_bps=0 must be set explicitly — they ARE allowed."""
        ohlcv = _make_ohlcv([100.0, 100.0, 110.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL, SignalDirection.LONG, SignalDirection.NEUTRAL])
        cfg = _zero_cost_config()
        result = run_backtest(ohlcv, sig, cfg)
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 1
        assert buys[0].fee == pytest.approx(0.0)
        assert buys[0].slippage_amount == pytest.approx(0.0)


# ── Equity curve correctness ──────────────────────────────────────────────────

class TestEquityCurve:
    def test_initial_equity_is_initial_capital(self) -> None:
        ohlcv = _make_ohlcv([100.0, 100.0, 100.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        result = run_backtest(ohlcv, sig, _zero_cost_config(initial_capital=5_000.0))
        assert result.equity_curve[0].equity == pytest.approx(5_000.0)

    def test_no_trades_equity_stays_constant(self) -> None:
        ohlcv = _make_ohlcv([100.0, 105.0, 110.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        result = run_backtest(ohlcv, sig, _zero_cost_config(initial_capital=10_000.0))
        for point in result.equity_curve:
            assert point.equity == pytest.approx(10_000.0)

    def test_equity_updates_with_price_when_long(self) -> None:
        closes = [100.0, 100.0, 200.0]
        opens  = [100.0, 100.0, 100.0]
        ohlcv = _make_ohlcv(closes, opens)
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL, SignalDirection.LONG, SignalDirection.NEUTRAL])
        result = run_backtest(ohlcv, sig, _zero_cost_config(initial_capital=10_000.0))
        # After buy at bar 2 open (100), holding at close of bar 2 (200):
        # equity ≈ 10_000 * (200 / 100) = 20_000
        assert result.equity_curve[-1].equity == pytest.approx(20_000.0, rel=1e-4)

    def test_equity_curve_length_equals_n_bars(self) -> None:
        n = 10
        closes = [100.0 + i for i in range(n)]
        ohlcv = _make_ohlcv(closes)
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * n)
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        assert len(result.equity_curve) == n

    def test_cash_plus_position_value_equals_equity(self) -> None:
        closes = [100.0, 100.0, 150.0, 200.0]
        opens  = [100.0, 100.0, 100.0, 150.0]
        ohlcv = _make_ohlcv(closes, opens)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        for point in result.equity_curve:
            implied_equity = point.cash + point.position * point.price
            assert implied_equity == pytest.approx(point.equity, rel=1e-10)


# ── Trade semantics ───────────────────────────────────────────────────────────

class TestTrades:
    def test_long_only_no_short_positions(self) -> None:
        ohlcv = _make_ohlcv([100.0] * 5)
        sig = _signals(ohlcv, [SignalDirection.SHORT] * 5)
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        # SHORT signals should be treated as EXIT (not enter short)
        buys = [t for t in result.trades if t.side == "buy"]
        assert len(buys) == 0, "No buy should occur from SHORT signals in long-only engine"

    def test_no_pyramiding_single_position(self) -> None:
        ohlcv = _make_ohlcv([100.0, 100.0, 105.0, 108.0, 110.0, 115.0])
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        buys = [t for t in result.trades if t.side == "buy"]
        # Only 1 buy even though LONG persists across multiple bars
        assert len(buys) == 1, "No pyramiding — only one position at a time"

    def test_buy_sell_pair_generated(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 110.0]
        opens  = [100.0, 100.0, 100.0, 110.0, 110.0]
        ohlcv = _make_ohlcv(closes, opens)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.NEUTRAL,
            SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        sides = [t.side for t in result.trades]
        assert sides == ["buy", "sell"]


# ── Metrics correctness ───────────────────────────────────────────────────────

class TestMetrics:
    def test_zero_return_when_no_trades(self) -> None:
        ohlcv = _make_ohlcv([100.0, 110.0, 120.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        assert result.metrics["total_return"] == pytest.approx(0.0)

    def test_max_drawdown_zero_when_equity_only_rises(self) -> None:
        # Equity never falls: all NEUTRAL, no position
        ohlcv = _make_ohlcv([100.0] * 5)
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 5)
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        assert result.metrics["max_drawdown"] == pytest.approx(0.0)

    def test_trade_count_matches_number_of_entries(self) -> None:
        closes = [100.0, 100.0, 110.0, 110.0, 100.0, 100.0, 110.0, 110.0]
        ohlcv = _make_ohlcv(closes)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.NEUTRAL,
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.NEUTRAL,
        ])
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        assert result.metrics["trade_count"] == pytest.approx(2.0)

    def test_exposure_zero_when_no_trades(self) -> None:
        ohlcv = _make_ohlcv([100.0] * 5)
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 5)
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        assert result.metrics["exposure"] == pytest.approx(0.0)

    def test_win_rate_nan_when_no_completed_trades(self) -> None:
        ohlcv = _make_ohlcv([100.0, 100.0, 110.0])
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG, SignalDirection.LONG,
        ])
        # Buy but never sell (position still open at end)
        result = run_backtest(ohlcv, sig, _zero_cost_config())
        assert math.isnan(result.metrics["win_rate"])


# ── Determinism ───────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_repeated_runs_produce_identical_results(self) -> None:
        closes = [100.0, 105.0, 103.0, 108.0, 112.0, 109.0, 115.0]
        ohlcv = _make_ohlcv(closes)
        sig = _signals(ohlcv, [
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.LONG, SignalDirection.LONG,
            SignalDirection.NEUTRAL, SignalDirection.LONG,
            SignalDirection.NEUTRAL,
        ])
        cfg = _config(fee_bps=10.0, slippage_bps=5.0)

        result1 = run_backtest(ohlcv, sig, cfg)
        result2 = run_backtest(ohlcv, sig, cfg)

        assert result1.metrics == result2.metrics
        assert len(result1.trades) == len(result2.trades)
        for t1, t2 in zip(result1.trades, result2.trades):
            assert t1.fill_price == t2.fill_price
            assert t1.quantity == t2.quantity
            assert t1.fee == t2.fee

    def test_metrics_are_deterministic(self) -> None:
        curve = tuple([
            EquityCurvePoint(
                timestamp=pd.Timestamp(f"2024-01-0{i+1}", tz="UTC").to_pydatetime(),
                equity=10_000.0 * (1.01 ** i),
                cash=10_000.0 * (1.01 ** i),
                position=0.0,
                price=100.0,
            )
            for i in range(5)
        ])
        m1 = compute_metrics(curve, (), 252)
        m2 = compute_metrics(curve, (), 252)
        # Compare key-by-key to handle NaN (NaN != NaN in Python)
        assert set(m1.keys()) == set(m2.keys())
        for key in m1:
            v1, v2 = m1[key], m2[key]
            if math.isnan(v1) and math.isnan(v2):
                continue  # both NaN → deterministic
            assert v1 == pytest.approx(v2), f"Metric '{key}' differs between runs"


# ── Experiment tracking integration ──────────────────────────────────────────

class TestExperimentTracking:
    def test_experiment_record_created_when_tracker_provided(self, tmp_path) -> None:
        from aqcs.experiments.tracker import ExperimentTracker
        from aqcs.experiments.storage import list_experiments

        ohlcv = _make_ohlcv([100.0, 105.0, 110.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        tracker = ExperimentTracker(tmp_path)
        result = run_backtest(ohlcv, sig, _zero_cost_config(), tracker=tracker)
        assert result.experiment_id != ""
        saved = list_experiments(tmp_path)
        assert len(saved) >= 1

    def test_no_tracker_still_works(self) -> None:
        ohlcv = _make_ohlcv([100.0, 105.0, 110.0])
        sig = _signals(ohlcv, [SignalDirection.NEUTRAL] * 3)
        result = run_backtest(ohlcv, sig, _zero_cost_config(), tracker=None)
        assert result.experiment_id == ""
        assert isinstance(result, BacktestResult)
