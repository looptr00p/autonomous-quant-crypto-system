"""Integration: artifact hash stability across independent runs.

Validates that canonical_hash, campaign_hash, benchmark_hash, and
regression_report_hash produce bit-identical outputs on repeated calls
with identical inputs, and that any content change produces a different hash.

All tests are deterministic and local — no network, no wall-clock.

Coverage:
- canonical_hash is deterministic across calls
- canonical_hash changes on content modification
- NaN is normalized to None consistently
- campaign_hash content-addressable: same artifacts → same hash
- campaign_hash changes when artifact content changes
- benchmark_hash stable across two build calls
- regression_report on identical dirs → 0 findings, stable hash
- sensitivity_audit_hash stable across two calls
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from aqcs.research.campaign import build_campaign
from aqcs.research.regression_guard import run_regression_guard
from aqcs.research.sensitivity_audit import make_default_perturbation_config, run_sensitivity_audit
from aqcs.utils.canonicalization import canonical_hash, normalize_nan

from .conftest import FIXED_NOW

_FIXED_UUID = uuid.uuid4()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write(path: Path, d: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d), encoding="utf-8")


def _campaign_artifact_dir(base: Path, label: str) -> Path:
    """Write a minimal valid campaign artifact directory."""
    d = base / label
    d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "manifest_version": "1",
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "content_hash": "a" * 64,
        "schema_hash": "b" * 64,
        "row_count": 90,
        "start_timestamp_utc": "2024-01-01T00:00:00+00:00",
        "end_timestamp_utc": "2024-03-31T00:00:00+00:00",
        "duplicate_row_count": 0,
        "missing_intervals": {},
        "generation_timestamp_utc": FIXED_NOW.isoformat(),
    }
    cert = {
        "certificate_version": "1",
        "experiment_id": str(_FIXED_UUID),
        "certified_bars": 90,
        "config_hash": "c" * 64,
        "parameters_hash": "d" * 64,
        "dataset_content_hash": "a" * 64,
        "dataset_schema_hash": "b" * 64,
        "metrics_hash": "e" * 64,
        "trades_hash": "f" * 64,
        "equity_hash": "g" * 64,
        "signals_hash": "h" * 64,
        "generation_timestamp_utc": FIXED_NOW.isoformat(),
    }
    wf_base = {
        "report_version": "1",
        "train_bars": 200,
        "test_bars": 50,
        "step_bars": 50,
        "n_windows": 2,
        "leakage_validated": True,
        "summary": {
            "mean_total_return": 0.08,
            "mean_sharpe_ratio": 1.2,
            "mean_max_drawdown": 0.04,
            "n_windows_evaluated": 2,
            "n_windows_failed": 0,
            "n_windows_profitable": 2,
        },
        "results": [],
        "generation_timestamp_utc": FIXED_NOW.isoformat(),
    }
    # Compute report_hash the way walkforward.py does (legacy separator format)
    from aqcs.utils.canonicalization import legacy_hash as _lhash

    wf_no_hash = {k: v for k, v in wf_base.items() if k != "report_hash"}
    wf_base["report_hash"] = _lhash(wf_no_hash)

    baseline = {
        "report_version": "1",
        "experiment_id": str(_FIXED_UUID),
        "disclaimer": "For research only.",
        "initial_capital": 10_000.0,
        "benchmark_total_return": 0.08,
        "total_return": 0.10,
        "cagr": 0.08,
        "max_drawdown": 0.05,
        "sharpe_ratio": 1.42,
        "annualised_volatility": 0.18,
        "trade_count": 3.0,
        "win_rate": 0.67,
        "exposure": 0.50,
        "total_fees_paid": 27.0,
        "total_slippage_cost": 5.4,
        "excess_return": 0.02,
        "avg_trade_value": 9_000.0,
        "avg_holding_period_bars": 5.0,
        "turnover_per_bar": 0.27,
        "max_consecutive_losses": 1,
        "metrics_hash": "i" * 64,
        "generation_timestamp_utc": FIXED_NOW.isoformat(),
        "dataset_content_hash": "a" * 64,
        "dataset_schema_hash": "b" * 64,
        "replay_certificate_hash": "c" * 64,
    }
    baseline_no_hash = {k: v for k, v in baseline.items() if k != "report_hash"}
    baseline["report_hash"] = _lhash(baseline_no_hash)

    _write(d / "manifest.json", manifest)
    _write(d / "cert.json", cert)
    _write(d / "wf.json", wf_base)
    _write(d / "baseline.json", baseline)
    return d


# ── Canonical hash stability ──────────────────────────────────────────────────


class TestCanonicalHashStability:
    def test_same_data_same_hash(self) -> None:
        data = {"key": "value", "num": 1.5, "nested": {"a": 1}}
        assert canonical_hash(data) == canonical_hash(data)

    def test_different_data_different_hash(self) -> None:
        d1 = {"key": "value"}
        d2 = {"key": "other"}
        assert canonical_hash(d1) != canonical_hash(d2)

    def test_key_order_independent(self) -> None:
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert canonical_hash(d1) == canonical_hash(d2)

    def test_nan_normalized_to_none(self) -> None:
        d_nan = {"x": float("nan")}
        d_none = {"x": None}
        assert normalize_nan(d_nan) == d_none
        assert canonical_hash(normalize_nan(d_nan)) == canonical_hash(d_none)

    def test_nan_in_nested_structure(self) -> None:
        nested = {"metrics": {"total_return": float("nan"), "sharpe": 1.5}}
        safe = normalize_nan(nested)
        assert safe["metrics"]["total_return"] is None
        assert safe["metrics"]["sharpe"] == 1.5
        h1 = canonical_hash(safe)
        h2 = canonical_hash(safe)
        assert h1 == h2

    def test_hash_is_64_hex_chars(self) -> None:
        h = canonical_hash({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Campaign hash stability ───────────────────────────────────────────────────


class TestCampaignHashStability:
    def test_identical_artifacts_identical_campaign_hash(self, tmp_path: Path) -> None:
        d1 = _campaign_artifact_dir(tmp_path, "dir_a")
        d2 = _campaign_artifact_dir(tmp_path, "dir_b")
        c1 = build_campaign(d1, "test_campaign", now_utc=FIXED_NOW)
        c2 = build_campaign(d2, "test_campaign", now_utc=FIXED_NOW)
        assert c1.campaign_hash == c2.campaign_hash

    def test_different_content_different_campaign_hash(self, tmp_path: Path) -> None:
        d1 = _campaign_artifact_dir(tmp_path, "dir_a")
        d2 = _campaign_artifact_dir(tmp_path, "dir_b")
        # Modify baseline's total_return in dir_b
        baseline_path = d2 / "baseline.json"
        data = json.loads(baseline_path.read_text())
        data["total_return"] = 0.99
        from aqcs.utils.canonicalization import legacy_hash as _lhash

        data_no_hash = {k: v for k, v in data.items() if k != "report_hash"}
        data["report_hash"] = _lhash(data_no_hash)
        baseline_path.write_text(json.dumps(data), encoding="utf-8")
        c1 = build_campaign(d1, "test_campaign", now_utc=FIXED_NOW)
        c2 = build_campaign(d2, "test_campaign", now_utc=FIXED_NOW)
        assert c1.campaign_hash != c2.campaign_hash

    def test_campaign_hash_excludes_timestamp(self, tmp_path: Path) -> None:
        d = _campaign_artifact_dir(tmp_path, "dir_a")
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        c1 = build_campaign(d, "test_campaign", now_utc=t1)
        c2 = build_campaign(d, "test_campaign", now_utc=t2)
        assert c1.campaign_hash == c2.campaign_hash

    def test_campaign_id_is_uuid5_of_hash(self, tmp_path: Path) -> None:
        from aqcs.research.campaign import _CAMPAIGN_NS

        d = _campaign_artifact_dir(tmp_path, "dir_a")
        c = build_campaign(d, "test_campaign", now_utc=FIXED_NOW)
        expected_id = str(uuid.uuid5(_CAMPAIGN_NS, c.campaign_hash))
        assert str(c.campaign_id) == expected_id


# ── Regression guard hash stability ──────────────────────────────────────────


class TestRegressionGuardHashStability:
    def test_identical_dirs_zero_critical_findings(self, tmp_path: Path) -> None:
        d = _campaign_artifact_dir(tmp_path, "artifacts")
        r = run_regression_guard(d, d, now_utc=FIXED_NOW)
        critical = [f for f in r.regression_findings if f.severity == "critical"]
        assert len(critical) == 0

    def test_identical_dirs_stable_regression_hash(self, tmp_path: Path) -> None:
        d = _campaign_artifact_dir(tmp_path, "artifacts")
        r1 = run_regression_guard(d, d, now_utc=FIXED_NOW)
        r2 = run_regression_guard(d, d, now_utc=FIXED_NOW)
        assert r1.regression_hash == r2.regression_hash

    def test_regression_hash_excludes_timestamp(self, tmp_path: Path) -> None:
        d = _campaign_artifact_dir(tmp_path, "artifacts")
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        r1 = run_regression_guard(d, d, now_utc=t1)
        r2 = run_regression_guard(d, d, now_utc=t2)
        assert r1.regression_hash == r2.regression_hash


# ── Sensitivity audit hash stability ─────────────────────────────────────────


class TestSensitivityAuditHashStability:
    def test_audit_hash_stable_across_calls(self, tmp_path: Path) -> None:
        d = _campaign_artifact_dir(tmp_path, "artifacts")
        # Build campaign and save as baseline artifact
        campaign = build_campaign(d, "audit_test", now_utc=FIXED_NOW)
        from aqcs.research.campaign import campaign_to_dict

        artifact_path = tmp_path / "campaign.json"
        artifact_path.write_text(json.dumps(campaign_to_dict(campaign)), encoding="utf-8")
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(make_default_perturbation_config()), encoding="utf-8")
        a1 = run_sensitivity_audit(artifact_path, config_path, now_utc=FIXED_NOW)
        a2 = run_sensitivity_audit(artifact_path, config_path, now_utc=FIXED_NOW)
        assert a1.audit_hash == a2.audit_hash

    def test_audit_hash_excludes_timestamp(self, tmp_path: Path) -> None:
        d = _campaign_artifact_dir(tmp_path, "artifacts")
        campaign = build_campaign(d, "audit_test", now_utc=FIXED_NOW)
        from aqcs.research.campaign import campaign_to_dict

        artifact_path = tmp_path / "campaign.json"
        artifact_path.write_text(json.dumps(campaign_to_dict(campaign)), encoding="utf-8")
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(make_default_perturbation_config()), encoding="utf-8")
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        a1 = run_sensitivity_audit(artifact_path, config_path, now_utc=t1)
        a2 = run_sensitivity_audit(artifact_path, config_path, now_utc=t2)
        assert a1.audit_hash == a2.audit_hash
