"""Deterministic walk-forward validation infrastructure for AQCS.

Walk-forward validation segments a historical series into sequential,
non-overlapping temporal windows.  Each window has a training period
and an evaluation (test) period.  The signal is computed on all data
up to the test window's end bar — no future data is visible.

Window layout (example: train=500, test=100, step=100):

  Window 0: train [0, 500)  test [500, 600)
  Window 1: train [100, 600)  test [600, 700)
  Window 2: train [200, 700)  test [700, 800)
  ...

Leakage safety
--------------
- Within each window: train_end == test_start (no gap, no overlap).
- Signal computation uses only data in [0, test_end_bar) — no future.
- Backtest evaluates only [test_start_bar, test_end_bar).
- If step_bars < test_bars, consecutive test windows overlap in calendar
  time; this is flagged in ``summary.test_overlap`` for caller awareness.

Determinism
-----------
- Windows are generated in ascending order by ``train_start_bar``.
- ``report_hash`` is SHA-256 of the serialised report (excluding itself).
- ``generation_timestamp_utc`` is the only wall-clock field; inject
  ``now_utc`` in tests.

This module does NOT perform parameter optimisation, ML/RL, or live
execution.  It is offline, deterministic, and read-only with respect to
the input data.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from aqcs.backtesting.engine import run_backtest
from aqcs.backtesting.models import BacktestConfig, BacktestResult
from aqcs.signals.combined import combined_momentum_trend_signal

REPORT_VERSION: str = "2"
# Version history:
#   "1" — initial release (mean/std/min/max for total_return only)
#   "2" — adds variance/dispersion for sharpe and drawdown, CV, range,
#          and governance advisory counts (TASK-WALKFORWARD-VARIANCE-001)

# Minimum training bars needed for the default signal to be meaningful.
# combined_momentum_trend_signal defaults: momentum_window=20, trend_long_window=50.
_MIN_WARMUP_BARS: int = 50

# ── Governance floor/ceiling thresholds ──────────────────────────────────────
# Used for advisory governance counts in WalkForwardSummary.
# These values must match governance_thresholds.RETURN_FLOOR / DRAWDOWN_CEIL /
# SHARPE_FLOOR once TASK-GOVERNANCE-CONSOLIDATION-001 merges to master.
# Any change requires an ADR and explicit human approval.
_RETURN_FLOOR: float = -0.10  # total_return below this → governance advisory
_DRAWDOWN_CEIL: float = 0.30  # max_drawdown above this → governance advisory
_SHARPE_FLOOR: float = 0.0  # sharpe_ratio at/below this → governance advisory

# Minimum |mean| below which coefficient of variation is treated as undefined.
_CV_MEAN_EPS: float = 1e-10


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WalkForwardWindow:
    """Single temporal window in a walk-forward evaluation.

    All bar indices are 0-based and use Python slice semantics:
    ``train_end_bar`` and ``test_end_bar`` are exclusive upper bounds.
    """

    window_index: int
    train_start_bar: int
    train_end_bar: int
    test_start_bar: int
    test_end_bar: int
    train_bars: int
    test_bars: int


@dataclass(frozen=True)
class WalkForwardResult:
    """Outcome of evaluating a single walk-forward window.

    ``failed`` is True when the backtest engine raised an exception
    (e.g. no bars in the test date range).  All metric values are NaN
    and ``n_trades`` is 0 for failed windows.
    """

    window_index: int
    train_start_bar: int
    train_end_bar: int
    test_start_bar: int
    test_end_bar: int
    metrics: dict[str, float]
    n_trades: int
    n_bars_evaluated: int
    failed: bool
    failure_reason: str


@dataclass(frozen=True)
class WalkForwardSummary:
    """Aggregate statistics across all walk-forward windows.

    Version 2 additions
    -------------------
    Dispersion metrics for total_return (range, cv) and full dispersion for
    sharpe_ratio and max_drawdown (std, min, max).  Governance advisory counts
    for folds that breach Phase-1B acceptability thresholds.

    All float fields are NaN when there are fewer than 2 evaluated windows
    (or fewer than 2 non-NaN values for that metric).  Governance advisory
    counts are integers and default to 0 when no evaluated windows exist.

    Advisory-only
    -------------
    Governance advisory counts and instability metrics are for human review
    only.  They do not auto-approve or auto-reject strategies, do not rank
    deployment candidates, and do not imply trading readiness.
    """

    # ── Window counts ─────────────────────────────────────────────────────────
    n_windows_total: int
    n_windows_evaluated: int
    n_windows_failed: int
    n_windows_profitable: int

    # ── Total return dispersion ───────────────────────────────────────────────
    mean_total_return: float
    std_total_return: float
    min_total_return: float
    max_total_return: float
    range_total_return: float  # max - min; NaN if < 2 evaluated windows
    cv_total_return: float  # std / |mean|; NaN if |mean| < eps or < 2 windows

    # ── Sharpe ratio dispersion ───────────────────────────────────────────────
    mean_sharpe_ratio: float
    std_sharpe_ratio: float  # NaN if < 2 evaluated windows
    min_sharpe_ratio: float  # NaN if no evaluated windows
    max_sharpe_ratio: float  # NaN if no evaluated windows

    # ── Max drawdown dispersion ───────────────────────────────────────────────
    mean_max_drawdown: float
    std_max_drawdown: float  # NaN if < 2 evaluated windows
    min_max_drawdown: float  # NaN if no evaluated windows
    max_max_drawdown: float  # NaN if no evaluated windows

    # ── Trade count ───────────────────────────────────────────────────────────
    mean_trade_count: float

    # ── Overlap flag ─────────────────────────────────────────────────────────
    test_overlap: bool

    # ── Governance advisory counts (Phase-1B thresholds) ─────────────────────
    # Advisory only — never used for automated strategy selection.
    n_windows_below_return_floor: int  # folds with return < _RETURN_FLOOR (-10%)
    n_windows_above_drawdown_ceil: int  # folds with drawdown > _DRAWDOWN_CEIL (30%)
    n_windows_below_sharpe_floor: int  # folds with sharpe <= _SHARPE_FLOOR (0.0)


@dataclass(frozen=True)
class WalkForwardReport:
    """Immutable deterministic report for a complete walk-forward run.

    ``leakage_validated`` is True when all windows pass the temporal
    leakage checks.  ``validation_issues`` lists any issues found.
    ``report_hash`` is a SHA-256 of the report content (excluding itself).
    """

    report_version: str
    generation_timestamp_utc: str
    dataset_path: str
    total_bars: int
    train_bars: int
    test_bars: int
    step_bars: int
    n_windows: int
    windows: tuple[WalkForwardWindow, ...]
    results: tuple[WalkForwardResult, ...]
    summary: WalkForwardSummary
    leakage_validated: bool
    validation_issues: tuple[str, ...]
    report_hash: str


# ── Window generation ─────────────────────────────────────────────────────────


def generate_windows(
    total_bars: int,
    train_bars: int,
    test_bars: int,
    step_bars: int,
) -> tuple[WalkForwardWindow, ...]:
    """Generate deterministic walk-forward windows.

    Args:
        total_bars: Total number of bars in the dataset.
        train_bars: Number of bars in each training window.
        test_bars: Number of bars in each test window.
        step_bars: Number of bars to advance each window.

    Returns:
        Tuple of ``WalkForwardWindow`` objects in ascending order.

    Raises:
        ValueError: If parameters are invalid (non-positive values, or
            ``train_bars + test_bars > total_bars``).
    """
    if train_bars <= 0:
        raise ValueError(f"train_bars must be positive, got {train_bars}")
    if test_bars <= 0:
        raise ValueError(f"test_bars must be positive, got {test_bars}")
    if step_bars <= 0:
        raise ValueError(f"step_bars must be positive, got {step_bars}")
    if total_bars <= 0:
        raise ValueError(f"total_bars must be positive, got {total_bars}")
    if train_bars + test_bars > total_bars:
        raise ValueError(
            f"train_bars ({train_bars}) + test_bars ({test_bars}) = "
            f"{train_bars + test_bars} exceeds total_bars ({total_bars})"
        )

    windows: list[WalkForwardWindow] = []
    train_start = 0
    window_index = 0

    while True:
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars
        if test_end > total_bars:
            break
        windows.append(
            WalkForwardWindow(
                window_index=window_index,
                train_start_bar=train_start,
                train_end_bar=train_end,
                test_start_bar=test_start,
                test_end_bar=test_end,
                train_bars=train_bars,
                test_bars=test_bars,
            )
        )
        train_start += step_bars
        window_index += 1

    return tuple(windows)


def validate_windows(windows: tuple[WalkForwardWindow, ...]) -> tuple[bool, list[str]]:
    """Validate temporal consistency and leakage safety of walk-forward windows.

    Checks:
    1. Windows are in ascending order by ``train_start_bar``.
    2. Within each window: ``train_end_bar == test_start_bar`` (no gap, no overlap).
    3. Train period must strictly precede test period.
    4. No future data access: test window must not exceed prior test_end_bar.
    5. Reports (but does not reject) test period overlap across windows.

    Returns:
        ``(is_valid, issues)`` — issues is empty when valid.
    """
    issues: list[str] = []

    if not windows:
        return True, []

    for i, w in enumerate(windows):
        if w.window_index != i:
            issues.append(f"Window {i} has incorrect index {w.window_index} (expected {i})")
        if w.train_end_bar != w.test_start_bar:
            issues.append(
                f"Window {i}: train_end_bar ({w.train_end_bar}) != "
                f"test_start_bar ({w.test_start_bar}) — gap or overlap between train and test"
            )
        if w.train_start_bar >= w.train_end_bar:
            issues.append(
                f"Window {i}: train_start_bar ({w.train_start_bar}) >= "
                f"train_end_bar ({w.train_end_bar}) — empty training period"
            )
        if w.test_start_bar >= w.test_end_bar:
            issues.append(
                f"Window {i}: test_start_bar ({w.test_start_bar}) >= "
                f"test_end_bar ({w.test_end_bar}) — empty test period"
            )
        if w.train_end_bar > w.test_end_bar:
            issues.append(
                f"Window {i}: train overlaps test "
                f"(train_end={w.train_end_bar} > test_end={w.test_end_bar})"
            )

    for i in range(1, len(windows)):
        prev = windows[i - 1]
        curr = windows[i]
        if curr.train_start_bar <= prev.train_start_bar:
            issues.append(
                f"Window {i}: train_start_bar ({curr.train_start_bar}) is not "
                f"after previous ({prev.train_start_bar}) — chronological order violated"
            )
        # Leakage check: each window's TEST start must be strictly after the
        # previous window's TEST start (advancing evaluation frontier).
        if curr.test_start_bar <= prev.test_start_bar:
            issues.append(
                f"Window {i}: test_start_bar ({curr.test_start_bar}) <= "
                f"previous test_start_bar ({prev.test_start_bar}) — test frontier not advancing"
            )

    return len(issues) == 0, issues


# ── Walk-forward orchestration ────────────────────────────────────────────────

SignalFn = Callable[[pd.Series], pd.Series]


def _default_signal_fn(prices: pd.Series) -> pd.Series:
    """Combined momentum-trend signal with AQCS default parameters."""
    result: pd.Series = combined_momentum_trend_signal(prices, 20, 10, 50)
    return result


def run_walkforward(
    ohlcv: pd.DataFrame,
    config: BacktestConfig,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    *,
    dataset_path: str = "",
    signal_fn: SignalFn | None = None,
    now_utc: datetime | None = None,
) -> WalkForwardReport:
    """Execute a deterministic walk-forward validation on an OHLCV dataset.

    For each window, the signal is computed on ``ohlcv[:test_end_bar]``
    (no future data is visible) and the backtest evaluates only the test
    period ``[test_start_bar, test_end_bar)``.

    Args:
        ohlcv: Validated OHLCV DataFrame with UTC timestamps and "timestamp"
               column.  Must be sorted by timestamp ascending.
        config: Base ``BacktestConfig``.  ``start_date`` and ``end_date`` are
                overridden per window to isolate the test period.
        train_bars: Number of training bars per window.
        test_bars: Number of evaluation (test) bars per window.
        step_bars: Bar stride between consecutive windows.
        dataset_path: Informational path recorded in the report.
        signal_fn: Signal generator ``(prices: pd.Series) -> pd.Series``.
                   Defaults to ``combined_momentum_trend_signal`` with
                   window parameters (20, 10, 50).
        now_utc: Reference UTC time for ``generation_timestamp_utc``.
                 Defaults to ``datetime.now(UTC)``.

    Returns:
        Immutable ``WalkForwardReport`` with results for all windows.

    Raises:
        ValueError: If window parameters are invalid or the dataset is empty.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)
    _signal = signal_fn if signal_fn is not None else _default_signal_fn

    total_bars = len(ohlcv)
    if total_bars == 0:
        raise ValueError("OHLCV dataset is empty")

    ohlcv_sorted = ohlcv.sort_values("timestamp").reset_index(drop=True)

    windows = generate_windows(total_bars, train_bars, test_bars, step_bars)
    leakage_valid, validation_issues = validate_windows(windows)

    results: list[WalkForwardResult] = []
    for w in windows:
        result = _run_window(ohlcv_sorted, w, config, _signal)
        results.append(result)

    summary = _compute_summary(tuple(results), step_bars, test_bars)
    report_dict = _build_report_dict(
        _now,
        dataset_path,
        total_bars,
        train_bars,
        test_bars,
        step_bars,
        windows,
        tuple(results),
        summary,
        leakage_valid,
        tuple(validation_issues),
    )
    report_hash = _compute_report_hash(report_dict)

    return WalkForwardReport(
        report_version=REPORT_VERSION,
        generation_timestamp_utc=_now.isoformat(),
        dataset_path=dataset_path,
        total_bars=total_bars,
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
        n_windows=len(windows),
        windows=windows,
        results=tuple(results),
        summary=summary,
        leakage_validated=leakage_valid,
        validation_issues=tuple(validation_issues),
        report_hash=report_hash,
    )


def validate_report(report: WalkForwardReport) -> tuple[bool, list[str]]:
    """Validate a walk-forward report's hash and temporal consistency.

    Returns:
        ``(is_valid, errors)`` — errors is empty when valid.
    """
    errors: list[str] = []

    d = report_to_dict(report)
    d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
    expected = _compute_report_hash(d_no_hash)
    if expected != report.report_hash:
        errors.append(
            f"report_hash mismatch: stored={report.report_hash[:16]}… "
            f"recomputed={expected[:16]}…"
        )

    if report.report_version != REPORT_VERSION:
        errors.append(f"report_version '{report.report_version}' != current '{REPORT_VERSION}'")

    window_valid, window_issues = validate_windows(report.windows)
    if not window_valid:
        errors.extend(window_issues)

    if len(report.windows) != report.n_windows:
        errors.append(f"n_windows ({report.n_windows}) != len(windows) ({len(report.windows)})")

    return len(errors) == 0, errors


# ── Serialization ─────────────────────────────────────────────────────────────


def report_to_dict(report: WalkForwardReport) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``WalkForwardReport``."""

    def _f(v: float) -> float | None:
        return None if math.isnan(v) else v

    return {
        "report_version": report.report_version,
        "generation_timestamp_utc": report.generation_timestamp_utc,
        "dataset_path": report.dataset_path,
        "total_bars": report.total_bars,
        "train_bars": report.train_bars,
        "test_bars": report.test_bars,
        "step_bars": report.step_bars,
        "n_windows": report.n_windows,
        "leakage_validated": report.leakage_validated,
        "validation_issues": list(report.validation_issues),
        "report_hash": report.report_hash,
        "summary": {
            "n_windows_total": report.summary.n_windows_total,
            "n_windows_evaluated": report.summary.n_windows_evaluated,
            "n_windows_failed": report.summary.n_windows_failed,
            "n_windows_profitable": report.summary.n_windows_profitable,
            "mean_total_return": _f(report.summary.mean_total_return),
            "std_total_return": _f(report.summary.std_total_return),
            "min_total_return": _f(report.summary.min_total_return),
            "max_total_return": _f(report.summary.max_total_return),
            "range_total_return": _f(report.summary.range_total_return),
            "cv_total_return": _f(report.summary.cv_total_return),
            "mean_sharpe_ratio": _f(report.summary.mean_sharpe_ratio),
            "std_sharpe_ratio": _f(report.summary.std_sharpe_ratio),
            "min_sharpe_ratio": _f(report.summary.min_sharpe_ratio),
            "max_sharpe_ratio": _f(report.summary.max_sharpe_ratio),
            "mean_max_drawdown": _f(report.summary.mean_max_drawdown),
            "std_max_drawdown": _f(report.summary.std_max_drawdown),
            "min_max_drawdown": _f(report.summary.min_max_drawdown),
            "max_max_drawdown": _f(report.summary.max_max_drawdown),
            "mean_trade_count": _f(report.summary.mean_trade_count),
            "test_overlap": report.summary.test_overlap,
            "n_windows_below_return_floor": report.summary.n_windows_below_return_floor,
            "n_windows_above_drawdown_ceil": report.summary.n_windows_above_drawdown_ceil,
            "n_windows_below_sharpe_floor": report.summary.n_windows_below_sharpe_floor,
        },
        "windows": [
            {
                "window_index": w.window_index,
                "train_start_bar": w.train_start_bar,
                "train_end_bar": w.train_end_bar,
                "test_start_bar": w.test_start_bar,
                "test_end_bar": w.test_end_bar,
                "train_bars": w.train_bars,
                "test_bars": w.test_bars,
            }
            for w in report.windows
        ],
        "results": [
            {
                "window_index": r.window_index,
                "train_start_bar": r.train_start_bar,
                "train_end_bar": r.train_end_bar,
                "test_start_bar": r.test_start_bar,
                "test_end_bar": r.test_end_bar,
                "n_trades": r.n_trades,
                "n_bars_evaluated": r.n_bars_evaluated,
                "failed": r.failed,
                "failure_reason": r.failure_reason,
                "metrics": {k: _f(v) for k, v in r.metrics.items()},
            }
            for r in report.results
        ],
    }


def report_from_dict(d: dict[str, Any]) -> WalkForwardReport:
    """Reconstruct a ``WalkForwardReport`` from a dict.

    Raises:
        KeyError: If any required field is missing.
    """

    def _fn(v: Any) -> float:
        return float("nan") if v is None else float(v)

    s = d["summary"]
    summary = WalkForwardSummary(
        # Required fields — present in v1 and v2
        n_windows_total=int(s["n_windows_total"]),
        n_windows_evaluated=int(s["n_windows_evaluated"]),
        n_windows_failed=int(s["n_windows_failed"]),
        n_windows_profitable=int(s["n_windows_profitable"]),
        mean_total_return=_fn(s["mean_total_return"]),
        std_total_return=_fn(s["std_total_return"]),
        min_total_return=_fn(s["min_total_return"]),
        max_total_return=_fn(s["max_total_return"]),
        mean_sharpe_ratio=_fn(s["mean_sharpe_ratio"]),
        mean_max_drawdown=_fn(s["mean_max_drawdown"]),
        mean_trade_count=_fn(s["mean_trade_count"]),
        test_overlap=bool(s["test_overlap"]),
        # v2 fields — NaN/0 when loading a v1 report
        range_total_return=_fn(s.get("range_total_return")),
        cv_total_return=_fn(s.get("cv_total_return")),
        std_sharpe_ratio=_fn(s.get("std_sharpe_ratio")),
        min_sharpe_ratio=_fn(s.get("min_sharpe_ratio")),
        max_sharpe_ratio=_fn(s.get("max_sharpe_ratio")),
        std_max_drawdown=_fn(s.get("std_max_drawdown")),
        min_max_drawdown=_fn(s.get("min_max_drawdown")),
        max_max_drawdown=_fn(s.get("max_max_drawdown")),
        n_windows_below_return_floor=int(s.get("n_windows_below_return_floor", 0)),
        n_windows_above_drawdown_ceil=int(s.get("n_windows_above_drawdown_ceil", 0)),
        n_windows_below_sharpe_floor=int(s.get("n_windows_below_sharpe_floor", 0)),
    )

    windows = tuple(
        WalkForwardWindow(
            window_index=int(w["window_index"]),
            train_start_bar=int(w["train_start_bar"]),
            train_end_bar=int(w["train_end_bar"]),
            test_start_bar=int(w["test_start_bar"]),
            test_end_bar=int(w["test_end_bar"]),
            train_bars=int(w["train_bars"]),
            test_bars=int(w["test_bars"]),
        )
        for w in d["windows"]
    )

    results = tuple(
        WalkForwardResult(
            window_index=int(r["window_index"]),
            train_start_bar=int(r["train_start_bar"]),
            train_end_bar=int(r["train_end_bar"]),
            test_start_bar=int(r["test_start_bar"]),
            test_end_bar=int(r["test_end_bar"]),
            metrics={k: _fn(v) for k, v in r["metrics"].items()},
            n_trades=int(r["n_trades"]),
            n_bars_evaluated=int(r["n_bars_evaluated"]),
            failed=bool(r["failed"]),
            failure_reason=str(r["failure_reason"]),
        )
        for r in d["results"]
    )

    return WalkForwardReport(
        report_version=str(d["report_version"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        dataset_path=str(d["dataset_path"]),
        total_bars=int(d["total_bars"]),
        train_bars=int(d["train_bars"]),
        test_bars=int(d["test_bars"]),
        step_bars=int(d["step_bars"]),
        n_windows=int(d["n_windows"]),
        windows=windows,
        results=results,
        summary=summary,
        leakage_validated=bool(d["leakage_validated"]),
        validation_issues=tuple(str(i) for i in d["validation_issues"]),
        report_hash=str(d["report_hash"]),
    )


def save_report(report: WalkForwardReport, path: Path) -> None:
    """Write a walk-forward report to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_report(path: Path) -> WalkForwardReport:
    """Load a walk-forward report from a JSON file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in walk-forward report '{path}': {exc}") from exc
    return report_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _run_window(
    ohlcv: pd.DataFrame,
    window: WalkForwardWindow,
    config: BacktestConfig,
    signal_fn: SignalFn,
) -> WalkForwardResult:
    """Run a single walk-forward window and return its result."""
    nan = float("nan")
    empty_metrics = {
        "total_return": nan,
        "cagr": nan,
        "max_drawdown": nan,
        "sharpe_ratio": nan,
        "annualised_volatility": nan,
        "trade_count": nan,
        "win_rate": nan,
        "exposure": nan,
    }

    # Slice to test_end_bar — no future data leaks past this point
    ohlcv_window = ohlcv.iloc[: window.test_end_bar].copy()

    # Generate signal on all available data up to test_end_bar
    prices = pd.Series(
        ohlcv_window.set_index("timestamp")["close"],
        name="close",
    )
    try:
        signals: pd.Series = signal_fn(prices)
    except Exception as exc:
        return WalkForwardResult(
            window_index=window.window_index,
            train_start_bar=window.train_start_bar,
            train_end_bar=window.train_end_bar,
            test_start_bar=window.test_start_bar,
            test_end_bar=window.test_end_bar,
            metrics=empty_metrics,
            n_trades=0,
            n_bars_evaluated=0,
            failed=True,
            failure_reason=f"Signal generation failed: {exc}",
        )

    # Determine test period date range from timestamps
    test_start_ts = ohlcv_window.iloc[window.test_start_bar]["timestamp"]
    test_end_ts = ohlcv_window.iloc[window.test_end_bar - 1]["timestamp"]
    start_date = pd.Timestamp(test_start_ts).strftime("%Y-%m-%d")
    end_date = pd.Timestamp(test_end_ts).strftime("%Y-%m-%d")

    # Build window-specific config (frozen model → model_copy)
    window_config = config.model_copy(update={"start_date": start_date, "end_date": end_date})

    try:
        result: BacktestResult = run_backtest(ohlcv_window, signals, window_config)
    except Exception as exc:
        return WalkForwardResult(
            window_index=window.window_index,
            train_start_bar=window.train_start_bar,
            train_end_bar=window.train_end_bar,
            test_start_bar=window.test_start_bar,
            test_end_bar=window.test_end_bar,
            metrics=empty_metrics,
            n_trades=0,
            n_bars_evaluated=0,
            failed=True,
            failure_reason=f"Backtest failed: {exc}",
        )

    return WalkForwardResult(
        window_index=window.window_index,
        train_start_bar=window.train_start_bar,
        train_end_bar=window.train_end_bar,
        test_start_bar=window.test_start_bar,
        test_end_bar=window.test_end_bar,
        metrics=dict(result.metrics),
        n_trades=len(result.trades),
        n_bars_evaluated=result.n_bars,
        failed=False,
        failure_reason="",
    )


def _compute_summary(
    results: tuple[WalkForwardResult, ...],
    step_bars: int,
    test_bars: int,
) -> WalkForwardSummary:
    """Compute aggregate statistics across all walk-forward windows."""
    nan = float("nan")
    n_total = len(results)
    succeeded = [r for r in results if not r.failed]
    n_evaluated = len(succeeded)
    n_failed = n_total - n_evaluated

    returns = [r.metrics.get("total_return", nan) for r in succeeded]
    returns = [v for v in returns if not math.isnan(v)]
    sharpes = [r.metrics.get("sharpe_ratio", nan) for r in succeeded]
    sharpes = [v for v in sharpes if not math.isnan(v)]
    drawdowns = [r.metrics.get("max_drawdown", nan) for r in succeeded]
    drawdowns = [v for v in drawdowns if not math.isnan(v)]
    trade_counts = [float(r.n_trades) for r in succeeded]

    n_profitable = sum(1 for v in returns if v > 0)

    def _mean(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else nan

    def _std(lst: list[float]) -> float:
        if len(lst) < 2:
            return nan
        mean = _mean(lst)
        var = sum((v - mean) ** 2 for v in lst) / (len(lst) - 1)
        return math.sqrt(var)

    def _range(lst: list[float]) -> float:
        return max(lst) - min(lst) if len(lst) >= 2 else nan

    def _cv(lst: list[float]) -> float:
        if len(lst) < 2:
            return nan
        s = _std(lst)
        m = _mean(lst)
        if math.isnan(s) or abs(m) < _CV_MEAN_EPS:
            return nan
        return s / abs(m)

    # Governance advisory counts — advisory only, never used for auto-selection
    n_below_return_floor = sum(1 for v in returns if v < _RETURN_FLOOR)
    n_above_drawdown_ceil = sum(1 for v in drawdowns if v > _DRAWDOWN_CEIL)
    n_below_sharpe_floor = sum(1 for v in sharpes if v <= _SHARPE_FLOOR)

    return WalkForwardSummary(
        n_windows_total=n_total,
        n_windows_evaluated=n_evaluated,
        n_windows_failed=n_failed,
        n_windows_profitable=n_profitable,
        mean_total_return=_mean(returns),
        std_total_return=_std(returns),
        min_total_return=min(returns) if returns else nan,
        max_total_return=max(returns) if returns else nan,
        range_total_return=_range(returns),
        cv_total_return=_cv(returns),
        mean_sharpe_ratio=_mean(sharpes),
        std_sharpe_ratio=_std(sharpes),
        min_sharpe_ratio=min(sharpes) if sharpes else nan,
        max_sharpe_ratio=max(sharpes) if sharpes else nan,
        mean_max_drawdown=_mean(drawdowns),
        std_max_drawdown=_std(drawdowns),
        min_max_drawdown=min(drawdowns) if drawdowns else nan,
        max_max_drawdown=max(drawdowns) if drawdowns else nan,
        mean_trade_count=_mean(trade_counts),
        test_overlap=step_bars < test_bars,
        n_windows_below_return_floor=n_below_return_floor,
        n_windows_above_drawdown_ceil=n_above_drawdown_ceil,
        n_windows_below_sharpe_floor=n_below_sharpe_floor,
    )


def _build_report_dict(
    now_utc: datetime,
    dataset_path: str,
    total_bars: int,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    windows: tuple[WalkForwardWindow, ...],
    results: tuple[WalkForwardResult, ...],
    summary: WalkForwardSummary,
    leakage_validated: bool,
    validation_issues: tuple[str, ...],
) -> dict[str, Any]:
    """Build the report dict (without report_hash) for hashing."""
    report = WalkForwardReport(
        report_version=REPORT_VERSION,
        generation_timestamp_utc=now_utc.isoformat(),
        dataset_path=dataset_path,
        total_bars=total_bars,
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
        n_windows=len(windows),
        windows=windows,
        results=results,
        summary=summary,
        leakage_validated=leakage_validated,
        validation_issues=validation_issues,
        report_hash="",  # placeholder
    )
    d = report_to_dict(report)
    del d["report_hash"]
    return d


def _compute_report_hash(d: dict[str, Any]) -> str:
    """SHA-256 of the report dict (``report_hash`` key must be absent)."""
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()
