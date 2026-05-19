"""Tests for deterministic benchmark suite infrastructure.

All tests are deterministic and local.  No network, no wall-clock, no randomness.

Coverage:
- build_benchmark_suite: all required fields populated
- benchmark_hash is deterministic and self-certifying
- benchmark_id is UUID5 of benchmark_hash
- campaigns sorted by (campaign_hash, campaign_id)
- ranking by descending score is deterministic
- duplicate campaign rejection
- tampered campaign rejection (hash mismatch)
- malformed campaign rejection
- scoring: all components explicit and bounded [0, 1]
- score weight constants sum to 1.0
- regression flag detection: return floor, drawdown ceiling, sharpe floor, issue ceiling
- no regression flags on healthy campaign
- suite-level comparison metrics
- advisory disclaimer present in ranking_metrics
- benchmark_hash excludes generation_timestamp_utc
- validate_benchmark: valid passes
- validate_benchmark: tampered hash detected
- validate_benchmark: wrong version detected
- validate_benchmark: total_campaigns mismatch detected
- JSON round-trip: benchmark_to_dict / benchmark_from_dict
- save_benchmark / load_benchmark round-trip
- load_benchmark: invalid JSON raises ValueError
- BenchmarkSuite is immutable (frozen=True)
- input campaign artifacts are NOT mutated
- no optimization logic: scores are reproducible pure functions
- stable ranking: same input → same rank order
- CLI build: exit 0 on clean campaigns
- CLI build: exit 1 when regressions/issues
- CLI validate: exit 0 on valid benchmark
- CLI validate: exit 1 on tampered benchmark
- CLI validate: exit 2 on malformed file
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from build_benchmark_suite import main as build_main
from click.testing import CliRunner
from validate_benchmark_suite import main as validate_main

from aqcs.research.benchmark_suite import (
    _BENCHMARK_NS,
    BENCHMARK_VERSION,
    REGRESSION_DRAWDOWN_CEIL,
    REGRESSION_ISSUE_CEIL,
    REGRESSION_RETURN_FLOOR,
    REGRESSION_SHARPE_FLOOR,
    SCORE_WEIGHT_ISSUE_PENALTY,
    SCORE_WEIGHT_MAX_DRAWDOWN,
    SCORE_WEIGHT_SHARPE,
    SCORE_WEIGHT_TOTAL_RETURN,
    SCORE_WEIGHT_WF_COVERAGE,
    BenchmarkSuite,
    benchmark_from_dict,
    benchmark_to_dict,
    build_benchmark_suite,
    load_benchmark,
    save_benchmark,
    validate_benchmark,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)


# ── Synthetic campaign factory ────────────────────────────────────────────────


def _campaign_dict(
    name: str = "test_campaign",
    total_return: float = 0.10,
    max_drawdown: float = 0.05,
    sharpe: float = 1.2,
    n_experiments: int = 3,
    n_wf_windows: int = 20,
    n_issues: int = 0,
) -> dict:
    """Return a minimal synthetic ResearchCampaign dict."""
    from aqcs.utils.canonicalization import canonical_hash

    d: dict = {
        "campaign_version": "1",
        "campaign_name": name,
        "generation_timestamp_utc": "2024-06-01T00:00:00+00:00",
        "dataset_manifest_hashes": [],
        "replay_certificate_hashes": [],
        "walkforward_report_hashes": [],
        "baseline_report_hashes": [],
        "total_experiments": n_experiments,
        "total_walkforward_windows": n_wf_windows,
        "symbols": ["BTC/USDT"],
        "timeframes": ["1h"],
        "aggregate_metrics": {
            "n_experiments": n_experiments,
            "n_profitable": max(0, n_experiments - 1),
            "mean_total_return": total_return,
            "std_total_return": 0.02,
            "min_total_return": total_return - 0.05,
            "max_total_return": total_return + 0.05,
            "mean_sharpe_ratio": sharpe,
            "mean_trade_count": 5.0,
            "mean_win_rate": 0.6,
            "wf_n_reports": 1,
            "wf_total_windows": n_wf_windows,
            "wf_total_profitable_windows": n_wf_windows // 2,
            "wf_total_evaluated_windows": n_wf_windows,
            "wf_mean_window_total_return": total_return * 0.9,
            "wf_mean_window_sharpe_ratio": sharpe * 0.9,
        },
        "aggregate_drawdown": {
            "mean_max_drawdown": max_drawdown,
            "max_max_drawdown": max_drawdown + 0.02,
            "min_max_drawdown": max_drawdown - 0.01,
            "std_max_drawdown": 0.01,
        },
        "aggregate_turnover": {
            "mean_turnover_per_bar": 0.18,
            "mean_total_fees_paid": 45.0,
            "mean_total_slippage_cost": 9.0,
        },
        "aggregate_exposure": {
            "mean_exposure": 0.5,
            "std_exposure": 0.05,
            "mean_avg_holding_period_bars": 5.0,
        },
        "artifact_hashes": {},
        "issues": [f"issue_{i}" for i in range(n_issues)],
        "warnings": [],
    }

    # Compute deterministic campaign_hash and campaign_id
    from aqcs.research.campaign import _CAMPAIGN_NS

    content: dict = {
        k: v
        for k, v in d.items()
        if k not in {"campaign_hash", "campaign_id", "generation_timestamp_utc"}
    }
    campaign_hash = canonical_hash(content)
    campaign_id = str(uuid.uuid5(_CAMPAIGN_NS, campaign_hash))

    d["campaign_hash"] = campaign_hash
    d["campaign_id"] = campaign_id
    return d


def _write_campaign(tmp_path: Path, name: str = "test_campaign", **kwargs: object) -> Path:
    d = _campaign_dict(name=name, **kwargs)  # type: ignore[arg-type]
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    return path


def _build(
    tmp_path: Path,
    campaigns: list[dict] | None = None,
    name: str = "test_benchmark",
) -> BenchmarkSuite:
    """Write synthetic campaign files and build a benchmark suite."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(campaigns or [_campaign_dict()]):
        (tmp_path / f"campaign_{i}.json").write_text(json.dumps(c), encoding="utf-8")
    return build_benchmark_suite(
        list(sorted(tmp_path.glob("*.json"))),
        name,
        now_utc=_FIXED_NOW,
    )


# ── Benchmark generation ──────────────────────────────────────────────────────


class TestBenchmarkGeneration:
    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        assert suite.benchmark_version == BENCHMARK_VERSION
        assert suite.benchmark_name == "test_benchmark"
        assert suite.generation_timestamp_utc == _FIXED_NOW.isoformat()
        assert len(suite.benchmark_hash) == 64
        assert suite.benchmark_id != ""
        assert suite.total_campaigns == 1

    def test_generation_timestamp_uses_injection(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        assert suite.generation_timestamp_utc == _FIXED_NOW.isoformat()

    def test_comparison_entries_count_matches_campaigns(self, tmp_path: Path) -> None:
        suite = _build(tmp_path, campaigns=[_campaign_dict("a"), _campaign_dict("b")])
        assert len(suite.comparison_entries) == 2

    def test_advisory_disclaimer_in_ranking_metrics(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        assert "advisory_disclaimer" in suite.ranking_metrics

    def test_empty_list_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            build_benchmark_suite([], "test")

    def test_campaign_hash_excluded_from_benchmark_hash(self, tmp_path: Path) -> None:
        # Benchmark hash must not depend on generation_timestamp_utc
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 1, 1, tzinfo=UTC)
        c = [_campaign_dict()]
        files = [tmp_path / "c.json"]
        files[0].write_text(json.dumps(c[0]), encoding="utf-8")
        s1 = build_benchmark_suite(files, "test", now_utc=t1)
        s2 = build_benchmark_suite(files, "test", now_utc=t2)
        assert s1.benchmark_hash == s2.benchmark_hash


# ── Deterministic ordering ────────────────────────────────────────────────────


class TestDeterministicOrdering:
    def test_campaigns_sorted_by_hash(self, tmp_path: Path) -> None:
        c1 = _campaign_dict("alpha", total_return=0.10)
        c2 = _campaign_dict("beta", total_return=0.20)
        suite = _build(tmp_path, campaigns=[c2, c1])
        hashes = [e.campaign_hash for e in suite.comparison_entries]
        # Entries are sorted by (campaign_hash, campaign_id) — deterministic
        assert hashes == sorted(hashes)

    def test_two_builds_same_hash(self, tmp_path: Path) -> None:
        c = _campaign_dict()
        f = [tmp_path / "c.json"]
        f[0].write_text(json.dumps(c), encoding="utf-8")
        s1 = build_benchmark_suite(f, "x", now_utc=_FIXED_NOW)
        s2 = build_benchmark_suite(f, "x", now_utc=_FIXED_NOW)
        assert s1.benchmark_hash == s2.benchmark_hash

    def test_ranking_stable(self, tmp_path: Path) -> None:
        # Higher return → higher score → rank 1
        c_high = _campaign_dict("high", total_return=0.30, max_drawdown=0.03, sharpe=2.0)
        c_low = _campaign_dict("low", total_return=0.05, max_drawdown=0.15, sharpe=0.5)
        suite = _build(tmp_path, campaigns=[c_low, c_high])
        by_rank = sorted(suite.comparison_entries, key=lambda e: e.rank)
        assert by_rank[0].campaign_name == "high"


# ── Duplicate and tamper detection ────────────────────────────────────────────


class TestCampaignValidation:
    def test_duplicate_campaign_rejected(self, tmp_path: Path) -> None:
        c = _campaign_dict()
        (tmp_path / "a.json").write_text(json.dumps(c), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(c), encoding="utf-8")
        files = sorted(tmp_path.glob("*.json"))
        suite = build_benchmark_suite(files, "x", now_utc=_FIXED_NOW)
        assert suite.total_campaigns == 1
        assert any("Duplicate" in i for i in suite.issues)

    def test_tampered_campaign_hash_rejected(self, tmp_path: Path) -> None:
        c = _campaign_dict()
        c["campaign_hash"] = "0" * 64
        (tmp_path / "c.json").write_text(json.dumps(c), encoding="utf-8")
        suite = build_benchmark_suite([tmp_path / "c.json"], "x", now_utc=_FIXED_NOW)
        assert suite.total_campaigns == 0
        assert any("hash validation" in i for i in suite.issues)

    def test_malformed_campaign_recorded_as_issue(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        suite = build_benchmark_suite([bad], "x", now_utc=_FIXED_NOW)
        assert any("Cannot load" in i for i in suite.issues)

    def test_campaign_issues_become_warnings(self, tmp_path: Path) -> None:
        c = _campaign_dict(n_issues=2)
        (tmp_path / "c.json").write_text(json.dumps(c), encoding="utf-8")
        suite = build_benchmark_suite([tmp_path / "c.json"], "x", now_utc=_FIXED_NOW)
        assert any("2 recorded issue" in w for w in suite.warnings)


# ── Scoring ───────────────────────────────────────────────────────────────────


class TestScoring:
    def test_score_weights_sum_to_one(self) -> None:
        total = (
            SCORE_WEIGHT_TOTAL_RETURN
            + SCORE_WEIGHT_MAX_DRAWDOWN
            + SCORE_WEIGHT_SHARPE
            + SCORE_WEIGHT_WF_COVERAGE
            + SCORE_WEIGHT_ISSUE_PENALTY
        )
        assert abs(total - 1.0) < 1e-9

    def test_score_is_in_zero_one(self, tmp_path: Path) -> None:
        suite = _build(tmp_path, campaigns=[_campaign_dict()])
        for e in suite.comparison_entries:
            assert 0.0 <= e.score <= 1.0

    def test_score_components_bounded(self, tmp_path: Path) -> None:
        suite = _build(tmp_path, campaigns=[_campaign_dict()])
        for e in suite.comparison_entries:
            for k, v in e.score_components.items():
                assert 0.0 <= v <= 1.0, f"Component {k}={v} out of [0, 1]"

    def test_higher_return_higher_score(self, tmp_path: Path) -> None:
        c_good = _campaign_dict("good", total_return=0.30, max_drawdown=0.05, sharpe=2.0)
        c_bad = _campaign_dict("bad", total_return=0.02, max_drawdown=0.20, sharpe=0.3)
        suite = _build(tmp_path, campaigns=[c_good, c_bad])
        scores = {e.campaign_name: e.score for e in suite.comparison_entries}
        assert scores["good"] > scores["bad"]

    def test_score_deterministic(self, tmp_path: Path) -> None:
        c = _campaign_dict()
        f = [tmp_path / "c.json"]
        f[0].write_text(json.dumps(c), encoding="utf-8")
        s1 = build_benchmark_suite(f, "x", now_utc=_FIXED_NOW)
        s2 = build_benchmark_suite(f, "x", now_utc=_FIXED_NOW)
        assert s1.comparison_entries[0].score == s2.comparison_entries[0].score

    def test_all_score_components_present(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        expected_keys = {
            "return_component",
            "drawdown_component",
            "sharpe_component",
            "wf_component",
            "issue_component",
        }
        for e in suite.comparison_entries:
            assert expected_keys.issubset(e.score_components.keys())

    def test_input_campaigns_not_mutated(self, tmp_path: Path) -> None:
        c = _campaign_dict()
        original_hash = c["campaign_hash"]
        (tmp_path / "c.json").write_text(json.dumps(c), encoding="utf-8")
        build_benchmark_suite([tmp_path / "c.json"], "x", now_utc=_FIXED_NOW)
        assert c["campaign_hash"] == original_hash


# ── Regression flags ──────────────────────────────────────────────────────────


class TestRegressionFlags:
    def test_no_flags_for_healthy_campaign(self, tmp_path: Path) -> None:
        c = _campaign_dict(total_return=0.15, max_drawdown=0.08, sharpe=1.5)
        suite = _build(tmp_path, campaigns=[c])
        assert suite.comparison_entries[0].regression_flags == ()
        assert suite.regression_flags == ()

    def test_return_floor_flag(self, tmp_path: Path) -> None:
        c = _campaign_dict(total_return=REGRESSION_RETURN_FLOOR - 0.01)
        suite = _build(tmp_path, campaigns=[c])
        flags = suite.comparison_entries[0].regression_flags
        assert any("mean_total_return" in f for f in flags)

    def test_drawdown_ceiling_flag(self, tmp_path: Path) -> None:
        c = _campaign_dict(max_drawdown=REGRESSION_DRAWDOWN_CEIL + 0.01)
        suite = _build(tmp_path, campaigns=[c])
        flags = suite.comparison_entries[0].regression_flags
        assert any("mean_max_drawdown" in f for f in flags)

    def test_sharpe_floor_flag(self, tmp_path: Path) -> None:
        c = _campaign_dict(sharpe=REGRESSION_SHARPE_FLOOR - 0.01)
        suite = _build(tmp_path, campaigns=[c])
        flags = suite.comparison_entries[0].regression_flags
        assert any("mean_sharpe_ratio" in f for f in flags)

    def test_issue_count_flag(self, tmp_path: Path) -> None:
        c = _campaign_dict(n_issues=REGRESSION_ISSUE_CEIL + 1)
        suite = _build(tmp_path, campaigns=[c])
        flags = suite.comparison_entries[0].regression_flags
        assert any("issues" in f for f in flags)

    def test_regression_flags_bubble_to_suite(self, tmp_path: Path) -> None:
        c = _campaign_dict(total_return=REGRESSION_RETURN_FLOOR - 0.05)
        suite = _build(tmp_path, campaigns=[c])
        assert len(suite.regression_flags) > 0


# ── Suite validation ──────────────────────────────────────────────────────────


class TestBenchmarkValidation:
    def test_valid_suite_passes(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        valid, errors = validate_benchmark(suite)
        assert valid is True
        assert errors == []

    def test_tampered_hash_detected(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        d = benchmark_to_dict(suite)
        d["benchmark_hash"] = "0" * 64
        tampered = benchmark_from_dict(d)
        valid, errors = validate_benchmark(tampered)
        assert valid is False
        assert any("benchmark_hash" in e for e in errors)

    def test_wrong_version_detected(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        d = benchmark_to_dict(suite)
        d["benchmark_version"] = "99"
        from aqcs.utils.canonicalization import canonical_hash

        d_no_hash = {
            k: v for k, v in d.items() if k not in {"benchmark_hash", "generation_timestamp_utc"}
        }
        d["benchmark_hash"] = canonical_hash(d_no_hash)
        d["benchmark_id"] = str(uuid.uuid5(_BENCHMARK_NS, d["benchmark_hash"]))
        wrong = benchmark_from_dict(d)
        valid, errors = validate_benchmark(wrong)
        assert valid is False

    def test_total_campaigns_mismatch_detected(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        d = benchmark_to_dict(suite)
        d["total_campaigns"] = 999
        from aqcs.utils.canonicalization import canonical_hash

        d_no_hash = {
            k: v for k, v in d.items() if k not in {"benchmark_hash", "generation_timestamp_utc"}
        }
        d["benchmark_hash"] = canonical_hash(d_no_hash)
        d["benchmark_id"] = str(uuid.uuid5(_BENCHMARK_NS, d["benchmark_hash"]))
        wrong = benchmark_from_dict(d)
        valid, errors = validate_benchmark(wrong)
        assert valid is False


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_dict(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        d = benchmark_to_dict(suite)
        j1 = json.dumps(benchmark_to_dict(suite), sort_keys=True)
        restored = benchmark_from_dict(d)
        j2 = json.dumps(benchmark_to_dict(restored), sort_keys=True)
        assert j1 == j2

    def test_json_dumps_deterministic(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        j1 = json.dumps(benchmark_to_dict(suite), sort_keys=True)
        j2 = json.dumps(benchmark_to_dict(suite), sort_keys=True)
        assert j1 == j2

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "campaigns"
        suite = _build(data_dir)
        out = tmp_path / "bench.json"
        save_benchmark(suite, out)
        loaded = load_benchmark(out)
        assert json.dumps(benchmark_to_dict(suite), sort_keys=True) == json.dumps(
            benchmark_to_dict(loaded), sort_keys=True
        )

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_benchmark(bad)

    def test_from_dict_missing_field_raises(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        d = benchmark_to_dict(suite)
        del d["benchmark_hash"]
        with pytest.raises(KeyError):
            benchmark_from_dict(d)

    def test_suite_is_immutable(self, tmp_path: Path) -> None:
        suite = _build(tmp_path)
        assert isinstance(suite, BenchmarkSuite)
        with pytest.raises((AttributeError, TypeError)):
            suite.benchmark_name = "hacked"  # type: ignore[misc]

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "campaigns"
        suite = _build(data_dir)
        out = tmp_path / "deep" / "nested" / "bench.json"
        save_benchmark(suite, out)
        assert out.exists()


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestCLIBuild:
    def test_exit_0_on_clean_campaign(self, tmp_path: Path) -> None:
        c = _campaign_dict(total_return=0.15, max_drawdown=0.08, sharpe=1.5)
        (tmp_path / "c.json").write_text(json.dumps(c), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--campaigns-dir", str(tmp_path), "--benchmark-name", "test"],
        )
        assert result.exit_code == 0

    def test_exit_1_on_regression(self, tmp_path: Path) -> None:
        c = _campaign_dict(total_return=REGRESSION_RETURN_FLOOR - 0.05)
        (tmp_path / "c.json").write_text(json.dumps(c), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--campaigns-dir", str(tmp_path), "--benchmark-name", "test"],
        )
        assert result.exit_code == 1

    def test_exit_2_on_no_json_files(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            build_main,
            ["--campaigns-dir", str(tmp_path), "--benchmark-name", "test"],
        )
        assert result.exit_code == 2

    def test_writes_output_json(self, tmp_path: Path) -> None:
        c = _campaign_dict()
        (tmp_path / "c.json").write_text(json.dumps(c), encoding="utf-8")
        out = tmp_path / "bench.json"
        runner = CliRunner()
        runner.invoke(
            build_main,
            [
                "--campaigns-dir",
                str(tmp_path),
                "--benchmark-name",
                "test",
                "--output-json",
                str(out),
            ],
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert "benchmark_hash" in data


class TestCLIValidate:
    def _make_benchmark_file(self, tmp_path: Path) -> Path:
        data_dir = tmp_path / "campaigns"
        data_dir.mkdir()
        c = _campaign_dict(total_return=0.15, max_drawdown=0.08, sharpe=1.5)
        (data_dir / "c.json").write_text(json.dumps(c), encoding="utf-8")
        suite = build_benchmark_suite(sorted(data_dir.glob("*.json")), "test", now_utc=_FIXED_NOW)
        out = tmp_path / "bench.json"
        save_benchmark(suite, out)
        return out

    def test_exit_0_on_valid_benchmark(self, tmp_path: Path) -> None:
        path = self._make_benchmark_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--benchmark-json", str(path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_exit_1_on_tampered_hash(self, tmp_path: Path) -> None:
        path = self._make_benchmark_file(tmp_path)
        d = json.loads(path.read_text())
        d["benchmark_hash"] = "0" * 64
        path.write_text(json.dumps(d), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--benchmark-json", str(path)])
        assert result.exit_code == 1

    def test_exit_2_on_malformed_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--benchmark-json", str(bad)])
        assert result.exit_code == 2

    def test_report_contains_advisory_disclaimer(self, tmp_path: Path) -> None:
        path = self._make_benchmark_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--benchmark-json", str(path)])
        data = json.loads(result.output)
        assert "advisory_disclaimer" in data
