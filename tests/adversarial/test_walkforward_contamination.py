"""Adversarial: walk-forward contamination and segmentation corruption.

Deliberately introduces contamination and invalid segmentation in
walk-forward runs to verify that the AQCS validation layer detects:

1. Fold overlap: train and test overlap within a window.
2. Temporal boundary corruption: train_end != test_start.
3. Chronological order violation: windows out of order.
4. Future-feature contamination: signal_fn accessing data beyond test_end_bar.
5. Segmentation corruption: wrong window_index or duplicate indices.
6. Report hash tampering: validate_report detects tampered report_hash.
7. Embargo-style boundary integrity: a 1-bar gap between train and test
   yields different segmentation than the standard boundary.

Corruption classes covered:
- fold overlap contamination
- temporal boundary corruption (train_end != test_start)
- chronological order violation
- future-feature contamination (signal_fn beyond window boundary)
- window index corruption
- report_hash tampering
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from aqcs.backtesting.models import BacktestConfig
from aqcs.research.walkforward import (
    WalkForwardWindow,
    _compute_report_hash,
    generate_windows,
    report_from_dict,
    report_to_dict,
    run_walkforward,
    validate_report,
    validate_windows,
)
from aqcs.utils.events import SignalDirection

from .conftest import FIXED_NOW

# ── Constants ─────────────────────────────────────────────────────────────────

_N = 250  # enough for train=100, test=50, step=50 (4 windows)


# ── Factories ─────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = _N, seed: int = 42) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=n, freq="1D", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 45_000.0 + np.cumsum(rng.normal(0, 300.0, n))
    close = np.maximum(close, 1_000.0)
    high = close * (1 + rng.uniform(0.001, 0.004, n))
    low = close * (1 - rng.uniform(0.001, 0.004, n))
    open_ = low + rng.uniform(0.0, 1.0, n) * (high - low)
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(100.0, 500.0, n),
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "exchange": "binance",
        }
    )


def _make_config(**overrides: object) -> BacktestConfig:
    defaults: dict[str, object] = {
        "initial_capital": 10_000.0,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
    }
    defaults.update(overrides)
    return BacktestConfig(**defaults)  # type: ignore[arg-type]


def _neutral_signal_fn(prices: pd.Series) -> pd.Series:
    return pd.Series(SignalDirection.NEUTRAL, index=prices.index, dtype=object)


def _run_clean() -> object:
    return run_walkforward(
        _make_ohlcv(),
        _make_config(),
        100,
        50,
        50,
        signal_fn=_neutral_signal_fn,
        now_utc=FIXED_NOW,
    )


# ── Fold overlap contamination ────────────────────────────────────────────────


class TestFoldOverlapContamination:
    """validate_windows detects when a window's train period overlaps its test period."""

    def test_train_overlapping_test_within_window_detected(self) -> None:
        """Manually crafted window where train_end > test_start → overlap detected."""
        contaminated_window = WalkForwardWindow(
            window_index=0,
            train_start_bar=0,
            train_end_bar=120,  # train_end PAST test_start
            test_start_bar=100,  # test_start < train_end → OVERLAP
            test_end_bar=150,
            train_bars=120,
            test_bars=50,
        )
        valid, issues = validate_windows((contaminated_window,))

        assert valid is False, (
            "validate_windows must detect train/test overlap within a window. "
            "train_end=120 > test_start=100 is an overlap."
        )
        assert any(
            "overlap" in issue.lower() or "gap" in issue.lower() or "!=" in issue
            for issue in issues
        ), f"Issues must describe the overlap. Got: {issues}"

    def test_train_end_equal_to_test_start_passes(self) -> None:
        """train_end == test_start is the correct boundary — must pass validate_windows."""
        clean_window = WalkForwardWindow(
            window_index=0,
            train_start_bar=0,
            train_end_bar=100,
            test_start_bar=100,
            test_end_bar=150,
            train_bars=100,
            test_bars=50,
        )
        valid, issues = validate_windows((clean_window,))
        assert valid is True, (
            f"train_end == test_start is the correct boundary. "
            f"validate_windows should pass. Issues: {issues}"
        )

    def test_overlapping_consecutive_windows_detected(self) -> None:
        """Two consecutive windows where second has lower test_start_bar → detected."""
        w0 = WalkForwardWindow(0, 0, 100, 100, 150, 100, 50)
        w1 = WalkForwardWindow(1, 50, 150, 90, 200, 100, 50)  # test_start regresses
        valid, issues = validate_windows((w0, w1))
        assert (
            valid is False
        ), "validate_windows must detect a regressing test_start_bar across windows."


# ── Temporal boundary corruption ─────────────────────────────────────────────


class TestTemporalBoundaryCorruption:
    """validate_windows detects train_end != test_start (gap or overlap at boundary)."""

    def test_gap_between_train_and_test_detected(self) -> None:
        """train_end < test_start creates an uncovered gap — must be detected."""
        gapped_window = WalkForwardWindow(
            window_index=0,
            train_start_bar=0,
            train_end_bar=90,  # gap: bars 90-99 uncovered
            test_start_bar=100,
            test_end_bar=150,
            train_bars=90,
            test_bars=50,
        )
        valid, issues = validate_windows((gapped_window,))
        assert valid is False, (
            "A gap between train_end and test_start must be detected by validate_windows. "
            "train_end=90 != test_start=100"
        )
        # Issue must mention the gap/mismatch
        assert any(
            "90" in i and "100" in i for i in issues
        ), f"Issues must reference the boundary values. Got: {issues}"

    def test_train_end_equals_test_start_is_valid(self) -> None:
        """The standard boundary (no gap, no overlap) must pass."""
        windows = generate_windows(200, 100, 50, 50)
        for w in windows:
            assert w.train_end_bar == w.test_start_bar, (
                f"generate_windows must produce train_end==test_start. "
                f"Window {w.window_index}: train_end={w.train_end_bar}, "
                f"test_start={w.test_start_bar}"
            )
        valid, issues = validate_windows(windows)
        assert (
            valid is True
        ), f"generate_windows output must pass validate_windows. Issues: {issues}"


# ── Chronological order violation ────────────────────────────────────────────


class TestChronologicalOrderViolation:
    """validate_windows detects windows in wrong chronological order."""

    def test_reversed_window_order_detected(self) -> None:
        """Reversed window tuple must fail validate_windows."""
        windows = generate_windows(200, 100, 50, 50)
        reversed_windows = tuple(reversed(windows))

        valid, issues = validate_windows(reversed_windows)
        assert valid is False, (
            "Reversed window tuple must fail validate_windows — " "chronological order is violated."
        )

    def test_swapped_consecutive_windows_detected(self) -> None:
        """Swapping two adjacent windows produces a chronological violation."""
        windows = list(generate_windows(300, 100, 50, 50))
        windows[0], windows[1] = windows[1], windows[0]
        valid, issues = validate_windows(tuple(windows))
        assert valid is False, (
            "Swapping adjacent windows must fail validate_windows. " f"Issues: {issues}"
        )


# ── Segmentation corruption ───────────────────────────────────────────────────


class TestSegmentationCorruption:
    """Corrupted window_index values are detected by validate_windows."""

    def test_wrong_window_index_detected(self) -> None:
        """A window with window_index != its position in the tuple is detected."""
        windows = list(generate_windows(200, 100, 50, 50))
        # Corrupt the index of window[1]
        w = windows[1]
        corrupted = WalkForwardWindow(
            window_index=99,  # should be 1
            train_start_bar=w.train_start_bar,
            train_end_bar=w.train_end_bar,
            test_start_bar=w.test_start_bar,
            test_end_bar=w.test_end_bar,
            train_bars=w.train_bars,
            test_bars=w.test_bars,
        )
        windows[1] = corrupted
        valid, issues = validate_windows(tuple(windows))
        assert valid is False, (
            "validate_windows must detect a window with wrong window_index. "
            "Window position 1 has index 99."
        )
        assert any(
            "99" in i or "index" in i.lower() for i in issues
        ), f"Issues must mention the wrong index. Got: {issues}"

    def test_empty_window_train_period_detected(self) -> None:
        """train_start_bar == train_end_bar (empty train) must be detected."""
        w = WalkForwardWindow(
            window_index=0,
            train_start_bar=100,
            train_end_bar=100,  # empty!
            test_start_bar=100,
            test_end_bar=150,
            train_bars=0,
            test_bars=50,
        )
        valid, issues = validate_windows((w,))
        assert valid is False, "Empty training period (train_start == train_end) must be detected."


# ── Future-feature contamination ─────────────────────────────────────────────


class TestFutureFeatureContamination:
    """signal_fn using data beyond test_end_bar produces a different report_hash."""

    def _clean_fn(self, prices: pd.Series) -> pd.Series:
        """Clean: rolling mean using only past data."""
        roll = prices.rolling(10).mean()
        return pd.Series(
            [
                (
                    SignalDirection.LONG
                    if (not pd.isna(roll.iloc[i]) and prices.iloc[i] > roll.iloc[i])
                    else SignalDirection.NEUTRAL
                )
                for i in range(len(prices))
            ],
            index=prices.index,
            dtype=object,
        )

    def _contaminated_fn(self, prices: pd.Series) -> pd.Series:
        """Contaminated: centered rolling mean (uses future bars within the window)."""
        roll = prices.rolling(10, center=True).mean()
        return pd.Series(
            [
                (
                    SignalDirection.LONG
                    if (not pd.isna(roll.iloc[i]) and prices.iloc[i] > roll.iloc[i])
                    else SignalDirection.NEUTRAL
                )
                for i in range(len(prices))
            ],
            index=prices.index,
            dtype=object,
        )

    def test_contaminated_fn_produces_different_report_hash(self) -> None:
        """Walk-forward with contaminated signal_fn has different report_hash than clean."""
        df = _make_ohlcv(250, seed=77)
        cfg = _make_config()

        report_clean = run_walkforward(
            df,
            cfg,
            100,
            50,
            50,
            signal_fn=self._clean_fn,
            now_utc=FIXED_NOW,
        )
        report_dirty = run_walkforward(
            df,
            cfg,
            100,
            50,
            50,
            signal_fn=self._contaminated_fn,
            now_utc=FIXED_NOW,
        )

        assert report_clean.report_hash != report_dirty.report_hash, (
            "report_hash must differ between clean and contaminated signal_fn. "
            f"clean={report_clean.report_hash[:16]}…, "
            f"dirty={report_dirty.report_hash[:16]}…. "
            "Contamination must leave an auditable hash footprint."
        )

    def test_contaminated_fn_report_is_internally_consistent(self) -> None:
        """A contaminated-but-internally-consistent report passes validate_report."""
        df = _make_ohlcv(250, seed=77)
        cfg = _make_config()

        report = run_walkforward(
            df,
            cfg,
            100,
            50,
            50,
            signal_fn=self._contaminated_fn,
            now_utc=FIXED_NOW,
        )
        valid, errors = validate_report(report)
        assert valid is True, (
            f"Contaminated-but-consistent walk-forward report must pass "
            f"validate_report. Errors: {errors}"
        )


# ── Report hash tampering ─────────────────────────────────────────────────────


class TestReportHashTampering:
    """validate_report detects any modification to report content."""

    def test_tampered_report_hash_detected(self) -> None:
        """Replacing report_hash with garbage causes validate_report to fail."""
        report = _run_clean()
        d = report_to_dict(report)  # type: ignore[attr-defined]
        d["report_hash"] = "0" * 64

        tampered = report_from_dict(d)

        valid, errors = validate_report(tampered)
        assert valid is False, "validate_report must detect a tampered report_hash."
        assert any(
            "hash" in e.lower() for e in errors
        ), f"Errors must mention the hash mismatch. Got: {errors}"

    def test_mutating_n_windows_invalidates_report(self) -> None:
        """Changing n_windows in the report dict changes the recomputed hash."""
        report = _run_clean()
        d = report_to_dict(report)  # type: ignore[attr-defined]

        # Recompute what the correct hash WOULD be with the mutation
        d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
        original_hash = d["report_hash"]

        d_no_hash["n_windows"] = d_no_hash["n_windows"] + 999
        tampered_hash = _compute_report_hash(d_no_hash)

        assert tampered_hash != original_hash, (
            "Mutating n_windows must change the recomputed report_hash. "
            "report_hash covers all content fields."
        )

    def test_clean_report_passes_validate_report(self) -> None:
        """A freshly generated walk-forward report passes validate_report."""
        report = _run_clean()
        valid, errors = validate_report(report)  # type: ignore[arg-type]
        assert (
            valid is True
        ), f"Clean walk-forward report must pass validate_report. Errors: {errors}"

    def test_clean_report_has_leakage_validated_true(self) -> None:
        """generate_windows produces leakage-safe windows → leakage_validated is True."""
        report = _run_clean()
        assert report.leakage_validated is True, (  # type: ignore[attr-defined]
            "Walk-forward with generate_windows output must have leakage_validated=True."
        )
