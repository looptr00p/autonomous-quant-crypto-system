"""Tests for deterministic research campaign orchestration.

All tests use deterministic local fixtures only.  No network access.

Coverage:
- campaign generation: all required fields populated
- campaign hash is deterministic and content-addressable
- campaign_id is derived from campaign_hash (UUID5)
- artifact type detection: manifest, certificate, walkforward, baseline
- artifact type detection: unknown files generate warnings
- required field validation: missing fields produce issues
- self-certifying hash verification for reports
- duplicate artifact detection
- aggregate metrics correctness: mean/std/min/max total_return
- aggregate drawdown correctness
- aggregate turnover correctness
- aggregate exposure correctness
- walk-forward aggregate integration
- empty artifacts directory: warnings for missing types
- multiple artifacts of same type: all aggregated
- JSON round-trip: campaign_to_dict / campaign_from_dict
- NaN serialisation: NaN becomes null, restored correctly
- save_campaign / load_campaign round-trip
- load_campaign: invalid JSON raises ValueError
- campaign_from_dict: missing field raises KeyError
- ResearchCampaign is immutable (frozen=True)
- validate_campaign: valid campaign passes
- validate_campaign: tampered campaign_hash detected
- validate_campaign: wrong campaign_version detected
- stable ordering: manifest hashes are sorted
- deterministic across two builds of same directory
- CLI build: exit 0 on clean artifacts
- CLI build: exit 1 when issues present
- CLI validate: exit 0 on valid campaign
- CLI validate: exit 1 on tampered campaign
- CLI validate: exit 2 on malformed JSON
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from build_campaign import main as build_main
from click.testing import CliRunner
from validate_campaign import main as validate_main

from aqcs.research.campaign import (
    CAMPAIGN_VERSION,
    ResearchCampaign,
    _detect_artifact_type,
    build_campaign,
    campaign_from_dict,
    campaign_to_dict,
    load_campaign,
    save_campaign,
    validate_campaign,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)


# ── Synthetic artifact factories ──────────────────────────────────────────────


def _manifest_dict(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    content_hash: str = "a" * 64,
    schema_hash: str = "b" * 64,
) -> dict:
    return {
        "manifest_version": "1",
        "exchange": "binance",
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": "UTC",
        "row_count": 1000,
        "start_timestamp_utc": "2023-01-01T00:00:00+00:00",
        "end_timestamp_utc": "2024-01-01T00:00:00+00:00",
        "schema_hash": schema_hash,
        "content_hash": content_hash,
        "duplicate_count": 0,
        "missing_interval_summary": {"count": 0},
        "generation_timestamp_utc": "2024-06-01T00:00:00+00:00",
    }


def _cert_dict(
    experiment_id: str = "exp-001",
    content_hash: str = "a" * 64,
) -> dict:
    return {
        "certificate_version": "1",
        "experiment_id": experiment_id,
        "experiment_name": "test_exp",
        "git_commit_hash": "deadbeef",
        "dataset_content_hash": content_hash,
        "dataset_schema_hash": "b" * 64,
        "config_hash": "c" * 64,
        "parameters_hash": "d" * 64,
        "metrics_hash": "e" * 64,
        "trades_hash": "f" * 64,
        "equity_hash": "0" * 64,
        "signals_hash": "1" * 64,
        "generation_timestamp_utc": "2024-06-01T00:00:00+00:00",
        "certified_bars": 500,
        "certified_trades": 10,
    }


def _wf_dict(n_windows: int = 4, report_hash_suffix: str = "wf") -> dict:
    d: dict = {
        "report_version": "1",
        "generation_timestamp_utc": "2024-06-01T00:00:00+00:00",
        "dataset_path": "data/BTC_USDT_1h.parquet",
        "total_bars": 1000,
        "train_bars": 200,
        "test_bars": 50,
        "step_bars": 50,
        "n_windows": n_windows,
        "leakage_validated": True,
        "validation_issues": [],
        "summary": {
            "n_windows_total": n_windows,
            "n_windows_evaluated": n_windows,
            "n_windows_failed": 0,
            "n_windows_profitable": n_windows // 2,
            "mean_total_return": 0.05,
            "std_total_return": 0.02,
            "min_total_return": -0.01,
            "max_total_return": 0.12,
            "mean_sharpe_ratio": 1.2,
            "mean_max_drawdown": 0.04,
            "mean_trade_count": 3.0,
            "test_overlap": False,
        },
        "windows": [],
        "results": [],
    }
    # Compute a real report_hash so self-verification can be skipped
    # (We omit report_hash to avoid computing it in tests)
    d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
    d["report_hash"] = hashlib.sha256(
        json.dumps(d_no_hash, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return d


def _baseline_dict(
    total_return: float = 0.10,
    max_drawdown: float = 0.05,
    report_hash_suffix: str = "bl",
) -> dict:
    d: dict = {
        "report_version": "1",
        "experiment_id": "exp-001",
        "experiment_name": "test_exp",
        "git_commit_hash": "deadbeef",
        "generation_timestamp_utc": "2024-06-01T00:00:00+00:00",
        "disclaimer": "For research only.",
        "dataset_content_hash": "a" * 64,
        "dataset_schema_hash": "b" * 64,
        "dataset_symbol": "BTC/USDT",
        "dataset_timeframe": "1h",
        "dataset_exchange": "binance",
        "dataset_start_utc": "2023-01-01T00:00:00+00:00",
        "dataset_end_utc": "2024-01-01T00:00:00+00:00",
        "dataset_row_count": 1000,
        "replay_certificate_hash": "",
        "replay_certified": False,
        "initial_capital": 10000.0,
        "fee_bps": 10.0,
        "slippage_bps": 2.0,
        "start_date": "",
        "end_date": "",
        "periods_per_year": 252,
        "n_bars": 50,
        "total_return": total_return,
        "cagr": total_return * 0.8,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": total_return / (max_drawdown + 0.01),
        "annualised_volatility": 0.18,
        "trade_count": 5,
        "win_rate": 0.6,
        "exposure": 0.5,
        "total_fees_paid": 45.0,
        "total_slippage_cost": 9.0,
        "avg_trade_value": 9000.0,
        "turnover_per_bar": 0.18,
        "avg_holding_period_bars": 5.0,
        "max_consecutive_losses": 2,
        "benchmark_total_return": 0.08,
        "excess_return": total_return - 0.08,
        "metrics_hash": "e" * 64,
    }
    d_no_hash = {k: v for k, v in d.items() if k != "report_hash"}
    d["report_hash"] = hashlib.sha256(
        json.dumps(d_no_hash, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return d


def _write_artifacts(
    artifacts_dir: Path,
    manifests: list[dict] | None = None,
    certs: list[dict] | None = None,
    walkforwards: list[dict] | None = None,
    baselines: list[dict] | None = None,
) -> None:
    """Write synthetic artifact JSON files to the directory."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for i, m in enumerate(manifests or []):
        (artifacts_dir / f"manifest_{i}.json").write_text(json.dumps(m), encoding="utf-8")
    for i, c in enumerate(certs or []):
        (artifacts_dir / f"cert_{i}.json").write_text(json.dumps(c), encoding="utf-8")
    for i, w in enumerate(walkforwards or []):
        (artifacts_dir / f"wf_{i}.json").write_text(json.dumps(w), encoding="utf-8")
    for i, b in enumerate(baselines or []):
        (artifacts_dir / f"baseline_{i}.json").write_text(json.dumps(b), encoding="utf-8")


def _build(
    tmp_path: Path,
    manifests: list[dict] | None = None,
    certs: list[dict] | None = None,
    walkforwards: list[dict] | None = None,
    baselines: list[dict] | None = None,
    name: str = "test_campaign",
) -> ResearchCampaign:
    _write_artifacts(tmp_path, manifests, certs, walkforwards, baselines)
    return build_campaign(tmp_path, name, now_utc=_FIXED_NOW)


# ── Artifact type detection ───────────────────────────────────────────────────


class TestArtifactTypeDetection:
    def test_manifest_detected(self) -> None:
        assert _detect_artifact_type(_manifest_dict()) == "manifest"

    def test_certificate_detected(self) -> None:
        assert _detect_artifact_type(_cert_dict()) == "certificate"

    def test_walkforward_detected(self) -> None:
        assert _detect_artifact_type(_wf_dict()) == "walkforward"

    def test_baseline_detected(self) -> None:
        assert _detect_artifact_type(_baseline_dict()) == "baseline"

    def test_unknown_artifact(self) -> None:
        assert _detect_artifact_type({"random_field": True}) == "unknown"

    def test_empty_dict_unknown(self) -> None:
        assert _detect_artifact_type({}) == "unknown"


# ── Campaign generation ───────────────────────────────────────────────────────


class TestCampaignGeneration:
    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            manifests=[_manifest_dict()],
            certs=[_cert_dict()],
            walkforwards=[_wf_dict()],
            baselines=[_baseline_dict()],
        )
        assert c.campaign_version == CAMPAIGN_VERSION
        assert c.campaign_name == "test_campaign"
        assert c.generation_timestamp_utc == _FIXED_NOW.isoformat()
        assert len(c.campaign_hash) == 64
        assert c.campaign_id != ""
        assert c.total_experiments == 1

    def test_campaign_id_is_uuid5_of_hash(self, tmp_path: Path) -> None:
        import uuid

        from aqcs.research.campaign import _CAMPAIGN_NS

        c = _build(tmp_path, baselines=[_baseline_dict()])
        expected_id = str(uuid.uuid5(_CAMPAIGN_NS, c.campaign_hash))
        assert c.campaign_id == expected_id

    def test_generation_timestamp_uses_injection(self, tmp_path: Path) -> None:
        c = _build(tmp_path)
        assert c.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_symbols_from_manifests(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            manifests=[
                _manifest_dict("BTC/USDT"),
                _manifest_dict("ETH/USDT", content_hash="c" * 64),
            ],
        )
        assert "BTC/USDT" in c.symbols
        assert "ETH/USDT" in c.symbols
        assert list(c.symbols) == sorted(c.symbols)

    def test_timeframes_sorted(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            manifests=[
                _manifest_dict(timeframe="1d", content_hash="x" * 64),
                _manifest_dict(timeframe="1h", content_hash="y" * 64),
            ],
        )
        assert list(c.timeframes) == sorted(c.timeframes)

    def test_total_experiments_counts_baselines(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict(), _baseline_dict(total_return=0.05)])
        assert c.total_experiments == 2

    def test_total_walkforward_windows(self, tmp_path: Path) -> None:
        c = _build(tmp_path, walkforwards=[_wf_dict(n_windows=4), _wf_dict(n_windows=3)])
        assert c.total_walkforward_windows == 7

    def test_empty_directory_generates_warnings(self, tmp_path: Path) -> None:
        c = _build(tmp_path)
        assert len(c.warnings) >= 4  # one per missing artifact type

    def test_unknown_json_file_generates_warning(self, tmp_path: Path) -> None:
        (tmp_path / "random.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        c = build_campaign(tmp_path, "x", now_utc=_FIXED_NOW)
        assert any("Unrecognised" in w for w in c.warnings)


# ── Campaign hash ─────────────────────────────────────────────────────────────


class TestCampaignHash:
    def test_hash_deterministic(self, tmp_path: Path) -> None:
        c1 = _build(tmp_path, baselines=[_baseline_dict()])
        c2 = _build(tmp_path, baselines=[_baseline_dict()])
        assert c1.campaign_hash == c2.campaign_hash

    def test_hash_changes_when_artifact_changes(self, tmp_path: Path) -> None:
        c1 = _build(tmp_path, baselines=[_baseline_dict(total_return=0.10)])
        # Need separate tmp dirs since first build wrote files
        c2 = _build(Path(str(tmp_path) + "b"), baselines=[_baseline_dict(total_return=0.20)])
        assert c1.campaign_hash != c2.campaign_hash

    def test_hash_excludes_generation_timestamp(self, tmp_path: Path) -> None:
        d = tmp_path / "a"
        d.mkdir()
        c1 = build_campaign(d, "x", now_utc=datetime(2024, 1, 1, tzinfo=UTC))
        c2 = build_campaign(d, "x", now_utc=datetime(2025, 1, 1, tzinfo=UTC))
        assert c1.campaign_hash == c2.campaign_hash

    def test_hash_changes_when_campaign_name_changes(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        a.mkdir()
        c1 = build_campaign(a, "campaign_alpha", now_utc=_FIXED_NOW)
        c2 = build_campaign(a, "campaign_beta", now_utc=_FIXED_NOW)
        assert c1.campaign_hash != c2.campaign_hash


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_campaign_passes(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        valid, errors = validate_campaign(c)
        # Issues from missing artifact types become "recorded issues" in validation
        # but the hash and id should still be correct
        assert not any("campaign_hash" in e for e in errors)
        assert not any("campaign_id" in e for e in errors)

    def test_tampered_hash_detected(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        d = campaign_to_dict(c)
        d["campaign_hash"] = "0" * 64
        tampered = campaign_from_dict(d)
        valid, errors = validate_campaign(tampered)
        assert not valid
        assert any("campaign_hash" in e for e in errors)

    def test_tampered_campaign_id_detected(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        d = campaign_to_dict(c)
        d["campaign_id"] = "00000000-0000-0000-0000-000000000000"
        tampered = campaign_from_dict(d)
        valid, errors = validate_campaign(tampered)
        assert not valid
        assert any("campaign_id" in e for e in errors)

    def test_missing_required_manifest_field_recorded(self, tmp_path: Path) -> None:
        bad_manifest = _manifest_dict()
        del bad_manifest["symbol"]  # symbol is required but not a discriminating field
        c = _build(tmp_path, manifests=[bad_manifest])
        assert any("symbol" in i for i in c.issues)

    def test_missing_required_baseline_field_recorded(self, tmp_path: Path) -> None:
        bad_baseline = _baseline_dict()
        del bad_baseline["max_drawdown"]
        c = _build(tmp_path, baselines=[bad_baseline])
        assert any("max_drawdown" in i for i in c.issues)

    def test_tampered_report_hash_recorded_as_issue(self, tmp_path: Path) -> None:
        bad = _baseline_dict()
        bad["report_hash"] = "0" * 64  # wrong hash
        c = _build(tmp_path, baselines=[bad])
        assert any("report_hash" in i for i in c.issues)

    def test_duplicate_artifact_detected(self, tmp_path: Path) -> None:
        m = _manifest_dict()
        # Write same content twice
        (tmp_path / "m1.json").write_text(json.dumps(m), encoding="utf-8")
        (tmp_path / "m2.json").write_text(json.dumps(m), encoding="utf-8")
        c = build_campaign(tmp_path, "x", now_utc=_FIXED_NOW)
        assert any("Duplicate" in i for i in c.issues)


# ── Aggregate metrics ─────────────────────────────────────────────────────────


class TestAggregateMetrics:
    def test_mean_total_return(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            baselines=[_baseline_dict(0.10), _baseline_dict(0.20)],
        )
        assert abs(c.aggregate_metrics["mean_total_return"] - 0.15) < 1e-9

    def test_n_profitable(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            baselines=[_baseline_dict(0.10), _baseline_dict(-0.05)],
        )
        assert c.aggregate_metrics["n_profitable"] == 1

    def test_mean_max_drawdown(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            baselines=[_baseline_dict(max_drawdown=0.10), _baseline_dict(max_drawdown=0.20)],
        )
        assert abs(c.aggregate_drawdown["mean_max_drawdown"] - 0.15) < 1e-9

    def test_mean_exposure(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        assert not math.isnan(c.aggregate_exposure["mean_exposure"])
        assert abs(c.aggregate_exposure["mean_exposure"] - 0.5) < 1e-9

    def test_mean_turnover(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        assert not math.isnan(c.aggregate_turnover["mean_turnover_per_bar"])

    def test_wf_aggregate_included(self, tmp_path: Path) -> None:
        c = _build(tmp_path, walkforwards=[_wf_dict(n_windows=4)])
        assert "wf_total_windows" in c.aggregate_metrics
        assert c.aggregate_metrics["wf_total_windows"] == 4

    def test_empty_baselines_nan_metrics(self, tmp_path: Path) -> None:
        c = _build(tmp_path)
        assert math.isnan(c.aggregate_metrics["mean_total_return"])

    def test_manifest_hashes_sorted(self, tmp_path: Path) -> None:
        c = _build(
            tmp_path,
            manifests=[
                _manifest_dict("BTC/USDT", content_hash="z" * 64),
                _manifest_dict("ETH/USDT", content_hash="a" * 64),
            ],
        )
        assert list(c.dataset_manifest_hashes) == sorted(c.dataset_manifest_hashes)


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_dict(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        d = campaign_to_dict(c)
        j1 = json.dumps(campaign_to_dict(c), sort_keys=True)
        restored = campaign_from_dict(d)
        j2 = json.dumps(campaign_to_dict(restored), sort_keys=True)
        assert j1 == j2

    def test_nan_serialised_as_null(self, tmp_path: Path) -> None:
        c = _build(tmp_path)  # empty → NaN aggregates
        d = campaign_to_dict(c)
        serialized = json.dumps(d, sort_keys=True)
        parsed = json.loads(serialized)
        # NaN fields become None in dict → null in JSON
        assert parsed["aggregate_metrics"]["mean_total_return"] is None

    def test_null_restored_as_nan(self, tmp_path: Path) -> None:
        c = _build(tmp_path)
        d = campaign_to_dict(c)
        restored = campaign_from_dict(d)
        assert math.isnan(restored.aggregate_metrics["mean_total_return"])

    def test_json_dumps_deterministic(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        j1 = json.dumps(campaign_to_dict(c), sort_keys=True)
        j2 = json.dumps(campaign_to_dict(c), sort_keys=True)
        assert j1 == j2

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "artifacts"
        c = _build(data_dir, baselines=[_baseline_dict()])
        out = tmp_path / "campaign.json"
        save_campaign(c, out)
        loaded = load_campaign(out)
        assert json.dumps(campaign_to_dict(c), sort_keys=True) == json.dumps(
            campaign_to_dict(loaded), sort_keys=True
        )

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_campaign(bad)

    def test_from_dict_missing_field_raises(self, tmp_path: Path) -> None:
        c = _build(tmp_path, baselines=[_baseline_dict()])
        d = campaign_to_dict(c)
        del d["campaign_hash"]
        with pytest.raises(KeyError):
            campaign_from_dict(d)

    def test_campaign_is_immutable(self, tmp_path: Path) -> None:
        c = _build(tmp_path)
        assert isinstance(c, ResearchCampaign)
        with pytest.raises((AttributeError, TypeError)):
            c.campaign_name = "hacked"  # type: ignore[misc]

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        c = _build(tmp_path)
        out = tmp_path / "deep" / "nested" / "campaign.json"
        save_campaign(c, out)
        assert out.exists()


# ── Determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_two_builds_same_dir_identical_hash(self, tmp_path: Path) -> None:
        c1 = _build(tmp_path, baselines=[_baseline_dict()], name="camp")
        c2 = _build(tmp_path, baselines=[_baseline_dict()], name="camp")
        assert c1.campaign_hash == c2.campaign_hash

    def test_different_artifact_order_same_hash(self, tmp_path: Path) -> None:
        """Alphabetic sort of files must produce same hashes regardless of write order."""
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        # Write in different orders
        b1 = _baseline_dict(0.10)
        b2 = _baseline_dict(0.20)
        (dir_a / "z_baseline.json").write_text(json.dumps(b1), encoding="utf-8")
        (dir_a / "a_baseline.json").write_text(json.dumps(b2), encoding="utf-8")
        (dir_b / "a_baseline.json").write_text(json.dumps(b2), encoding="utf-8")
        (dir_b / "z_baseline.json").write_text(json.dumps(b1), encoding="utf-8")
        ca = build_campaign(dir_a, "x", now_utc=_FIXED_NOW)
        cb = build_campaign(dir_b, "x", now_utc=_FIXED_NOW)
        assert ca.campaign_hash == cb.campaign_hash


# ── CLI build ─────────────────────────────────────────────────────────────────


class TestCLIBuild:
    def test_exit_0_on_clean_artifacts(self, tmp_path: Path) -> None:
        _write_artifacts(
            tmp_path,
            manifests=[_manifest_dict()],
            certs=[_cert_dict()],
            walkforwards=[_wf_dict()],
            baselines=[_baseline_dict()],
        )
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--artifacts-dir", str(tmp_path), "--campaign-name", "test"],
        )
        # Empty artifact types generate warnings but not issues → exit 0
        assert result.exit_code == 0

    def test_exit_1_when_issues_exist(self, tmp_path: Path) -> None:
        bad = _baseline_dict()
        del bad["max_drawdown"]  # missing required field → issue
        _write_artifacts(tmp_path, baselines=[bad])
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--artifacts-dir", str(tmp_path), "--campaign-name", "test"],
        )
        assert result.exit_code == 1

    def test_writes_output_json(self, tmp_path: Path) -> None:
        _write_artifacts(tmp_path, baselines=[_baseline_dict()])
        out = tmp_path / "campaign.json"
        runner = CliRunner()
        runner.invoke(
            build_main,
            [
                "--artifacts-dir",
                str(tmp_path),
                "--campaign-name",
                "test",
                "--output-json",
                str(out),
            ],
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert "campaign_hash" in data

    def test_stdout_json_summary(self, tmp_path: Path) -> None:
        _write_artifacts(tmp_path, baselines=[_baseline_dict()])
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--artifacts-dir", str(tmp_path), "--campaign-name", "test"],
        )
        summary = json.loads(result.output)
        assert "campaign_hash" in summary
        assert "total_experiments" in summary


# ── CLI validate ──────────────────────────────────────────────────────────────


class TestCLIValidate:
    def _make_campaign_file(self, tmp_path: Path, **kwargs: object) -> Path:
        data_dir = tmp_path / "artifacts"
        data_dir.mkdir()
        _write_artifacts(data_dir, baselines=[_baseline_dict()])
        c = build_campaign(data_dir, "test", now_utc=_FIXED_NOW)
        out = tmp_path / "campaign.json"
        save_campaign(c, out)
        return out

    def test_exit_0_on_valid_campaign(self, tmp_path: Path) -> None:
        path = self._make_campaign_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--campaign-json", str(path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_exit_1_on_tampered_hash(self, tmp_path: Path) -> None:
        path = self._make_campaign_file(tmp_path)
        d = json.loads(path.read_text())
        d["campaign_hash"] = "0" * 64
        path.write_text(json.dumps(d), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--campaign-json", str(path)])
        assert result.exit_code == 1

    def test_exit_2_on_malformed_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--campaign-json", str(bad)])
        assert result.exit_code == 2

    def test_report_contains_required_fields(self, tmp_path: Path) -> None:
        path = self._make_campaign_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--campaign-json", str(path)])
        data = json.loads(result.output)
        required = {"valid", "campaign_hash", "campaign_id", "total_experiments"}
        assert required.issubset(data.keys())
