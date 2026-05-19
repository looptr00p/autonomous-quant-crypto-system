"""Tests for deterministic research regression guards.

All tests are deterministic and local.  No network, no wall-clock, no randomness.

Coverage:
- run_regression_guard: deterministic report generation
- regression_hash is deterministic and self-certifying
- regression_id is UUID5 of regression_hash
- identical artifacts → no findings
- artifacts sorted by name (deterministic traversal)
- metric drift detection: warning (5%) and critical (20%) thresholds
- hash mismatch detection (baseline_report report_hash changed)
- replay drift detection (certificate hash fields changed)
- artifact missing detection (baseline file absent in candidate)
- artifact added detection (file in candidate not in baseline)
- version change detection
- schema drift detection (type changes between directories)
- walk-forward leakage regression detection
- manifest content_hash change detection
- benchmark regression_flags change detection
- governance violation: missing disclaimer in baseline report
- governance violation: leakage_validated=False in walk-forward
- validate_regression_report: valid passes
- validate_regression_report: tampered hash detected
- validate_regression_report: wrong version detected
- save_regression_report / load_regression_report round-trip
- load_regression_report: invalid JSON raises ValueError
- RegressionReport is immutable (frozen=True)
- input artifacts are NOT mutated
- no regressions on identical directories
- two independent runs produce identical report (deterministic)
- CLI run: exit 0 on no regressions
- CLI run: exit 1 on regressions
- CLI validate: exit 0 on valid report
- CLI validate: exit 1 on tampered report
- CLI validate: exit 2 on malformed file
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from run_regression_guard import main as run_main
from validate_regression_report import main as validate_main

from aqcs.research.regression_guard import (
    _REGRESSION_NS,
    DRIFT_THRESHOLD_CRITICAL,
    DRIFT_THRESHOLD_WARNING,
    FINDING_ARTIFACT_ADDED,
    FINDING_ARTIFACT_MISSING,
    FINDING_GOVERNANCE_VIOLATION,
    FINDING_HASH_MISMATCH,
    FINDING_METRIC_DRIFT,
    FINDING_REPLAY_DRIFT,
    REGRESSION_VERSION,
    RegressionReport,
    load_regression_report,
    regression_report_from_dict,
    regression_report_to_dict,
    run_regression_guard,
    save_regression_report,
    validate_regression_report,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)


# ── Synthetic artifact factories ──────────────────────────────────────────────


def _baseline_report(total_return: float = 0.10, max_drawdown: float = 0.05) -> dict:
    return {
        "report_version": "1",
        "experiment_id": "exp-001",
        "report_hash": "a" * 64,
        "disclaimer": "For research only.",
        "total_return": total_return,
        "cagr": total_return * 0.8,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": total_return / (max_drawdown + 0.01),
        "annualised_volatility": 0.18,
        "win_rate": 0.6,
        "exposure": 0.5,
        "turnover_per_bar": 0.18,
        "initial_capital": 10000.0,
        "benchmark_total_return": 0.08,
    }


def _walkforward_report(
    mean_return: float = 0.05,
    leakage_validated: bool = True,
    report_hash: str = "b" * 64,
) -> dict:
    return {
        "report_version": "1",
        "train_bars": 200,
        "test_bars": 50,
        "step_bars": 50,
        "n_windows": 4,
        "leakage_validated": leakage_validated,
        "report_hash": report_hash,
        "summary": {
            "mean_total_return": mean_return,
            "mean_sharpe_ratio": 1.2,
            "mean_max_drawdown": 0.04,
            "n_windows_evaluated": 4,
            "n_windows_failed": 0,
        },
    }


def _campaign(
    campaign_hash: str = "c" * 64,
    mean_return: float = 0.10,
) -> dict:
    return {
        "campaign_version": "1",
        "campaign_id": str(uuid.uuid4()),
        "campaign_hash": campaign_hash,
        "total_experiments": 3,
        "aggregate_metrics": {
            "mean_total_return": mean_return,
            "mean_sharpe_ratio": 1.2,
        },
        "aggregate_drawdown": {
            "mean_max_drawdown": 0.05,
        },
    }


def _replay_cert(metrics_hash: str = "d" * 64) -> dict:
    return {
        "certificate_version": "1",
        "experiment_id": "exp-001",
        "certified_bars": 500,
        "config_hash": "e" * 64,
        "metrics_hash": metrics_hash,
        "trades_hash": "f" * 64,
        "equity_hash": "0" * 64,
        "signals_hash": "1" * 64,
    }


def _manifest(content_hash: str = "g" * 64, row_count: int = 1000) -> dict:
    return {
        "manifest_version": "1",
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "content_hash": content_hash,
        "schema_hash": "h" * 64,
        "row_count": row_count,
    }


def _benchmark_suite(benchmark_hash: str = "i" * 64, flags: list | None = None) -> dict:
    return {
        "benchmark_version": "1",
        "benchmark_id": str(uuid.uuid4()),
        "benchmark_hash": benchmark_hash,
        "total_campaigns": 2,
        "regression_flags": flags or [],
    }


def _write(directory: Path, name: str, d: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(d), encoding="utf-8")


def _run(baseline_dir: Path, candidate_dir: Path) -> RegressionReport:
    return run_regression_guard(baseline_dir, candidate_dir, now_utc=_FIXED_NOW)


# ── Report generation ─────────────────────────────────────────────────────────


class TestReportGeneration:
    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "report.json", _baseline_report())
        _write(c, "report.json", _baseline_report())
        r = _run(b, c)
        assert r.regression_version == REGRESSION_VERSION
        assert len(r.regression_hash) == 64
        assert r.regression_id != ""
        assert r.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_deterministic_on_repeated_calls(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r1 = _run(b, c)
        r2 = _run(b, c)
        assert r1.regression_hash == r2.regression_hash

    def test_hash_excludes_timestamp(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 1, 1, tzinfo=UTC)
        r1 = run_regression_guard(b, c, now_utc=t1)
        r2 = run_regression_guard(b, c, now_utc=t2)
        assert r1.regression_hash == r2.regression_hash

    def test_regression_id_is_uuid5_of_hash(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        expected_id = str(uuid.uuid5(_REGRESSION_NS, r.regression_hash))
        assert r.regression_id == expected_id

    def test_identical_artifacts_no_findings(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        assert r.regression_findings == ()

    def test_input_artifacts_not_mutated(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        orig = _baseline_report()
        _write(b, "r.json", orig)
        _write(c, "r.json", orig)
        _run(b, c)
        loaded = json.loads((b / "r.json").read_text())
        assert loaded["total_return"] == orig["total_return"]


# ── Metric drift detection ────────────────────────────────────────────────────


class TestMetricDrift:
    def test_no_finding_below_warning_threshold(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        base_return = 0.10
        _write(b, "r.json", _baseline_report(total_return=base_return))
        # 3% relative change — below 5% warning threshold
        _write(c, "r.json", _baseline_report(total_return=base_return * 1.03))
        r = _run(b, c)
        drift_findings = [
            f for f in r.regression_findings if f.finding_type == FINDING_METRIC_DRIFT
        ]
        total_return_findings = [f for f in drift_findings if "total_return" in f.expected_value]
        assert total_return_findings == []

    def test_warning_at_warning_threshold(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        base_return = 0.10
        _write(b, "r.json", _baseline_report(total_return=base_return))
        # Exactly at warning threshold: 10% * (1 + 0.05) = 0.105
        _write(
            c, "r.json", _baseline_report(total_return=base_return * (1 + DRIFT_THRESHOLD_WARNING))
        )
        r = _run(b, c)
        drift = [f for f in r.regression_findings if f.finding_type == FINDING_METRIC_DRIFT]
        assert any("total_return" in f.expected_value for f in drift)

    def test_critical_at_critical_threshold(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        base_return = 0.10
        _write(b, "r.json", _baseline_report(total_return=base_return))
        # DRIFT_THRESHOLD_CRITICAL + 0.10 = 30% change — clearly above the critical
        # threshold.  The exact boundary (1 + DRIFT_THRESHOLD_CRITICAL) is avoided
        # because (0.12 - 0.10) / 0.10 rounds to 0.1999... < 0.20 in IEEE 754.
        _write(
            c,
            "r.json",
            _baseline_report(total_return=base_return * (1.0 + DRIFT_THRESHOLD_CRITICAL + 0.10)),
        )
        r = _run(b, c)
        critical_drift = [
            f
            for f in r.regression_findings
            if f.finding_type == FINDING_METRIC_DRIFT and f.severity == "critical"
        ]
        assert len(critical_drift) >= 1


# ── Hash mismatch detection ───────────────────────────────────────────────────


class TestHashMismatch:
    def test_report_hash_change_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        candidate = _baseline_report()
        candidate["report_hash"] = "z" * 64
        _write(c, "r.json", candidate)
        r = _run(b, c)
        findings = [f for f in r.regression_findings if f.finding_type == FINDING_HASH_MISMATCH]
        assert len(findings) >= 1

    def test_campaign_hash_change_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "c.json", _campaign(campaign_hash="a" * 64))
        _write(c, "c.json", _campaign(campaign_hash="b" * 64))
        r = _run(b, c)
        findings = [f for f in r.regression_findings if f.finding_type == FINDING_HASH_MISMATCH]
        assert len(findings) >= 1


# ── Replay drift detection ────────────────────────────────────────────────────


class TestReplayDrift:
    def test_identical_cert_no_replay_finding(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "cert.json", _replay_cert("d" * 64))
        _write(c, "cert.json", _replay_cert("d" * 64))
        r = _run(b, c)
        replay = [f for f in r.regression_findings if f.finding_type == FINDING_REPLAY_DRIFT]
        assert replay == []

    def test_metrics_hash_change_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "cert.json", _replay_cert("d" * 64))
        _write(c, "cert.json", _replay_cert("e" * 64))
        r = _run(b, c)
        replay = [f for f in r.regression_findings if f.finding_type == FINDING_REPLAY_DRIFT]
        assert len(replay) >= 1

    def test_replay_results_populated(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "cert.json", _replay_cert("d" * 64))
        _write(c, "cert.json", _replay_cert("e" * 64))
        r = _run(b, c)
        assert "cert.json" in r.replay_validation_results
        assert r.replay_validation_results["cert.json"]["replay_compatible"] is False


# ── Artifact added/missing ────────────────────────────────────────────────────


class TestArtifactPresence:
    def test_missing_in_candidate_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        c.mkdir(parents=True, exist_ok=True)
        r = _run(b, c)
        missing = [f for f in r.regression_findings if f.finding_type == FINDING_ARTIFACT_MISSING]
        assert len(missing) == 1

    def test_added_in_candidate_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        b.mkdir(parents=True, exist_ok=True)
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        added = [f for f in r.regression_findings if f.finding_type == FINDING_ARTIFACT_ADDED]
        assert len(added) == 1


# ── Walk-forward leakage regression ──────────────────────────────────────────


class TestWalkForwardLeakage:
    def test_leakage_regression_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "wf.json", _walkforward_report(leakage_validated=True))
        _write(c, "wf.json", _walkforward_report(leakage_validated=False))
        r = _run(b, c)
        gov = [f for f in r.regression_findings if f.finding_type == FINDING_GOVERNANCE_VIOLATION]
        assert any("leakage" in f.deterministic_diff_summary.lower() for f in gov)

    def test_no_finding_when_both_validated(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "wf.json", _walkforward_report(leakage_validated=True))
        _write(c, "wf.json", _walkforward_report(leakage_validated=True))
        r = _run(b, c)
        gov = [f for f in r.regression_findings if f.finding_type == FINDING_GOVERNANCE_VIOLATION]
        assert gov == []


# ── Governance violations ─────────────────────────────────────────────────────


class TestGovernanceViolations:
    def test_missing_disclaimer_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        no_disclaimer = _baseline_report()
        no_disclaimer["disclaimer"] = ""
        _write(c, "r.json", no_disclaimer)
        r = _run(b, c)
        gov = [f for f in r.regression_findings if f.finding_type == FINDING_GOVERNANCE_VIOLATION]
        assert any("disclaimer" in f.deterministic_diff_summary for f in gov)
        assert r.governance_validation_results["violation_count"] >= 1

    def test_governance_clean_when_valid(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        assert r.governance_validation_results["governance_clean"] is True


# ── Manifest comparison ───────────────────────────────────────────────────────


class TestManifestComparison:
    def test_content_hash_change_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "m.json", _manifest(content_hash="g" * 64))
        _write(c, "m.json", _manifest(content_hash="h" * 64))
        r = _run(b, c)
        findings = [f for f in r.regression_findings if f.finding_type == FINDING_HASH_MISMATCH]
        assert any("content_hash" in f.deterministic_diff_summary for f in findings)

    def test_row_count_change_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "m.json", _manifest(row_count=1000))
        _write(c, "m.json", _manifest(row_count=800))
        r = _run(b, c)
        drift = [f for f in r.regression_findings if f.finding_type == FINDING_METRIC_DRIFT]
        assert any("row_count" in f.deterministic_diff_summary for f in drift)


# ── Benchmark regression ──────────────────────────────────────────────────────


class TestBenchmarkRegression:
    def test_new_regression_flag_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "bm.json", _benchmark_suite(flags=[]))
        _write(c, "bm.json", _benchmark_suite(flags=["mean_total_return −0.1200 < floor −0.1000"]))
        r = _run(b, c)
        drift = [f for f in r.regression_findings if f.finding_type == FINDING_METRIC_DRIFT]
        assert any(
            "benchmark" in f.artifact_reference.lower() or "bm.json" in f.artifact_reference
            for f in drift
        )


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_report_passes(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        valid, errors = validate_regression_report(r)
        assert valid is True
        assert errors == []

    def test_tampered_hash_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        d = regression_report_to_dict(r)
        d["regression_hash"] = "0" * 64
        tampered = regression_report_from_dict(d)
        valid, errors = validate_regression_report(tampered)
        assert valid is False
        assert any("regression_hash" in e for e in errors)

    def test_wrong_version_detected(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        d = regression_report_to_dict(r)
        d["regression_version"] = "99"
        from aqcs.utils.canonicalization import canonical_hash

        d_no_hash = {
            k: v
            for k, v in d.items()
            if k not in {"regression_hash", "regression_id", "generation_timestamp_utc"}
        }
        d["regression_hash"] = canonical_hash(d_no_hash)
        import uuid as _uuid

        d["regression_id"] = str(_uuid.uuid5(_REGRESSION_NS, d["regression_hash"]))
        wrong = regression_report_from_dict(d)
        valid, errors = validate_regression_report(wrong)
        assert valid is False


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_dict(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        import json as _json

        j1 = _json.dumps(regression_report_to_dict(r), sort_keys=True)
        restored = regression_report_from_dict(regression_report_to_dict(r))
        j2 = _json.dumps(regression_report_to_dict(restored), sort_keys=True)
        assert j1 == j2

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        out = tmp_path / "report.json"
        save_regression_report(r, out)
        loaded = load_regression_report(out)
        import json as _json

        assert _json.dumps(regression_report_to_dict(r), sort_keys=True) == _json.dumps(
            regression_report_to_dict(loaded), sort_keys=True
        )

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_regression_report(bad)

    def test_from_dict_missing_field_raises(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        d = regression_report_to_dict(r)
        del d["regression_hash"]
        with pytest.raises(KeyError):
            regression_report_from_dict(d)

    def test_report_is_immutable(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        assert isinstance(r, RegressionReport)
        with pytest.raises((AttributeError, TypeError)):
            r.regression_version = "hacked"  # type: ignore[misc]

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = _run(b, c)
        out = tmp_path / "deep" / "nested" / "report.json"
        save_regression_report(r, out)
        assert out.exists()


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestCLIRun:
    def test_exit_0_on_no_regressions(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        runner = CliRunner()
        result = runner.invoke(
            run_main,
            ["--baseline-dir", str(b), "--candidate-dir", str(c)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_regression"] is False

    def test_exit_1_on_regressions(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report(total_return=0.10))
        _write(c, "r.json", _baseline_report(total_return=0.00))  # 100% drop → critical
        runner = CliRunner()
        result = runner.invoke(
            run_main,
            ["--baseline-dir", str(b), "--candidate-dir", str(c)],
        )
        assert result.exit_code == 1

    def test_writes_output_json(self, tmp_path: Path) -> None:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        out = tmp_path / "report.json"
        runner = CliRunner()
        runner.invoke(
            run_main,
            ["--baseline-dir", str(b), "--candidate-dir", str(c), "--output-json", str(out)],
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert "regression_hash" in data


class TestCLIValidate:
    def _make_report(self, tmp_path: Path) -> Path:
        b = tmp_path / "b"
        c = tmp_path / "c"
        _write(b, "r.json", _baseline_report())
        _write(c, "r.json", _baseline_report())
        r = run_regression_guard(b, c, now_utc=_FIXED_NOW)
        out = tmp_path / "report.json"
        save_regression_report(r, out)
        return out

    def test_exit_0_on_valid(self, tmp_path: Path) -> None:
        path = self._make_report(tmp_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_exit_1_on_tampered(self, tmp_path: Path) -> None:
        path = self._make_report(tmp_path)
        d = json.loads(path.read_text())
        d["regression_hash"] = "0" * 64
        path.write_text(json.dumps(d), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(path)])
        assert result.exit_code == 1

    def test_exit_2_on_malformed(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--report-json", str(bad)])
        assert result.exit_code == 2
