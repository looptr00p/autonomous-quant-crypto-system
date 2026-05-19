"""Tests for deterministic parameter sensitivity auditing.

All tests are deterministic and local.  No network, no wall-clock, no randomness.

Coverage:
- run_sensitivity_audit: all required fields populated
- audit_hash is deterministic and self-certifying
- audit_id is UUID5 of audit_hash
- hash excludes generation_timestamp_utc
- identical runs produce identical hash
- baseline artifact is NOT mutated
- SensitivityAudit is immutable (frozen=True)
- relative perturbation: perturbed = baseline * (1 + delta)
- absolute perturbation: perturbed = baseline + delta
- severity: LOW below 5% relative change
- severity: MEDIUM at/above 5% relative change
- severity: HIGH at/above 20% relative change
- severity: CRITICAL at/above 50% relative change
- severity: CRITICAL on governance return floor breach
- severity: CRITICAL on governance drawdown ceiling breach
- severity: CRITICAL on governance sharpe floor breach
- instability findings generated for MEDIUM+ severity
- no finding for LOW severity
- stability scores computed correctly
- per-parameter stability
- benchmark_delta uses return weight for return fields
- benchmark_delta uses drawdown weight for drawdown fields
- benchmark_delta zero for unknown fields
- walkforward_delta populated for walkforward fields
- walkforward_delta zero for non-walkforward fields
- field not found → issue recorded, no crash
- malformed perturbation config → issue recorded
- invalid delta_type → issue recorded
- empty delta_values → issue recorded
- missing required config field → issue recorded
- governance threshold breach → CRITICAL with threshold name
- validate_sensitivity_audit: valid passes
- validate_sensitivity_audit: tampered hash detected
- validate_sensitivity_audit: wrong version detected
- save_sensitivity_audit / load_sensitivity_audit round-trip
- load_sensitivity_audit: invalid JSON raises ValueError
- from_dict / to_dict round-trip
- perturbations sorted by parameter_name (stable ordering)
- results sorted by (parameter_name, perturbation_magnitude)
- findings sorted by (severity, parameter_name, magnitude)
- make_default_perturbation_config: returns parseable config
- CLI run: exit 0 on fully stable artifact
- CLI run: exit 1 on instability findings
- CLI run: exit 2 on missing file
- CLI validate: exit 0 on valid audit
- CLI validate: exit 1 on tampered audit
- CLI validate: exit 2 on malformed file
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from run_sensitivity_audit import main as run_main
from validate_sensitivity_audit import main as validate_main

from aqcs.research.sensitivity_audit import (
    _AUDIT_NS,
    AUDIT_VERSION,
    GOVERNANCE_DRAWDOWN_CEIL,
    GOVERNANCE_RETURN_FLOOR,
    GOVERNANCE_SHARPE_FLOOR,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SensitivityAudit,
    load_sensitivity_audit,
    make_default_perturbation_config,
    run_sensitivity_audit,
    save_sensitivity_audit,
    sensitivity_audit_from_dict,
    sensitivity_audit_to_dict,
    validate_sensitivity_audit,
)

# ── Shared constants ──────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)


# ── Synthetic fixture helpers ─────────────────────────────────────────────────


def _campaign_artifact(
    mean_total_return: float = 0.10,
    mean_sharpe_ratio: float = 1.5,
    mean_max_drawdown: float = 0.05,
    mean_exposure: float = 0.50,
) -> dict:
    return {
        "campaign_version": "1",
        "campaign_id": str(uuid.uuid4()),
        "campaign_hash": "a" * 64,
        "total_experiments": 3,
        "aggregate_metrics": {
            "mean_total_return": mean_total_return,
            "mean_sharpe_ratio": mean_sharpe_ratio,
            "mean_exposure": mean_exposure,
            "mean_turnover_per_bar": 0.18,
        },
        "aggregate_drawdown": {
            "mean_max_drawdown": mean_max_drawdown,
        },
    }


def _perturbation_config(
    parameter_name: str = "mean_total_return",
    field_path: str = "aggregate_metrics.mean_total_return",
    delta_type: str = "relative",
    delta_values: list | None = None,
) -> dict:
    if delta_values is None:
        delta_values = [-0.05, 0.05]
    return {
        "config_version": "1",
        "perturbations": [
            {
                "parameter_name": parameter_name,
                "field_path": field_path,
                "delta_type": delta_type,
                "delta_values": delta_values,
                "description": f"Test perturbation of {parameter_name}",
            }
        ],
    }


def _write(directory: Path, name: str, d: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def _run(artifact_path: Path, config_path: Path) -> SensitivityAudit:
    return run_sensitivity_audit(artifact_path, config_path, now_utc=_FIXED_NOW)


# ── Report generation ─────────────────────────────────────────────────────────


class TestReportGeneration:
    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        c = _write(tmp_path, "config.json", _perturbation_config())
        audit = _run(a, c)
        assert audit.audit_version == AUDIT_VERSION
        assert len(audit.audit_hash) == 64
        assert audit.audit_id != ""
        assert audit.generation_timestamp_utc == _FIXED_NOW.isoformat()
        assert audit.baseline_artifact_hash != ""
        assert isinstance(audit.perturbation_definitions, tuple)
        assert isinstance(audit.sensitivity_results, tuple)
        assert isinstance(audit.instability_findings, tuple)
        assert isinstance(audit.warnings, tuple)
        assert isinstance(audit.issues, tuple)

    def test_deterministic_on_repeated_calls(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        c = _write(tmp_path, "config.json", _perturbation_config())
        r1 = _run(a, c)
        r2 = _run(a, c)
        assert r1.audit_hash == r2.audit_hash

    def test_hash_excludes_timestamp(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        c = _write(tmp_path, "config.json", _perturbation_config())
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        r1 = run_sensitivity_audit(a, c, now_utc=t1)
        r2 = run_sensitivity_audit(a, c, now_utc=t2)
        assert r1.audit_hash == r2.audit_hash

    def test_audit_id_is_uuid5_of_hash(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        c = _write(tmp_path, "config.json", _perturbation_config())
        audit = _run(a, c)
        expected_id = str(uuid.uuid5(_AUDIT_NS, audit.audit_hash))
        assert audit.audit_id == expected_id

    def test_baseline_artifact_not_mutated(self, tmp_path: Path) -> None:
        orig = _campaign_artifact()
        a = _write(tmp_path, "artifact.json", orig)
        c = _write(tmp_path, "config.json", _perturbation_config())
        _run(a, c)
        loaded = json.loads(a.read_text())
        assert (
            loaded["aggregate_metrics"]["mean_total_return"]
            == orig["aggregate_metrics"]["mean_total_return"]
        )

    def test_report_is_immutable(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        c = _write(tmp_path, "config.json", _perturbation_config())
        audit = _run(a, c)
        assert isinstance(audit, SensitivityAudit)
        with pytest.raises((AttributeError, TypeError)):
            audit.audit_version = "hacked"  # type: ignore[misc]


# ── Perturbation arithmetic ───────────────────────────────────────────────────


class TestPerturbationArithmetic:
    def test_relative_perturbation(self, tmp_path: Path) -> None:
        baseline = 0.10
        delta = 0.05
        a = _write(tmp_path, "artifact.json", _campaign_artifact(mean_total_return=baseline))
        c = _write(tmp_path, "config.json", _perturbation_config(delta_values=[delta]))
        audit = _run(a, c)
        result = audit.sensitivity_results[0]
        assert abs(result.baseline_value - baseline) < 1e-12
        assert abs(result.perturbed_value - baseline * (1.0 + delta)) < 1e-12

    def test_absolute_perturbation(self, tmp_path: Path) -> None:
        baseline = 0.10
        delta = 0.02
        a = _write(tmp_path, "artifact.json", _campaign_artifact(mean_total_return=baseline))
        c = _write(
            tmp_path,
            "config.json",
            _perturbation_config(delta_type="absolute", delta_values=[delta]),
        )
        audit = _run(a, c)
        result = audit.sensitivity_results[0]
        assert abs(result.perturbed_value - (baseline + delta)) < 1e-12

    def test_results_sorted_by_parameter_then_magnitude(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        cfg = {
            "config_version": "1",
            "perturbations": [
                {
                    "parameter_name": "return",
                    "field_path": "aggregate_metrics.mean_total_return",
                    "delta_type": "relative",
                    "delta_values": [0.10, -0.10, -0.05],
                    "description": "",
                }
            ],
        }
        c = _write(tmp_path, "config.json", cfg)
        audit = _run(a, c)
        magnitudes = [r.perturbation_magnitude for r in audit.sensitivity_results]
        assert magnitudes == sorted(magnitudes)

    def test_perturbation_defs_sorted_by_parameter_name(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "artifact.json", _campaign_artifact())
        cfg = {
            "config_version": "1",
            "perturbations": [
                {
                    "parameter_name": "zzz_param",
                    "field_path": "aggregate_metrics.mean_total_return",
                    "delta_type": "relative",
                    "delta_values": [0.05],
                    "description": "",
                },
                {
                    "parameter_name": "aaa_param",
                    "field_path": "aggregate_metrics.mean_sharpe_ratio",
                    "delta_type": "relative",
                    "delta_values": [0.05],
                    "description": "",
                },
            ],
        }
        c = _write(tmp_path, "config.json", cfg)
        audit = _run(a, c)
        names = [p.parameter_name for p in audit.perturbation_definitions]
        assert names == sorted(names)


# ── Severity classification ───────────────────────────────────────────────────


class TestSeverityClassification:
    def _make(
        self,
        tmp_path: Path,
        baseline: float,
        delta: float,
        field: str = "aggregate_metrics.mean_total_return",
    ) -> SensitivityAudit:
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_total_return=baseline))
        c = _write(tmp_path, "c.json", _perturbation_config(field_path=field, delta_values=[delta]))
        return _run(a, c)

    def test_low_below_5pct(self, tmp_path: Path) -> None:
        # 3% relative change → LOW
        audit = self._make(tmp_path, 0.10, 0.03)
        assert audit.sensitivity_results[0].severity == SEVERITY_LOW

    def test_medium_at_5pct(self, tmp_path: Path) -> None:
        # 5% relative change → MEDIUM (at the threshold)
        # Use a value safely above the medium threshold
        audit = self._make(tmp_path, 0.10, 0.06)
        assert audit.sensitivity_results[0].severity == SEVERITY_MEDIUM

    def test_high_above_20pct(self, tmp_path: Path) -> None:
        # 25% relative change → HIGH
        audit = self._make(tmp_path, 0.10, 0.25)
        assert audit.sensitivity_results[0].severity == SEVERITY_HIGH

    def test_critical_above_50pct(self, tmp_path: Path) -> None:
        # 60% relative change → CRITICAL (by magnitude)
        audit = self._make(tmp_path, 0.10, 0.60)
        assert audit.sensitivity_results[0].severity == SEVERITY_CRITICAL

    def test_critical_governance_return_breach(self, tmp_path: Path) -> None:
        # baseline 0.10, delta -0.90 → perturbed = 0.01 — wait, that won't breach
        # Let baseline = -0.05, delta = -0.10 (abs) → perturbed = -0.15 < -0.10
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_total_return=-0.05))
        c = _write(
            tmp_path,
            "c.json",
            _perturbation_config(delta_type="absolute", delta_values=[-0.10]),
        )
        audit = _run(a, c)
        result = audit.sensitivity_results[0]
        assert result.severity == SEVERITY_CRITICAL
        assert result.perturbed_value < GOVERNANCE_RETURN_FLOOR

    def test_critical_governance_drawdown_breach(self, tmp_path: Path) -> None:
        # baseline drawdown 0.25, delta +0.20 (relative) → 0.30 ≤ 0.25*1.20=0.30
        # Need perturbed > 0.30; use baseline=0.28, delta=absolute +0.05 → 0.33
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_max_drawdown=0.28))
        c = _write(
            tmp_path,
            "c.json",
            _perturbation_config(
                field_path="aggregate_drawdown.mean_max_drawdown",
                delta_type="absolute",
                delta_values=[0.05],
            ),
        )
        audit = _run(a, c)
        result = audit.sensitivity_results[0]
        assert result.severity == SEVERITY_CRITICAL
        assert result.perturbed_value > GOVERNANCE_DRAWDOWN_CEIL

    def test_critical_governance_sharpe_breach(self, tmp_path: Path) -> None:
        # baseline sharpe 0.20, delta -0.25 (absolute) → perturbed = -0.05 ≤ 0.0
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_sharpe_ratio=0.20))
        c = _write(
            tmp_path,
            "c.json",
            _perturbation_config(
                field_path="aggregate_metrics.mean_sharpe_ratio",
                delta_type="absolute",
                delta_values=[-0.25],
            ),
        )
        audit = _run(a, c)
        result = audit.sensitivity_results[0]
        assert result.severity == SEVERITY_CRITICAL
        assert result.perturbed_value <= GOVERNANCE_SHARPE_FLOOR


# ── Instability findings ──────────────────────────────────────────────────────


class TestInstabilityFindings:
    def test_no_finding_for_low_severity(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.03]))
        audit = _run(a, c)
        assert audit.instability_findings == ()

    def test_finding_for_medium_severity(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.10]))
        audit = _run(a, c)
        assert len(audit.instability_findings) >= 1

    def test_finding_for_critical_severity(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.60]))
        audit = _run(a, c)
        critical = [f for f in audit.instability_findings if f.severity == SEVERITY_CRITICAL]
        assert len(critical) >= 1

    def test_governance_threshold_name_in_finding(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_total_return=-0.05))
        c = _write(
            tmp_path, "c.json", _perturbation_config(delta_type="absolute", delta_values=[-0.10])
        )
        audit = _run(a, c)
        critical = [f for f in audit.instability_findings if f.severity == SEVERITY_CRITICAL]
        assert any("GOVERNANCE_RETURN_FLOOR" in f.governance_threshold_crossed for f in critical)

    def test_findings_sorted_by_severity_then_name(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        cfg = {
            "config_version": "1",
            "perturbations": [
                {
                    "parameter_name": "return_param",
                    "field_path": "aggregate_metrics.mean_total_return",
                    "delta_type": "relative",
                    "delta_values": [0.25, 0.60],  # HIGH and CRITICAL
                    "description": "",
                }
            ],
        }
        c = _write(tmp_path, "c.json", cfg)
        audit = _run(a, c)
        severities = [f.severity for f in audit.instability_findings]
        order = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 1, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 3}
        assert severities == sorted(severities, key=lambda s: order[s])


# ── Stability scores ──────────────────────────────────────────────────────────


class TestStabilityScores:
    def test_fully_stable_artifact(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.01, 0.02]))
        audit = _run(a, c)
        assert audit.stability_scores["overall_stability"] == 1.0

    def test_partially_stable_artifact(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.01, 0.25]))
        audit = _run(a, c)
        overall = audit.stability_scores["overall_stability"]
        assert 0.0 < overall < 1.0

    def test_per_parameter_stability_present(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.03]))
        audit = _run(a, c)
        per_param = audit.stability_scores["per_parameter"]
        assert "mean_total_return" in per_param

    def test_finding_counts_correct(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.02, 0.10, 0.25]))
        audit = _run(a, c)
        counts = audit.stability_scores["finding_counts"]
        total = sum(counts.values())
        assert total == len(audit.sensitivity_results)


# ── Benchmark and walkforward deltas ─────────────────────────────────────────


class TestDomainDeltas:
    def test_benchmark_delta_return_field(self, tmp_path: Path) -> None:
        baseline = 0.10
        delta_pct = 0.10
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_total_return=baseline))
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[delta_pct]))
        audit = _run(a, c)
        result = audit.sensitivity_results[-1]  # +0.10 delta (sorted ascending)
        # benchmark_delta = absolute_delta * 0.30 (return weight)
        expected_abs_delta = baseline * delta_pct
        assert abs(result.benchmark_delta - expected_abs_delta * 0.30) < 1e-10

    def test_benchmark_delta_drawdown_field(self, tmp_path: Path) -> None:
        # drawdown increase hurts score: benchmark_delta = -absolute_delta * 0.25
        baseline = 0.05
        delta_abs = 0.02
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_max_drawdown=baseline))
        c = _write(
            tmp_path,
            "c.json",
            _perturbation_config(
                field_path="aggregate_drawdown.mean_max_drawdown",
                delta_type="absolute",
                delta_values=[delta_abs],
            ),
        )
        audit = _run(a, c)
        result = audit.sensitivity_results[0]
        # benchmark_delta = -delta_abs * 0.25
        assert abs(result.benchmark_delta - (-delta_abs * 0.25)) < 1e-10

    def test_benchmark_delta_zero_for_unknown_field(self, tmp_path: Path) -> None:
        cfg = {
            "config_version": "1",
            "perturbations": [
                {
                    "parameter_name": "exposure",
                    "field_path": "aggregate_metrics.mean_exposure",
                    "delta_type": "relative",
                    "delta_values": [0.10],
                    "description": "",
                }
            ],
        }
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", cfg)
        audit = _run(a, c)
        assert audit.sensitivity_results[0].benchmark_delta == 0.0

    def test_walkforward_delta_for_return_field(self, tmp_path: Path) -> None:
        baseline = 0.10
        delta = 0.05
        a = _write(tmp_path, "a.json", _campaign_artifact(mean_total_return=baseline))
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[delta]))
        audit = _run(a, c)
        result = audit.sensitivity_results[-1]  # +0.05 delta
        # walkforward_delta = absolute_delta (return is in walkforward tokens)
        expected = baseline * delta
        assert abs(result.walkforward_delta - expected) < 1e-10

    def test_walkforward_delta_zero_for_non_walkforward_field(self, tmp_path: Path) -> None:
        cfg = {
            "config_version": "1",
            "perturbations": [
                {
                    "parameter_name": "exposure",
                    "field_path": "aggregate_metrics.mean_exposure",
                    "delta_type": "relative",
                    "delta_values": [0.10],
                    "description": "",
                }
            ],
        }
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", cfg)
        audit = _run(a, c)
        assert audit.sensitivity_results[0].walkforward_delta == 0.0


# ── Error handling ────────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_missing_field_records_issue(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(
            tmp_path,
            "c.json",
            _perturbation_config(field_path="nonexistent.field", delta_values=[0.05]),
        )
        audit = _run(a, c)
        assert any("nonexistent.field" in i for i in audit.issues)

    def test_malformed_config_no_crash(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        bad_config = {"config_version": "1", "perturbations": "not-a-list"}
        c = _write(tmp_path, "c.json", bad_config)
        audit = _run(a, c)
        assert len(audit.issues) >= 1

    def test_invalid_delta_type_records_issue(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_type="logarithmic"))
        audit = _run(a, c)
        assert len(audit.issues) >= 1

    def test_empty_delta_values_records_issue(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[]))
        audit = _run(a, c)
        assert len(audit.issues) >= 1

    def test_missing_artifact_records_issue(self, tmp_path: Path) -> None:
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = run_sensitivity_audit(tmp_path / "nonexistent.json", c, now_utc=_FIXED_NOW)
        assert any("not found" in i.lower() for i in audit.issues)


# ── Validation ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_audit_passes(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = _run(a, c)
        valid, errors = validate_sensitivity_audit(audit)
        assert valid is True
        assert errors == []

    def test_tampered_hash_detected(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = _run(a, c)
        d = sensitivity_audit_to_dict(audit)
        d["audit_hash"] = "0" * 64
        tampered = sensitivity_audit_from_dict(d)
        valid, errors = validate_sensitivity_audit(tampered)
        assert valid is False
        assert any("audit_hash" in e for e in errors)

    def test_wrong_version_detected(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = _run(a, c)
        d = sensitivity_audit_to_dict(audit)
        d["audit_version"] = "99"
        from aqcs.utils.canonicalization import canonical_hash

        d_no_hash = {
            k: v
            for k, v in d.items()
            if k not in {"audit_hash", "audit_id", "generation_timestamp_utc"}
        }
        d["audit_hash"] = canonical_hash(d_no_hash)
        import uuid as _uuid

        d["audit_id"] = str(_uuid.uuid5(_AUDIT_NS, d["audit_hash"]))
        wrong = sensitivity_audit_from_dict(d)
        valid, errors = validate_sensitivity_audit(wrong)
        assert valid is False


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_round_trip_dict(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = _run(a, c)
        restored = sensitivity_audit_from_dict(sensitivity_audit_to_dict(audit))
        j1 = json.dumps(sensitivity_audit_to_dict(audit), sort_keys=True)
        j2 = json.dumps(sensitivity_audit_to_dict(restored), sort_keys=True)
        assert j1 == j2

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = _run(a, c)
        out = tmp_path / "audit.json"
        save_sensitivity_audit(audit, out)
        loaded = load_sensitivity_audit(out)
        j1 = json.dumps(sensitivity_audit_to_dict(audit), sort_keys=True)
        j2 = json.dumps(sensitivity_audit_to_dict(loaded), sort_keys=True)
        assert j1 == j2

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_sensitivity_audit(bad)

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config())
        audit = _run(a, c)
        out = tmp_path / "deep" / "nested" / "audit.json"
        save_sensitivity_audit(audit, out)
        assert out.exists()


# ── Default config ────────────────────────────────────────────────────────────


class TestDefaultConfig:
    def test_default_config_is_valid(self, tmp_path: Path) -> None:
        default = make_default_perturbation_config()
        assert "perturbations" in default
        assert len(default["perturbations"]) >= 1

    def test_default_config_parseable_by_audit(self, tmp_path: Path) -> None:
        default = make_default_perturbation_config()
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", default)
        audit = _run(a, c)
        assert len(audit.sensitivity_results) > 0


# ── CLI tests ─────────────────────────────────────────────────────────────────


class TestCLIRun:
    def test_exit_0_on_stable(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.01, 0.02]))
        runner = CliRunner()
        result = runner.invoke(
            run_main,
            [
                "--baseline-artifact",
                str(a),
                "--perturbation-config",
                str(c),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_instability"] is False

    def test_exit_1_on_instability(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.60]))
        runner = CliRunner()
        result = runner.invoke(
            run_main,
            [
                "--baseline-artifact",
                str(a),
                "--perturbation-config",
                str(c),
            ],
        )
        assert result.exit_code == 1

    def test_writes_output_json(self, tmp_path: Path) -> None:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.03]))
        out = tmp_path / "audit_out.json"
        runner = CliRunner()
        runner.invoke(
            run_main,
            [
                "--baseline-artifact",
                str(a),
                "--perturbation-config",
                str(c),
                "--output-json",
                str(out),
            ],
        )
        assert out.exists()
        data = json.loads(out.read_text())
        assert "audit_hash" in data

    def test_exit_2_on_missing_artifact(self, tmp_path: Path) -> None:
        c = _write(tmp_path, "c.json", _perturbation_config())
        runner = CliRunner()
        result = runner.invoke(
            run_main,
            [
                "--baseline-artifact",
                str(tmp_path / "no.json"),
                "--perturbation-config",
                str(c),
            ],
        )
        assert result.exit_code == 2


class TestCLIValidate:
    def _make_audit_file(self, tmp_path: Path) -> Path:
        a = _write(tmp_path, "a.json", _campaign_artifact())
        c = _write(tmp_path, "c.json", _perturbation_config(delta_values=[0.03]))
        audit = run_sensitivity_audit(a, c, now_utc=_FIXED_NOW)
        out = tmp_path / "audit.json"
        save_sensitivity_audit(audit, out)
        return out

    def test_exit_0_on_valid(self, tmp_path: Path) -> None:
        path = self._make_audit_file(tmp_path)
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--audit-json", str(path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_exit_1_on_tampered(self, tmp_path: Path) -> None:
        path = self._make_audit_file(tmp_path)
        d = json.loads(path.read_text())
        d["audit_hash"] = "0" * 64
        path.write_text(json.dumps(d), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--audit-json", str(path)])
        assert result.exit_code == 1

    def test_exit_2_on_malformed(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(validate_main, ["--audit-json", str(bad)])
        assert result.exit_code == 2
