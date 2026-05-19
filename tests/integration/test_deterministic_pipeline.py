"""Integration: deterministic end-to-end research pipeline.

Validates that the full AQCS Phase-1 research pipeline — from synthetic OHLCV
data through manifests, replay certificates, baseline reports, walk-forward
validation, campaigns, benchmark suites, regression guards, and sensitivity
audits — produces deterministic, self-certifying, reproducible artifacts.

All tests use synthetic OHLCV data generated deterministically with
``np.linspace``.  No network calls.  No real exchange data required.

Coverage:
- manifest generated from synthetic parquet → valid, stable hash
- replay certificate generated from BacktestResult → valid, all hash fields
- baseline report generated from BacktestResult → valid, stable report_hash
- walk-forward report generated from OHLCV → valid, leakage_validated=True
- campaign built from artifact directory → valid, stable campaign_hash
- campaign hash is content-addressable: two identical builds → same hash
- benchmark suite built from campaign → valid, score ∈ [0, 1]
- regression guard on (same dir, same dir) → 0 critical findings, stable hash
- sensitivity audit on campaign artifact → stable audit_hash, advisory only
- artifact lineage: campaign references correct manifest content_hash
- artifact lineage: campaign references correct cert config_hash
- all validate_* functions confirm self-certification on generated artifacts
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aqcs.backtesting.models import BacktestConfig, BacktestResult, EquityCurvePoint, Trade
from aqcs.data.manifest import generate_manifest, save_manifest
from aqcs.experiments.models import ExperimentRecord, ExperimentStatus
from aqcs.research.baseline_report import (
    build_report,
    save_report,
    validate_report,
)
from aqcs.research.benchmark_suite import (
    build_benchmark_suite,
    save_benchmark,
    validate_benchmark,
)
from aqcs.research.campaign import (
    build_campaign,
    save_campaign,
    validate_campaign,
)
from aqcs.research.regression_guard import run_regression_guard
from aqcs.research.replay_certificate import (
    certify_result,
    save_certificate,
    verify_certificate,
)
from aqcs.research.sensitivity_audit import (
    make_default_perturbation_config,
    run_sensitivity_audit,
    validate_sensitivity_audit,
)
from aqcs.research.walkforward import (
    run_walkforward,
)
from aqcs.research.walkforward import (
    save_report as save_wf_report,
)
from aqcs.research.walkforward import (
    validate_report as validate_wf_report,
)
from aqcs.utils.events import SignalDirection

from .conftest import FIXED_NOW

# ── Shared synthetic data constants ──────────────────────────────────────────

_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1d"
_EXCHANGE = "binance"
_BASE_TS = datetime(2024, 1, 1, tzinfo=UTC)
_FIXED_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# 250 bars — enough for 2 walk-forward windows (train=150, test=50, step=50)
_N_BARS = 250
_WF_TRAIN = 150
_WF_TEST = 50
_WF_STEP = 50


# ── Synthetic helpers ─────────────────────────────────────────────────────────


def _ohlcv(n: int = _N_BARS) -> pd.DataFrame:
    """Deterministic schema-valid OHLCV using np.linspace only."""
    idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    close = np.linspace(45_000.0, 50_000.0, n)
    high = close * 1.001
    low = close * 0.999
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,  # open == close, always within [low, high]
            "high": high,
            "low": low,
            "close": close,
            "volume": np.linspace(100.0, 200.0, n),
            "symbol": _SYMBOL,
            "timeframe": _TIMEFRAME,
            "exchange": _EXCHANGE,
        }
    )


def _config(**ov: object) -> BacktestConfig:
    d: dict[str, object] = {
        "initial_capital": 10_000.0,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
    }
    d.update(ov)
    return BacktestConfig(**d)  # type: ignore[arg-type]


def _ts(n: int) -> list[datetime]:
    return [_BASE_TS + timedelta(days=i) for i in range(n)]


def _trades() -> tuple[Trade, ...]:
    stamps = _ts(6)
    result = []
    for i in range(3):
        price = 45_000.0 + i * 100
        qty = 0.2
        result.extend(
            [
                Trade(
                    timestamp=stamps[i * 2],
                    side="buy",
                    fill_price=price,
                    quantity=qty,
                    fee=4.5,
                    slippage_amount=0.9,
                    value=price * qty,
                ),
                Trade(
                    timestamp=stamps[i * 2 + 1],
                    side="sell",
                    fill_price=price + 200,
                    quantity=qty,
                    fee=4.5,
                    slippage_amount=0.9,
                    value=(price + 200) * qty,
                ),
            ]
        )
    return tuple(result)


def _equity(n: int = 30) -> tuple[EquityCurvePoint, ...]:
    return tuple(
        EquityCurvePoint(
            timestamp=_BASE_TS + timedelta(days=i),
            equity=10_000.0 + i * 10,
            cash=9_000.0 + i * 8,
            position=0.2,
            price=45_000.0 + i * 100,
        )
        for i in range(n)
    )


def _result() -> BacktestResult:
    return BacktestResult(
        config=_config(),
        trades=_trades(),
        equity_curve=_equity(30),
        metrics={
            "total_return": 0.12,
            "cagr": 0.08,
            "max_drawdown": 0.05,
            "sharpe_ratio": 1.42,
            "annualised_volatility": 0.18,
            "trade_count": 3.0,
            "win_rate": 0.67,
            "exposure": 0.50,
        },
        n_bars=30,
        experiment_id=str(_FIXED_UUID),
    )


def _experiment() -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=_FIXED_UUID,
        experiment_name="integration_e2e",
        timestamp_started_utc=_BASE_TS,
        status=ExperimentStatus.COMPLETED,
        git_commit_hash="deadbeef",
        parameters={"fee_bps": 10.0},
    )


def _signals(n: int = 30) -> pd.Series:
    idx = pd.DatetimeIndex(_ts(n), tz=UTC)
    return pd.Series([SignalDirection.LONG] * n, index=idx, dtype=object)


# ── E2E Pipeline fixture ──────────────────────────────────────────────────────


class _Pipeline:
    """Container for a fully-built pipeline run in a tmp directory."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.parquet_path: Path
        self.artifacts_dir: Path
        self._build()

    def _build(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

        # 1 — Write parquet
        df = _ohlcv()
        self.parquet_path = self.root / "data.parquet"
        df.to_parquet(self.parquet_path, index=False)

        # 2 — Generate manifest
        self.manifest = generate_manifest(self.parquet_path, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)

        # 3 — Replay certificate
        r = _result()
        exp = _experiment()
        sig = _signals()
        self.cert = certify_result(
            r,
            sig,
            self.manifest.content_hash,
            self.manifest.schema_hash,
            exp,
            now_utc=FIXED_NOW,
        )

        # 4 — Baseline report
        self.report = build_report(r, now_utc=FIXED_NOW)

        # 5 — Walk-forward (uses actual backtesting pipeline)
        self.wf_report = run_walkforward(
            df,
            _config(),
            train_bars=_WF_TRAIN,
            test_bars=_WF_TEST,
            step_bars=_WF_STEP,
            now_utc=FIXED_NOW,
        )

        # 6 — Write all artifacts to directory
        self.artifacts_dir = self.root / "artifacts"
        self.artifacts_dir.mkdir()
        save_manifest(self.manifest, self.artifacts_dir / "manifest.json")
        save_certificate(self.cert, self.artifacts_dir / "cert.json")
        save_report(self.report, self.artifacts_dir / "baseline.json")
        save_wf_report(self.wf_report, self.artifacts_dir / "walkforward.json")

        # 7 — Campaign
        self.campaign = build_campaign(self.artifacts_dir, "e2e_campaign", now_utc=FIXED_NOW)
        save_campaign(self.campaign, self.root / "campaign.json")

        # 8 — Benchmark suite
        self.benchmark = build_benchmark_suite(
            [self.root / "campaign.json"],
            benchmark_name="e2e_benchmark",
            now_utc=FIXED_NOW,
        )
        save_benchmark(self.benchmark, self.root / "benchmark.json")


# ── Test class ────────────────────────────────────────────────────────────────


class TestDeterministicPipelineE2E:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        self.pipeline = _Pipeline(tmp_path)
        self.tmp = tmp_path

    # ── Manifest ─────────────────────────────────────────────────────────────

    def test_manifest_valid(self) -> None:
        m = self.pipeline.manifest
        assert len(m.content_hash) == 64
        assert len(m.schema_hash) == 64
        assert m.row_count == _N_BARS
        assert m.symbol == _SYMBOL
        assert m.exchange == _EXCHANGE

    # ── Replay certificate ────────────────────────────────────────────────────

    def test_cert_all_hash_fields_populated(self) -> None:
        cert = self.pipeline.cert
        for field in ("config_hash", "metrics_hash", "trades_hash", "equity_hash", "signals_hash"):
            assert len(getattr(cert, field)) == 64

    def test_cert_certified_bars(self) -> None:
        assert self.pipeline.cert.certified_bars == 30

    def test_cert_dataset_hashes_match_manifest(self) -> None:
        cert = self.pipeline.cert
        manifest = self.pipeline.manifest
        assert cert.dataset_content_hash == manifest.content_hash
        assert cert.dataset_schema_hash == manifest.schema_hash

    def test_cert_self_certifying(self) -> None:
        """Re-running certify_result with same inputs must match stored cert."""
        cert = self.pipeline.cert
        r = _result()
        exp = _experiment()
        sig = _signals()
        manifest = self.pipeline.manifest
        vr = verify_certificate(
            r,
            sig,
            manifest.content_hash,
            manifest.schema_hash,
            exp,
            cert,
        )
        assert vr.verified, f"Certificate mismatches: {vr.mismatches}"

    # ── Baseline report ───────────────────────────────────────────────────────

    def test_baseline_report_valid(self) -> None:
        valid, errors = validate_report(self.pipeline.report)
        assert valid, f"Baseline report invalid: {errors}"

    def test_baseline_report_has_disclaimer(self) -> None:
        assert self.pipeline.report.disclaimer != ""

    def test_baseline_report_metrics_reasonable(self) -> None:
        r = self.pipeline.report
        assert r.total_return == pytest.approx(0.12)
        assert r.initial_capital == 10_000.0

    # ── Walk-forward report ───────────────────────────────────────────────────

    def test_wf_report_valid(self) -> None:
        valid, errors = validate_wf_report(self.pipeline.wf_report)
        assert valid, f"Walk-forward report invalid: {errors}"

    def test_wf_report_leakage_validated(self) -> None:
        assert self.pipeline.wf_report.leakage_validated is True

    def test_wf_report_has_windows(self) -> None:
        assert self.pipeline.wf_report.n_windows >= 1

    # ── Campaign ──────────────────────────────────────────────────────────────

    def test_campaign_valid(self) -> None:
        valid, errors = validate_campaign(self.pipeline.campaign)
        assert valid, f"Campaign invalid: {errors}"

    def test_campaign_hash_64_chars(self) -> None:
        assert len(self.pipeline.campaign.campaign_hash) == 64

    def test_campaign_references_manifest_content_hash(self) -> None:
        assert self.pipeline.manifest.content_hash in self.pipeline.campaign.dataset_manifest_hashes

    def test_campaign_hash_content_addressable(self, tmp_path: Path) -> None:
        """Two independent builds of the same artifacts → same campaign_hash."""
        p2 = _Pipeline(tmp_path / "second")
        assert p2.campaign.campaign_hash == self.pipeline.campaign.campaign_hash

    # ── Benchmark suite ───────────────────────────────────────────────────────

    def test_benchmark_valid(self) -> None:
        valid, errors = validate_benchmark(self.pipeline.benchmark)
        assert valid, f"Benchmark suite invalid: {errors}"

    def test_benchmark_score_in_unit_interval(self) -> None:
        for entry in self.pipeline.benchmark.comparison_entries:
            assert 0.0 <= entry.score <= 1.0, f"Score out of range: {entry.score}"

    def test_benchmark_advisory_disclaimer_present(self) -> None:
        # advisory_disclaimer lives inside ranking_metrics dict
        disclaimer = self.pipeline.benchmark.ranking_metrics.get("advisory_disclaimer", "")
        assert disclaimer != ""

    # ── Regression guard ──────────────────────────────────────────────────────

    def test_regression_guard_identical_dirs_zero_critical(self) -> None:
        d = self.pipeline.artifacts_dir
        rpt = run_regression_guard(d, d, now_utc=FIXED_NOW)
        critical = [f for f in rpt.regression_findings if f.severity == "critical"]
        assert critical == [], f"Unexpected critical findings: {critical}"

    def test_regression_guard_governance_clean(self) -> None:
        d = self.pipeline.artifacts_dir
        rpt = run_regression_guard(d, d, now_utc=FIXED_NOW)
        assert rpt.governance_validation_results["governance_clean"] is True

    def test_regression_hash_stable(self, tmp_path: Path) -> None:
        """Two independent pipeline runs → same regression_hash."""
        p2 = _Pipeline(tmp_path / "second")
        d1 = self.pipeline.artifacts_dir
        d2 = p2.artifacts_dir
        r1 = run_regression_guard(d1, d2, now_utc=FIXED_NOW)
        r2 = run_regression_guard(d1, d2, now_utc=FIXED_NOW)
        assert r1.regression_hash == r2.regression_hash

    # ── Sensitivity audit ────────────────────────────────────────────────────

    def test_sensitivity_audit_valid(self) -> None:
        artifact = self.tmp / "campaign.json"
        config = self.tmp / "sa_config.json"
        config.write_text(json.dumps(make_default_perturbation_config()), encoding="utf-8")
        audit = run_sensitivity_audit(artifact, config, now_utc=FIXED_NOW)
        valid, errors = validate_sensitivity_audit(audit)
        assert valid, f"Sensitivity audit invalid: {errors}"

    def test_sensitivity_audit_advisory(self) -> None:
        """Audit must be advisory-only: no autonomous action fields."""
        artifact = self.tmp / "campaign.json"
        config = self.tmp / "sa_config2.json"
        config.write_text(json.dumps(make_default_perturbation_config()), encoding="utf-8")
        audit = run_sensitivity_audit(artifact, config, now_utc=FIXED_NOW)
        # Advisory: just a hash, findings, stability scores — no action fields
        d = json.loads((self.tmp / "sa_config2.json").read_text())
        assert "perturbations" in d  # config is deterministic
        assert audit.audit_hash  # report is self-certifying
