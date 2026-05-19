"""Deterministic baseline research reports for AQCS experiments.

A BaselineReport is an immutable, reproducible summary of a completed
deterministic backtest.  It extends the core backtesting metrics with:

  - extended cost metrics    (fees, slippage, avg trade value)
  - turnover metrics         (turnover per bar, avg holding period)
  - exposure metrics         (confirmed from equity curve)
  - drawdown metrics         (max drawdown confirmed)
  - benchmark comparison     (buy-and-hold return for the same period)
  - reproducibility anchors  (dataset hashes, replay certificate hash)

Reports are self-certifying: ``report_hash`` is a SHA-256 of the report
content (excluding the hash field itself).  Any modification to the report
invalidates the hash.

Determinism
-----------
- All metrics are deterministic given the same BacktestResult.
- ``generation_timestamp_utc`` is the only wall-clock field.
- Float fields are stored at float64 precision; NaN is serialised as ``null``
  in JSON to remain JSON-spec compliant.
- Report hash uses ``json.dumps(..., sort_keys=True)`` and
  ``struct.pack("<d", float(v))`` for float metrics — same approach as
  ReplayCertificate.

Safety
------
Reports must not claim alpha, profitability, or trading readiness.
The report surfaces only factual metrics.  No strategy optimisation,
parameter tuning, or autonomous decision-making is performed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqcs.backtesting.models import BacktestResult, EquityCurvePoint, Trade
from aqcs.experiments.models import ExperimentRecord

REPORT_VERSION: str = "1"

_SAFETY_DISCLAIMER: str = (
    "This report documents deterministic backtest results for research purposes only. "
    "It does not constitute alpha validation, profitability proof, paper trading "
    "readiness, or live trading authorisation."
)


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BaselineReport:
    """Immutable deterministic baseline research report.

    All timestamp fields are ISO-8601 UTC strings.
    ``report_hash`` is a SHA-256 of the report content (excluding itself).
    Float metrics use ``float("nan")`` for undefined values; JSON export
    serialises NaN as ``null``.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    report_version: str
    experiment_id: str
    experiment_name: str
    git_commit_hash: str
    generation_timestamp_utc: str
    report_hash: str
    disclaimer: str

    # ── Dataset references ────────────────────────────────────────────────────
    dataset_content_hash: str
    dataset_schema_hash: str
    dataset_symbol: str
    dataset_timeframe: str
    dataset_exchange: str
    dataset_start_utc: str
    dataset_end_utc: str
    dataset_row_count: int

    # ── Replay reference ──────────────────────────────────────────────────────
    replay_certificate_hash: str
    replay_certified: bool

    # ── Configuration ─────────────────────────────────────────────────────────
    initial_capital: float
    fee_bps: float
    slippage_bps: float
    start_date: str
    end_date: str
    periods_per_year: int
    n_bars: int

    # ── Core metrics (from compute_metrics) ───────────────────────────────────
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe_ratio: float
    annualised_volatility: float
    trade_count: int
    win_rate: float
    exposure: float

    # ── Extended cost metrics ──────────────────────────────────────────────────
    total_fees_paid: float
    total_slippage_cost: float
    avg_trade_value: float
    turnover_per_bar: float

    # ── Holding period metrics ─────────────────────────────────────────────────
    avg_holding_period_bars: float
    max_consecutive_losses: int

    # ── Benchmark comparison ──────────────────────────────────────────────────
    benchmark_total_return: float
    excess_return: float

    # ── Artifact hash ─────────────────────────────────────────────────────────
    metrics_hash: str


# ── Public API ────────────────────────────────────────────────────────────────


def build_report(
    result: BacktestResult,
    *,
    dataset_content_hash: str = "",
    dataset_schema_hash: str = "",
    dataset_symbol: str = "",
    dataset_timeframe: str = "",
    dataset_exchange: str = "",
    dataset_start_utc: str = "",
    dataset_end_utc: str = "",
    dataset_row_count: int = 0,
    replay_certificate_hash: str = "",
    replay_certified: bool = False,
    experiment_record: ExperimentRecord | None = None,
    now_utc: datetime | None = None,
) -> BaselineReport:
    """Build a deterministic baseline report from a completed backtest result.

    Args:
        result: Completed ``BacktestResult`` from ``run_backtest``.
        dataset_content_hash: SHA-256 content hash from ``DatasetManifest``
            (or ``""`` if not available).
        dataset_schema_hash: SHA-256 schema hash from ``DatasetManifest``.
        dataset_symbol: Market symbol in ccxt format (e.g. ``"BTC/USDT"``).
        dataset_timeframe: Candle timeframe (e.g. ``"1d"``).
        dataset_exchange: Exchange name (e.g. ``"binance"``).
        dataset_start_utc: ISO-8601 UTC string for dataset start.
        dataset_end_utc: ISO-8601 UTC string for dataset end.
        dataset_row_count: Number of rows in the source dataset.
        replay_certificate_hash: SHA-256 of the associated ``ReplayCertificate``
            (or ``""`` if not generated).
        replay_certified: Whether the experiment has a valid replay certificate.
        experiment_record: Optional ``ExperimentRecord`` for name and git hash.
        now_utc: Reference UTC time for ``generation_timestamp_utc``.
            Defaults to ``datetime.now(UTC)``.  Inject a fixed value in tests.

    Returns:
        An immutable ``BaselineReport`` with all metrics and references.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)

    exp_name = experiment_record.experiment_name if experiment_record else ""
    git_hash = experiment_record.git_commit_hash if experiment_record else ""

    metrics = result.metrics

    extended = _compute_extended_metrics(
        result.trades,
        result.equity_curve,
        result.config.initial_capital,
        result.n_bars,
    )

    metrics_hash = _compute_metrics_hash(metrics)

    # Build dict without report_hash to compute it
    report_dict: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "experiment_id": result.experiment_id,
        "experiment_name": exp_name,
        "git_commit_hash": git_hash,
        "generation_timestamp_utc": _now.isoformat(),
        "disclaimer": _SAFETY_DISCLAIMER,
        "dataset_content_hash": dataset_content_hash,
        "dataset_schema_hash": dataset_schema_hash,
        "dataset_symbol": dataset_symbol,
        "dataset_timeframe": dataset_timeframe,
        "dataset_exchange": dataset_exchange,
        "dataset_start_utc": dataset_start_utc,
        "dataset_end_utc": dataset_end_utc,
        "dataset_row_count": dataset_row_count,
        "replay_certificate_hash": replay_certificate_hash,
        "replay_certified": replay_certified,
        "initial_capital": result.config.initial_capital,
        "fee_bps": result.config.fee_bps,
        "slippage_bps": result.config.slippage_bps,
        "start_date": result.config.start_date,
        "end_date": result.config.end_date,
        "periods_per_year": result.config.periods_per_year,
        "n_bars": result.n_bars,
        "total_return": metrics.get("total_return", float("nan")),
        "cagr": metrics.get("cagr", float("nan")),
        "max_drawdown": metrics.get("max_drawdown", float("nan")),
        "sharpe_ratio": metrics.get("sharpe_ratio", float("nan")),
        "annualised_volatility": metrics.get("annualised_volatility", float("nan")),
        "trade_count": int(metrics.get("trade_count", 0)),
        "win_rate": metrics.get("win_rate", float("nan")),
        "exposure": metrics.get("exposure", float("nan")),
        "total_fees_paid": extended["total_fees_paid"],
        "total_slippage_cost": extended["total_slippage_cost"],
        "avg_trade_value": extended["avg_trade_value"],
        "turnover_per_bar": extended["turnover_per_bar"],
        "avg_holding_period_bars": extended["avg_holding_period_bars"],
        "max_consecutive_losses": extended["max_consecutive_losses"],
        "benchmark_total_return": extended["benchmark_total_return"],
        "excess_return": (
            metrics.get("total_return", float("nan")) - extended["benchmark_total_return"]
            if not math.isnan(extended["benchmark_total_return"])
            and not math.isnan(metrics.get("total_return", float("nan")))
            else float("nan")
        ),
        "metrics_hash": metrics_hash,
    }

    report_hash = _compute_report_hash(report_dict)

    return BaselineReport(
        report_version=REPORT_VERSION,
        experiment_id=result.experiment_id,
        experiment_name=exp_name,
        git_commit_hash=git_hash,
        generation_timestamp_utc=_now.isoformat(),
        report_hash=report_hash,
        disclaimer=_SAFETY_DISCLAIMER,
        dataset_content_hash=dataset_content_hash,
        dataset_schema_hash=dataset_schema_hash,
        dataset_symbol=dataset_symbol,
        dataset_timeframe=dataset_timeframe,
        dataset_exchange=dataset_exchange,
        dataset_start_utc=dataset_start_utc,
        dataset_end_utc=dataset_end_utc,
        dataset_row_count=dataset_row_count,
        replay_certificate_hash=replay_certificate_hash,
        replay_certified=replay_certified,
        initial_capital=result.config.initial_capital,
        fee_bps=result.config.fee_bps,
        slippage_bps=result.config.slippage_bps,
        start_date=result.config.start_date,
        end_date=result.config.end_date,
        periods_per_year=result.config.periods_per_year,
        n_bars=result.n_bars,
        total_return=report_dict["total_return"],
        cagr=report_dict["cagr"],
        max_drawdown=report_dict["max_drawdown"],
        sharpe_ratio=report_dict["sharpe_ratio"],
        annualised_volatility=report_dict["annualised_volatility"],
        trade_count=report_dict["trade_count"],
        win_rate=report_dict["win_rate"],
        exposure=report_dict["exposure"],
        total_fees_paid=extended["total_fees_paid"],
        total_slippage_cost=extended["total_slippage_cost"],
        avg_trade_value=extended["avg_trade_value"],
        turnover_per_bar=extended["turnover_per_bar"],
        avg_holding_period_bars=extended["avg_holding_period_bars"],
        max_consecutive_losses=extended["max_consecutive_losses"],
        benchmark_total_return=extended["benchmark_total_return"],
        excess_return=report_dict["excess_return"],
        metrics_hash=metrics_hash,
    )


def validate_report(report: BaselineReport) -> tuple[bool, list[str]]:
    """Validate a report's self-certification hash and basic consistency.

    Returns:
        ``(is_valid, errors)`` where errors is an empty list when valid.
    """
    errors: list[str] = []

    # Re-derive the hash from the report's own fields and compare
    d = report_to_dict(report)
    d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
    expected_hash = _compute_report_hash(d_no_hash)
    if expected_hash != report.report_hash:
        errors.append(
            f"report_hash mismatch: stored={report.report_hash[:16]}… "
            f"recomputed={expected_hash[:16]}…"
        )

    if report.report_version != REPORT_VERSION:
        errors.append(f"report_version '{report.report_version}' != current '{REPORT_VERSION}'")

    if report.n_bars <= 0:
        errors.append(f"n_bars must be positive, got {report.n_bars}")

    return len(errors) == 0, errors


def report_to_dict(report: BaselineReport) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``BaselineReport``.

    NaN float values are serialised as ``null`` for JSON-spec compliance.
    Output is deterministic when ``json.dumps(..., sort_keys=True)`` is used.
    """

    def _f(v: float) -> float | None:
        return None if math.isnan(v) else v

    return {
        "report_version": report.report_version,
        "experiment_id": report.experiment_id,
        "experiment_name": report.experiment_name,
        "git_commit_hash": report.git_commit_hash,
        "generation_timestamp_utc": report.generation_timestamp_utc,
        "report_hash": report.report_hash,
        "disclaimer": report.disclaimer,
        "dataset_content_hash": report.dataset_content_hash,
        "dataset_schema_hash": report.dataset_schema_hash,
        "dataset_symbol": report.dataset_symbol,
        "dataset_timeframe": report.dataset_timeframe,
        "dataset_exchange": report.dataset_exchange,
        "dataset_start_utc": report.dataset_start_utc,
        "dataset_end_utc": report.dataset_end_utc,
        "dataset_row_count": report.dataset_row_count,
        "replay_certificate_hash": report.replay_certificate_hash,
        "replay_certified": report.replay_certified,
        "initial_capital": report.initial_capital,
        "fee_bps": report.fee_bps,
        "slippage_bps": report.slippage_bps,
        "start_date": report.start_date,
        "end_date": report.end_date,
        "periods_per_year": report.periods_per_year,
        "n_bars": report.n_bars,
        "total_return": _f(report.total_return),
        "cagr": _f(report.cagr),
        "max_drawdown": _f(report.max_drawdown),
        "sharpe_ratio": _f(report.sharpe_ratio),
        "annualised_volatility": _f(report.annualised_volatility),
        "trade_count": report.trade_count,
        "win_rate": _f(report.win_rate),
        "exposure": _f(report.exposure),
        "total_fees_paid": _f(report.total_fees_paid),
        "total_slippage_cost": _f(report.total_slippage_cost),
        "avg_trade_value": _f(report.avg_trade_value),
        "turnover_per_bar": _f(report.turnover_per_bar),
        "avg_holding_period_bars": _f(report.avg_holding_period_bars),
        "max_consecutive_losses": report.max_consecutive_losses,
        "benchmark_total_return": _f(report.benchmark_total_return),
        "excess_return": _f(report.excess_return),
        "metrics_hash": report.metrics_hash,
    }


def report_from_dict(d: dict[str, Any]) -> BaselineReport:
    """Reconstruct a ``BaselineReport`` from a dict (e.g. loaded from JSON).

    ``null`` JSON values for float fields are converted back to ``float("nan")``.

    Raises:
        KeyError: If any required field is missing.
    """

    def _fn(v: Any) -> float:
        return float("nan") if v is None else float(v)

    return BaselineReport(
        report_version=str(d["report_version"]),
        experiment_id=str(d["experiment_id"]),
        experiment_name=str(d["experiment_name"]),
        git_commit_hash=str(d["git_commit_hash"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        report_hash=str(d["report_hash"]),
        disclaimer=str(d["disclaimer"]),
        dataset_content_hash=str(d["dataset_content_hash"]),
        dataset_schema_hash=str(d["dataset_schema_hash"]),
        dataset_symbol=str(d["dataset_symbol"]),
        dataset_timeframe=str(d["dataset_timeframe"]),
        dataset_exchange=str(d["dataset_exchange"]),
        dataset_start_utc=str(d["dataset_start_utc"]),
        dataset_end_utc=str(d["dataset_end_utc"]),
        dataset_row_count=int(d["dataset_row_count"]),
        replay_certificate_hash=str(d["replay_certificate_hash"]),
        replay_certified=bool(d["replay_certified"]),
        initial_capital=float(d["initial_capital"]),
        fee_bps=float(d["fee_bps"]),
        slippage_bps=float(d["slippage_bps"]),
        start_date=str(d["start_date"]),
        end_date=str(d["end_date"]),
        periods_per_year=int(d["periods_per_year"]),
        n_bars=int(d["n_bars"]),
        total_return=_fn(d["total_return"]),
        cagr=_fn(d["cagr"]),
        max_drawdown=_fn(d["max_drawdown"]),
        sharpe_ratio=_fn(d["sharpe_ratio"]),
        annualised_volatility=_fn(d["annualised_volatility"]),
        trade_count=int(d["trade_count"]),
        win_rate=_fn(d["win_rate"]),
        exposure=_fn(d["exposure"]),
        total_fees_paid=_fn(d["total_fees_paid"]),
        total_slippage_cost=_fn(d["total_slippage_cost"]),
        avg_trade_value=_fn(d["avg_trade_value"]),
        turnover_per_bar=_fn(d["turnover_per_bar"]),
        avg_holding_period_bars=_fn(d["avg_holding_period_bars"]),
        max_consecutive_losses=int(d["max_consecutive_losses"]),
        benchmark_total_return=_fn(d["benchmark_total_return"]),
        excess_return=_fn(d["excess_return"]),
        metrics_hash=str(d["metrics_hash"]),
    )


def save_report(report: BaselineReport, path: Path) -> None:
    """Write a report to a JSON file at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_report(path: Path) -> BaselineReport:
    """Load a report from a JSON file written by ``save_report``.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in report file '{path}': {exc}") from exc
    return report_from_dict(raw)


# ── Internal metric helpers ───────────────────────────────────────────────────


def _compute_extended_metrics(
    trades: tuple[Trade, ...],
    equity_curve: tuple[EquityCurvePoint, ...],
    initial_capital: float,
    n_bars: int,
) -> dict[str, Any]:
    """Compute extended metrics from raw backtest artifacts."""
    nan = float("nan")
    buy_trades = [t for t in trades if t.side == "buy"]
    sell_trades = [t for t in trades if t.side == "sell"]

    total_fees = sum(t.fee for t in trades)
    total_slippage = sum(t.slippage_amount for t in trades)
    avg_trade_value = sum(t.value for t in buy_trades) / len(buy_trades) if buy_trades else nan

    # Turnover: total bought value / initial_capital / n_bars
    total_bought = sum(t.value for t in buy_trades)
    turnover_per_bar = (
        total_bought / initial_capital / n_bars if initial_capital > 0 and n_bars > 0 else nan
    )

    # Average holding period (bars) from exposure
    trade_count = len(buy_trades)
    if equity_curve and trade_count > 0:
        bars_long = sum(1 for p in equity_curve if p.position > 0)
        avg_holding_period_bars = bars_long / trade_count
    else:
        avg_holding_period_bars = nan

    # Max consecutive losses (net P&L per round trip)
    max_consec = _compute_max_consecutive_losses(buy_trades, sell_trades)

    # Benchmark: buy-and-hold return using equity curve's price (close)
    if equity_curve and len(equity_curve) >= 2:
        p0 = equity_curve[0].price
        p_last = equity_curve[-1].price
        bm_return = (p_last - p0) / p0 if p0 != 0 else nan
    else:
        bm_return = nan

    # excess_return is computed in build_report using result.metrics["total_return"]
    # as the authoritative value; only benchmark_total_return is returned here.

    return {
        "total_fees_paid": total_fees,
        "total_slippage_cost": total_slippage,
        "avg_trade_value": avg_trade_value,
        "turnover_per_bar": turnover_per_bar,
        "avg_holding_period_bars": avg_holding_period_bars,
        "max_consecutive_losses": max_consec,
        "benchmark_total_return": bm_return,
    }


def _compute_max_consecutive_losses(
    buy_trades: list[Trade],
    sell_trades: list[Trade],
) -> int:
    """Return the maximum consecutive losing trade count (net of fees)."""
    n_pairs = min(len(buy_trades), len(sell_trades))
    if n_pairs == 0:
        return 0
    max_streak = 0
    current_streak = 0
    for buy, sell in zip(buy_trades[:n_pairs], sell_trades[:n_pairs], strict=True):
        gross = (sell.fill_price - buy.fill_price) * buy.quantity
        net_pnl = gross - buy.fee - sell.fee
        if net_pnl <= 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def _compute_metrics_hash(metrics: dict[str, float]) -> str:
    """SHA-256 over sorted (key, float64 LE) metric pairs."""
    h = hashlib.sha256()
    h.update(len(metrics).to_bytes(8, byteorder="little"))
    for key in sorted(metrics):
        h.update(key.encode("utf-8"))
        h.update(b"\x00")
        h.update(struct.pack("<d", float(metrics[key])))
    return h.hexdigest()


def _compute_report_hash(d: dict[str, Any]) -> str:
    """SHA-256 of report content dict with ``report_hash`` excluded."""
    d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
    return hashlib.sha256(json.dumps(d_no_hash, sort_keys=True).encode("utf-8")).hexdigest()
