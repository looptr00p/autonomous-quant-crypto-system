"""Deterministic parameter sensitivity auditing for AQCS research experiments.

A SensitivityAudit is an immutable, self-certifying report that evaluates
whether research results remain stable under controlled, explicit parameter
perturbations.

The audit answers: "If an artifact's reported metric were X% different, would
it still satisfy governance bounds?  How stable is the strategy to small
variations in its own reported values?"

The audit provides:
  - deterministic perturbation evaluation
  - metric stability scoring per parameter
  - benchmark impact approximations
  - walk-forward impact approximations
  - instability severity classification
  - governance threshold breach detection
  - self-certifying audit_hash

Safety and scope
----------------
This module NEVER:
  - performs parameter optimization or search
  - runs adaptive perturbation selection
  - mutates baseline artifacts
  - selects or recommends strategy parameters
  - makes autonomous governance decisions
  - applies ML/RL scoring
  - re-runs backtests

All perturbations are explicitly defined in the perturbation config.
All thresholds are explicit module-level constants.
Any change to thresholds requires an ADR and human approval.

Perturbation model
------------------
Each ``PerturbationDefinition`` specifies:
  - a field to stress-test (``field_path`` in dot notation)
  - a delta type (``"relative"`` or ``"absolute"``)
  - an explicit list of delta magnitudes to apply

For relative perturbations: ``perturbed = baseline * (1.0 + delta)``
For absolute perturbations:  ``perturbed = baseline + delta``

Governance threshold breaches are CRITICAL regardless of delta magnitude.

Determinism
-----------
- Perturbation traversal uses ``sorted()`` on ``(parameter_name, delta_value)``.
- ``audit_hash`` is ``canonical_hash(content_dict)`` excluding itself and
  ``generation_timestamp_utc``.
- ``audit_id`` is UUID5 derived from ``audit_hash``.
- NaN values are normalized to ``None`` before serialization.
- ``now_utc`` is injectable for fully deterministic test output.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqcs.research.governance_thresholds import (
    DRAWDOWN_CEIL,
    RETURN_FLOOR,
    SCORE_WEIGHT_DRAWDOWN,
    SCORE_WEIGHT_RETURN,
    SCORE_WEIGHT_SHARPE,
    SHARPE_FLOOR,
)
from aqcs.utils.canonicalization import canonical_hash, normalize_nan, sha256_hex

# ── Version ───────────────────────────────────────────────────────────────────

AUDIT_VERSION: str = "1"

# Fixed UUID5 namespace for deterministic audit_id derivation.
_AUDIT_NS: uuid.UUID = uuid.UUID("d4e5f6a7-b8c9-0123-4567-89abcdef0123")

# ── Severity levels ───────────────────────────────────────────────────────────
# Instability-magnitude classification: four levels of severity for perturbation
# results.  This is a distinct system from regression_guard's three-level
# comparison-severity system ("critical"/"warning"/"info").  See
# docs/governance/governance_constants.md for the distinction.

SEVERITY_LOW: str = "LOW"
SEVERITY_MEDIUM: str = "MEDIUM"
SEVERITY_HIGH: str = "HIGH"
SEVERITY_CRITICAL: str = "CRITICAL"

# ── Instability thresholds — explicit constants, require ADR to change ─────────
# Severity is based on the absolute relative change: |perturbed - baseline| / |baseline|.
# A governance threshold breach always produces CRITICAL regardless of magnitude.

INSTABILITY_LOW_THRESHOLD: float = 0.05  # 5% relative change → LOW
INSTABILITY_MEDIUM_THRESHOLD: float = 0.20  # 20% relative change → MEDIUM
INSTABILITY_HIGH_THRESHOLD: float = 0.50  # 50% relative change → HIGH
# Above HIGH_THRESHOLD → CRITICAL (by magnitude alone)

# ── Governance thresholds — sourced from governance_thresholds (single source of truth)
# Crossing these in the perturbed value produces a CRITICAL severity finding.
# Any change requires an ADR and human approval.

GOVERNANCE_RETURN_FLOOR: float = RETURN_FLOOR  # total_return / mean_total_return floor
GOVERNANCE_DRAWDOWN_CEIL: float = DRAWDOWN_CEIL  # max_drawdown / mean_max_drawdown ceiling
GOVERNANCE_SHARPE_FLOOR: float = SHARPE_FLOOR  # sharpe_ratio / mean_sharpe_ratio floor

# ── Benchmark score weight approximations ─────────────────────────────────────
# Used for benchmark_delta computation.  Sourced from governance_thresholds
# (single source of truth) — no longer need to manually stay in sync.

_BENCH_WEIGHT_RETURN: float = SCORE_WEIGHT_RETURN
_BENCH_WEIGHT_DRAWDOWN: float = SCORE_WEIGHT_DRAWDOWN
_BENCH_WEIGHT_SHARPE: float = SCORE_WEIGHT_SHARPE

# ── Known metric field path categories ───────────────────────────────────────
# Used to determine which governance threshold applies and benchmark weight.

_RETURN_FIELD_TOKENS: frozenset[str] = frozenset(
    {"total_return", "mean_total_return", "cagr", "excess_return"}
)
_DRAWDOWN_FIELD_TOKENS: frozenset[str] = frozenset({"max_drawdown", "mean_max_drawdown"})
_SHARPE_FIELD_TOKENS: frozenset[str] = frozenset({"sharpe_ratio", "mean_sharpe_ratio"})
_WALKFORWARD_FIELD_TOKENS: frozenset[str] = frozenset(
    {
        "mean_total_return",
        "mean_max_drawdown",
        "mean_sharpe_ratio",
        "train_bars",
        "step_bars",
        "n_windows",
    }
)


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PerturbationDefinition:
    """Explicit, deterministic specification of a single parameter perturbation.

    ``field_path`` uses dot notation to locate a numeric field in the baseline
    artifact JSON (e.g. ``"aggregate_metrics.mean_total_return"``).

    ``delta_type`` is either ``"relative"`` or ``"absolute"``.
      - relative: ``perturbed = baseline * (1.0 + delta_value)``
      - absolute: ``perturbed = baseline + delta_value``

    ``delta_values`` is an explicit, frozen tuple of magnitudes to apply.
    No adaptive selection — these values are defined by the human author of
    the perturbation config.
    """

    parameter_name: str
    field_path: str
    delta_type: str
    delta_values: tuple[float, ...]
    description: str


@dataclass(frozen=True)
class SensitivityResult:
    """Result of applying one specific delta to one perturbation definition.

    ``baseline_value``   — numeric value from the baseline artifact.
    ``perturbed_value``  — value after applying the perturbation.
    ``perturbation_magnitude`` — the delta that was applied (signed).
    ``metric_deltas``    — dict with ``{field_path: {baseline, perturbed, ...}}``.
    ``benchmark_delta``  — approximate change in benchmark score contribution.
    ``walkforward_delta``— absolute change in walkforward-relevant metric.
    ``severity``         — one of CRITICAL / HIGH / MEDIUM / LOW.
    ``deterministic_diff_summary`` — human-readable description.
    """

    parameter_name: str
    baseline_value: float
    perturbed_value: float
    perturbation_magnitude: float
    metric_deltas: dict[str, Any]
    benchmark_delta: float
    walkforward_delta: float
    severity: str
    deterministic_diff_summary: str


@dataclass(frozen=True)
class InstabilityFinding:
    """A single classified instability observation.

    Generated for each SensitivityResult with severity ≥ MEDIUM or a
    governance threshold crossing.
    """

    parameter_name: str
    severity: str
    perturbation_magnitude: float
    baseline_value: float
    perturbed_value: float
    governance_threshold_crossed: str  # empty string if none
    deterministic_diff_summary: str


@dataclass(frozen=True)
class SensitivityAudit:
    """Immutable self-certifying sensitivity audit report.

    ``audit_hash`` is SHA-256 of the report content excluding itself and
    ``generation_timestamp_utc``.  ``audit_id`` is UUID5 of ``audit_hash``.

    The report is advisory only.  Findings do not authorize automated
    parameter changes, artifact modifications, or strategy mutations.
    """

    audit_version: str
    audit_id: str
    generation_timestamp_utc: str
    audit_hash: str
    baseline_artifact_hash: str
    perturbation_definitions: tuple[PerturbationDefinition, ...]
    sensitivity_results: tuple[SensitivityResult, ...]
    benchmark_impacts: dict[str, Any]
    walkforward_impacts: dict[str, Any]
    stability_scores: dict[str, Any]
    instability_findings: tuple[InstabilityFinding, ...]
    warnings: tuple[str, ...]
    issues: tuple[str, ...]


# ── Public API ────────────────────────────────────────────────────────────────


def run_sensitivity_audit(
    baseline_artifact: Path,
    perturbation_config: Path,
    *,
    now_utc: datetime | None = None,
) -> SensitivityAudit:
    """Evaluate parameter sensitivity of a research artifact.

    Args:
        baseline_artifact: Path to the baseline JSON artifact.
        perturbation_config: Path to the perturbation config JSON.
        now_utc: Reference UTC time; defaults to ``datetime.now(UTC)``.
            Inject a fixed value in tests for deterministic output.

    Returns:
        Immutable, self-certifying ``SensitivityAudit``.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)
    issues: list[str] = []
    warnings: list[str] = []

    # ── 1. Load baseline artifact ──────────────────────────────────────────────
    baseline_dict, artifact_raw = _load_json_file(
        Path(baseline_artifact), "baseline artifact", issues
    )
    baseline_artifact_hash = sha256_hex(artifact_raw) if artifact_raw else ""

    # ── 2. Load perturbation config ────────────────────────────────────────────
    config_dict, _ = _load_json_file(Path(perturbation_config), "perturbation config", issues)
    perturbation_defs = _parse_perturbation_config(config_dict, issues)

    # ── 3. Apply perturbations ─────────────────────────────────────────────────
    all_results: list[SensitivityResult] = []
    all_findings: list[InstabilityFinding] = []

    for pdef in sorted(perturbation_defs, key=lambda p: p.parameter_name):
        baseline_value = _resolve_field(baseline_dict, pdef.field_path, warnings)
        if baseline_value is None:
            issues.append(
                f"Field '{pdef.field_path}' not found in baseline artifact "
                f"for parameter '{pdef.parameter_name}'"
            )
            continue

        for delta in sorted(pdef.delta_values):
            result = _apply_perturbation(pdef, baseline_value, delta)
            all_results.append(result)
            if result.severity in (SEVERITY_MEDIUM, SEVERITY_HIGH, SEVERITY_CRITICAL):
                all_findings.append(
                    InstabilityFinding(
                        parameter_name=result.parameter_name,
                        severity=result.severity,
                        perturbation_magnitude=delta,
                        baseline_value=result.baseline_value,
                        perturbed_value=result.perturbed_value,
                        governance_threshold_crossed=_governance_threshold_name(
                            pdef.field_path, result.perturbed_value
                        ),
                        deterministic_diff_summary=result.deterministic_diff_summary,
                    )
                )

    # ── 4. Sort results deterministically ─────────────────────────────────────
    results_sorted = tuple(
        sorted(all_results, key=lambda r: (r.parameter_name, r.perturbation_magnitude))
    )
    findings_sorted = tuple(
        sorted(
            all_findings,
            key=lambda f: (f.severity, f.parameter_name, f.perturbation_magnitude),
        )
    )

    # ── 5. Compute aggregate analyses ─────────────────────────────────────────
    benchmark_impacts = _compute_benchmark_impacts(results_sorted)
    walkforward_impacts = _compute_walkforward_impacts(results_sorted, perturbation_defs)
    stability_scores = _compute_stability_scores(results_sorted, perturbation_defs)

    # ── 6. Build content dict for hashing ─────────────────────────────────────
    content_dict: dict[str, Any] = {
        "audit_version": AUDIT_VERSION,
        "baseline_artifact_hash": baseline_artifact_hash,
        "perturbation_definitions": [
            _pdef_to_dict(p) for p in sorted(perturbation_defs, key=lambda p: p.parameter_name)
        ],
        "sensitivity_results": [_result_to_dict(r) for r in results_sorted],
        "benchmark_impacts": normalize_nan(benchmark_impacts),
        "walkforward_impacts": normalize_nan(walkforward_impacts),
        "stability_scores": normalize_nan(stability_scores),
        "instability_findings": [_finding_to_dict(f) for f in findings_sorted],
        "instability_thresholds": {
            "low": INSTABILITY_LOW_THRESHOLD,
            "medium": INSTABILITY_MEDIUM_THRESHOLD,
            "high": INSTABILITY_HIGH_THRESHOLD,
        },
        "governance_thresholds": {
            "return_floor": GOVERNANCE_RETURN_FLOOR,
            "drawdown_ceil": GOVERNANCE_DRAWDOWN_CEIL,
            "sharpe_floor": GOVERNANCE_SHARPE_FLOOR,
        },
        "issues": sorted(issues),
        "warnings": sorted(warnings),
    }

    audit_hash = canonical_hash(content_dict)
    audit_id = str(uuid.uuid5(_AUDIT_NS, audit_hash))

    return SensitivityAudit(
        audit_version=AUDIT_VERSION,
        audit_id=audit_id,
        generation_timestamp_utc=_now.isoformat(),
        audit_hash=audit_hash,
        baseline_artifact_hash=baseline_artifact_hash,
        perturbation_definitions=tuple(sorted(perturbation_defs, key=lambda p: p.parameter_name)),
        sensitivity_results=results_sorted,
        benchmark_impacts=benchmark_impacts,
        walkforward_impacts=walkforward_impacts,
        stability_scores=stability_scores,
        instability_findings=findings_sorted,
        warnings=tuple(sorted(warnings)),
        issues=tuple(sorted(issues)),
    )


def validate_sensitivity_audit(audit: SensitivityAudit) -> tuple[bool, list[str]]:
    """Validate a sensitivity audit's self-certifying hash and consistency.

    Returns:
        ``(is_valid, errors)`` — errors is empty when valid.
    """
    errors: list[str] = []

    d = sensitivity_audit_to_dict(audit)
    d_no_hash = {
        k: v
        for k, v in d.items()
        if k not in {"audit_hash", "audit_id", "generation_timestamp_utc"}
    }
    expected = canonical_hash(d_no_hash)
    if expected != audit.audit_hash:
        errors.append(
            f"audit_hash mismatch: stored={audit.audit_hash[:16]}… " f"recomputed={expected[:16]}…"
        )

    expected_id = str(uuid.uuid5(_AUDIT_NS, audit.audit_hash))
    if expected_id != audit.audit_id:
        errors.append(f"audit_id mismatch: stored={audit.audit_id} recomputed={expected_id}")

    if audit.audit_version != AUDIT_VERSION:
        errors.append(f"audit_version '{audit.audit_version}' != current '{AUDIT_VERSION}'")

    return len(errors) == 0, errors


def sensitivity_audit_to_dict(audit: SensitivityAudit) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``SensitivityAudit``."""
    return {
        "audit_version": audit.audit_version,
        "audit_id": audit.audit_id,
        "generation_timestamp_utc": audit.generation_timestamp_utc,
        "audit_hash": audit.audit_hash,
        "baseline_artifact_hash": audit.baseline_artifact_hash,
        "perturbation_definitions": [_pdef_to_dict(p) for p in audit.perturbation_definitions],
        "sensitivity_results": [_result_to_dict(r) for r in audit.sensitivity_results],
        "benchmark_impacts": dict(audit.benchmark_impacts),
        "walkforward_impacts": dict(audit.walkforward_impacts),
        "stability_scores": dict(audit.stability_scores),
        "instability_findings": [_finding_to_dict(f) for f in audit.instability_findings],
        "instability_thresholds": {
            "low": INSTABILITY_LOW_THRESHOLD,
            "medium": INSTABILITY_MEDIUM_THRESHOLD,
            "high": INSTABILITY_HIGH_THRESHOLD,
        },
        "governance_thresholds": {
            "return_floor": GOVERNANCE_RETURN_FLOOR,
            "drawdown_ceil": GOVERNANCE_DRAWDOWN_CEIL,
            "sharpe_floor": GOVERNANCE_SHARPE_FLOOR,
        },
        "warnings": list(audit.warnings),
        "issues": list(audit.issues),
    }


def sensitivity_audit_from_dict(d: dict[str, Any]) -> SensitivityAudit:
    """Reconstruct a ``SensitivityAudit`` from a dict.

    Raises:
        KeyError: If any required field is missing.
    """
    pdefs = tuple(
        PerturbationDefinition(
            parameter_name=str(p["parameter_name"]),
            field_path=str(p["field_path"]),
            delta_type=str(p["delta_type"]),
            delta_values=tuple(float(v) for v in p["delta_values"]),
            description=str(p["description"]),
        )
        for p in d["perturbation_definitions"]
    )

    def _flt(v: Any, default: float) -> float:
        return default if v is None else float(v)

    results = tuple(
        SensitivityResult(
            parameter_name=str(r["parameter_name"]),
            baseline_value=_flt(r["baseline_value"], float("nan")),
            perturbed_value=_flt(r["perturbed_value"], float("nan")),
            perturbation_magnitude=float(r["perturbation_magnitude"]),
            metric_deltas=dict(r["metric_deltas"]),
            benchmark_delta=_flt(r["benchmark_delta"], 0.0),
            walkforward_delta=_flt(r["walkforward_delta"], 0.0),
            severity=str(r["severity"]),
            deterministic_diff_summary=str(r["deterministic_diff_summary"]),
        )
        for r in d["sensitivity_results"]
    )
    findings = tuple(
        InstabilityFinding(
            parameter_name=str(f["parameter_name"]),
            severity=str(f["severity"]),
            perturbation_magnitude=float(f["perturbation_magnitude"]),
            baseline_value=_flt(f["baseline_value"], float("nan")),
            perturbed_value=_flt(f["perturbed_value"], float("nan")),
            governance_threshold_crossed=str(f["governance_threshold_crossed"]),
            deterministic_diff_summary=str(f["deterministic_diff_summary"]),
        )
        for f in d["instability_findings"]
    )
    return SensitivityAudit(
        audit_version=str(d["audit_version"]),
        audit_id=str(d["audit_id"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        audit_hash=str(d["audit_hash"]),
        baseline_artifact_hash=str(d["baseline_artifact_hash"]),
        perturbation_definitions=pdefs,
        sensitivity_results=results,
        benchmark_impacts=dict(d["benchmark_impacts"]),
        walkforward_impacts=dict(d["walkforward_impacts"]),
        stability_scores=dict(d["stability_scores"]),
        instability_findings=findings,
        warnings=tuple(str(w) for w in d["warnings"]),
        issues=tuple(str(i) for i in d["issues"]),
    )


def save_sensitivity_audit(audit: SensitivityAudit, path: Path) -> None:
    """Write a sensitivity audit to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sensitivity_audit_to_dict(audit), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_sensitivity_audit(path: Path) -> SensitivityAudit:
    """Load a sensitivity audit from a JSON file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in sensitivity audit '{path}': {exc}") from exc
    try:
        return sensitivity_audit_from_dict(raw)
    except KeyError as exc:
        raise ValueError(f"Missing required field in sensitivity audit '{path}': {exc}") from exc


def make_default_perturbation_config() -> dict[str, Any]:
    """Return a default perturbation config dict for campaign-type artifacts.

    Perturbs the six governance-relevant metrics at ±5%, ±10%, and ±20%.
    This config is suitable as a starting point; auditors should customize
    delta_values and field_paths for their specific artifact schema.
    """
    standard_deltas = (-0.20, -0.10, -0.05, 0.05, 0.10, 0.20)
    adverse_deltas = (0.05, 0.10, 0.20)  # for drawdown (adverse direction only)
    return {
        "config_version": "1",
        "description": "Default AQCS sensitivity perturbation config for campaign artifacts.",
        "perturbations": [
            {
                "parameter_name": "mean_total_return",
                "field_path": "aggregate_metrics.mean_total_return",
                "delta_type": "relative",
                "delta_values": list(standard_deltas),
                "description": "Relative stress test of mean_total_return",
            },
            {
                "parameter_name": "mean_sharpe_ratio",
                "field_path": "aggregate_metrics.mean_sharpe_ratio",
                "delta_type": "relative",
                "delta_values": list(standard_deltas),
                "description": "Relative stress test of mean_sharpe_ratio",
            },
            {
                "parameter_name": "mean_max_drawdown",
                "field_path": "aggregate_drawdown.mean_max_drawdown",
                "delta_type": "relative",
                "delta_values": list(adverse_deltas),
                "description": "Relative stress test of mean_max_drawdown (adverse only)",
            },
            {
                "parameter_name": "mean_exposure",
                "field_path": "aggregate_metrics.mean_exposure",
                "delta_type": "relative",
                "delta_values": list(standard_deltas),
                "description": "Relative stress test of mean_exposure",
            },
        ],
    }


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_json_file(
    path: Path,
    label: str,
    issues: list[str],
) -> tuple[dict[str, Any], bytes]:
    """Load and parse a JSON file.  Returns (dict, raw_bytes) or ({}, b'') on error."""
    if not path.exists():
        issues.append(f"{label} file not found: '{path}'")
        return {}, b""
    try:
        raw = path.read_bytes()
        return json.loads(raw), raw
    except json.JSONDecodeError as exc:
        issues.append(f"Cannot parse {label} JSON '{path}': {exc}")
        return {}, b""
    except OSError as exc:
        issues.append(f"Cannot read {label} '{path}': {exc}")
        return {}, b""


def _parse_perturbation_config(
    config: dict[str, Any],
    issues: list[str],
) -> list[PerturbationDefinition]:
    """Parse a perturbation config dict into PerturbationDefinition objects."""
    raw_perturbations = config.get("perturbations", [])
    if not isinstance(raw_perturbations, list):
        issues.append("perturbation config 'perturbations' must be a list")
        return []

    defs: list[PerturbationDefinition] = []
    for i, item in enumerate(raw_perturbations):
        if not isinstance(item, dict):
            issues.append(f"perturbation[{i}]: must be an object")
            continue
        try:
            delta_type = str(item.get("delta_type", "relative"))
            if delta_type not in ("relative", "absolute"):
                issues.append(
                    f"perturbation[{i}] '{item.get('parameter_name', '?')}': "
                    f"delta_type must be 'relative' or 'absolute', got '{delta_type}'"
                )
                continue
            raw_deltas = item.get("delta_values", [])
            if not isinstance(raw_deltas, list) or len(raw_deltas) == 0:
                issues.append(
                    f"perturbation[{i}] '{item.get('parameter_name', '?')}': "
                    "delta_values must be a non-empty list"
                )
                continue
            delta_values = tuple(float(v) for v in raw_deltas)
            defs.append(
                PerturbationDefinition(
                    parameter_name=str(item["parameter_name"]),
                    field_path=str(item["field_path"]),
                    delta_type=delta_type,
                    delta_values=delta_values,
                    description=str(item.get("description", "")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(f"perturbation[{i}]: invalid definition — {exc}")

    return defs


def _resolve_field(
    artifact: dict[str, Any],
    field_path: str,
    warnings: list[str],
) -> float | None:
    """Resolve a dotted field path in an artifact dict.

    Returns the numeric value, or None if the field is absent or non-numeric.
    """
    parts = field_path.split(".")
    current: Any = artifact
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            warnings.append(f"Field '{field_path}' not found in artifact")
            return None
        current = current[part]

    if current is None:
        return None
    try:
        val = float(current)
        return None if math.isnan(val) else val
    except (TypeError, ValueError):
        warnings.append(f"Field '{field_path}' is not numeric: {current!r}")
        return None


def _apply_perturbation(
    pdef: PerturbationDefinition,
    baseline_value: float,
    delta: float,
) -> SensitivityResult:
    """Apply one delta to one baseline value and return a SensitivityResult."""
    if pdef.delta_type == "relative":
        perturbed_value = baseline_value * (1.0 + delta)
    else:
        perturbed_value = baseline_value + delta

    absolute_delta = perturbed_value - baseline_value
    if baseline_value != 0.0 and not math.isnan(baseline_value):
        relative_delta = absolute_delta / abs(baseline_value)
    else:
        relative_delta = 0.0

    severity = _classify_severity(pdef.field_path, perturbed_value, relative_delta)
    benchmark_delta = _compute_benchmark_delta(pdef.field_path, absolute_delta)
    walkforward_delta = _compute_walkforward_delta(pdef.field_path, absolute_delta)

    summary = (
        f"'{pdef.parameter_name}' ({pdef.field_path}): "
        f"baseline={baseline_value:.6f} "
        f"perturbed={perturbed_value:.6f} "
        f"delta={delta:+.1%} ({pdef.delta_type}) "
        f"rel_change={relative_delta:+.1%} → {severity}"
    )

    metric_deltas: dict[str, Any] = {
        pdef.field_path: {
            "baseline": baseline_value if not math.isnan(baseline_value) else None,
            "perturbed": perturbed_value if not math.isnan(perturbed_value) else None,
            "absolute_delta": absolute_delta if not (math.isnan(absolute_delta)) else None,
            "relative_delta": relative_delta if not math.isnan(relative_delta) else None,
        }
    }

    return SensitivityResult(
        parameter_name=pdef.parameter_name,
        baseline_value=baseline_value,
        perturbed_value=perturbed_value,
        perturbation_magnitude=delta,
        metric_deltas=metric_deltas,
        benchmark_delta=benchmark_delta,
        walkforward_delta=walkforward_delta,
        severity=severity,
        deterministic_diff_summary=summary,
    )


def _classify_severity(field_path: str, perturbed_value: float, relative_delta: float) -> str:
    """Classify instability severity for a perturbation result.

    Governance threshold crossing always produces CRITICAL.
    Otherwise, magnitude-based classification is applied.
    """
    token = _last_field_token(field_path)

    # Governance breach check — CRITICAL regardless of magnitude
    if token in _RETURN_FIELD_TOKENS and perturbed_value < GOVERNANCE_RETURN_FLOOR:
        return SEVERITY_CRITICAL
    if token in _DRAWDOWN_FIELD_TOKENS and perturbed_value > GOVERNANCE_DRAWDOWN_CEIL:
        return SEVERITY_CRITICAL
    if token in _SHARPE_FIELD_TOKENS and perturbed_value <= GOVERNANCE_SHARPE_FLOOR:
        return SEVERITY_CRITICAL

    # Magnitude-based classification
    abs_rel = abs(relative_delta)
    if abs_rel >= INSTABILITY_HIGH_THRESHOLD:
        return SEVERITY_CRITICAL
    if abs_rel >= INSTABILITY_MEDIUM_THRESHOLD:
        return SEVERITY_HIGH
    if abs_rel >= INSTABILITY_LOW_THRESHOLD:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def _governance_threshold_name(field_path: str, perturbed_value: float) -> str:
    """Return the name of the governance threshold crossed, or empty string."""
    token = _last_field_token(field_path)
    if token in _RETURN_FIELD_TOKENS and perturbed_value < GOVERNANCE_RETURN_FLOOR:
        return f"GOVERNANCE_RETURN_FLOOR ({GOVERNANCE_RETURN_FLOOR})"
    if token in _DRAWDOWN_FIELD_TOKENS and perturbed_value > GOVERNANCE_DRAWDOWN_CEIL:
        return f"GOVERNANCE_DRAWDOWN_CEIL ({GOVERNANCE_DRAWDOWN_CEIL})"
    if token in _SHARPE_FIELD_TOKENS and perturbed_value <= GOVERNANCE_SHARPE_FLOOR:
        return f"GOVERNANCE_SHARPE_FLOOR ({GOVERNANCE_SHARPE_FLOOR})"
    return ""


def _compute_benchmark_delta(field_path: str, absolute_delta: float) -> float:
    """Approximate benchmark score impact of a metric change.

    Uses the explicit benchmark weight constants.  Returns 0.0 for
    fields not mapped to a known benchmark component.
    """
    token = _last_field_token(field_path)
    if token in _RETURN_FIELD_TOKENS:
        return absolute_delta * _BENCH_WEIGHT_RETURN
    if token in _DRAWDOWN_FIELD_TOKENS:
        return -absolute_delta * _BENCH_WEIGHT_DRAWDOWN  # drawdown increase hurts score
    if token in _SHARPE_FIELD_TOKENS:
        return absolute_delta * _BENCH_WEIGHT_SHARPE
    return 0.0


def _compute_walkforward_delta(field_path: str, absolute_delta: float) -> float:
    """Approximate walk-forward impact of a metric change.

    Returns absolute_delta for fields in the walk-forward metric category,
    0.0 otherwise.
    """
    token = _last_field_token(field_path)
    if token in _WALKFORWARD_FIELD_TOKENS:
        return absolute_delta
    return 0.0


def _last_field_token(field_path: str) -> str:
    """Return the last segment of a dotted field path."""
    return field_path.split(".")[-1]


def _compute_benchmark_impacts(
    results: tuple[SensitivityResult, ...],
) -> dict[str, Any]:
    """Summarise benchmark score impacts across all perturbation results."""
    if not results:
        return {
            "total_perturbations": 0,
            "max_absolute_benchmark_delta": None,
            "mean_absolute_benchmark_delta": None,
            "critical_count": 0,
            "high_count": 0,
        }

    benchmark_deltas = [abs(r.benchmark_delta) for r in results]
    critical_count = sum(1 for r in results if r.severity == SEVERITY_CRITICAL)
    high_count = sum(1 for r in results if r.severity == SEVERITY_HIGH)

    return {
        "total_perturbations": len(results),
        "max_absolute_benchmark_delta": max(benchmark_deltas),
        "mean_absolute_benchmark_delta": sum(benchmark_deltas) / len(benchmark_deltas),
        "critical_count": critical_count,
        "high_count": high_count,
    }


def _compute_walkforward_impacts(
    results: tuple[SensitivityResult, ...],
    perturbation_defs: list[PerturbationDefinition],
) -> dict[str, Any]:
    """Summarise walk-forward impacts across all perturbation results."""
    wf_results = [r for r in results if r.walkforward_delta != 0.0]
    wf_fields = sorted(
        {
            pdef.field_path
            for pdef in perturbation_defs
            if _last_field_token(pdef.field_path) in _WALKFORWARD_FIELD_TOKENS
        }
    )

    if not wf_results:
        return {
            "walkforward_fields_perturbed": wf_fields,
            "total_walkforward_perturbations": 0,
            "max_absolute_walkforward_delta": None,
            "degradation_finding_count": 0,
        }

    wf_deltas = [abs(r.walkforward_delta) for r in wf_results]
    degradation_count = sum(1 for r in wf_results if r.walkforward_delta < 0)

    return {
        "walkforward_fields_perturbed": wf_fields,
        "total_walkforward_perturbations": len(wf_results),
        "max_absolute_walkforward_delta": max(wf_deltas),
        "degradation_finding_count": degradation_count,
    }


def _compute_stability_scores(
    results: tuple[SensitivityResult, ...],
    perturbation_defs: list[PerturbationDefinition],
) -> dict[str, Any]:
    """Compute stability scores per parameter and overall.

    Stability score = fraction of perturbations classified as LOW severity.
    Score 1.0 = all perturbations are LOW (most stable).
    Score 0.0 = no perturbation is LOW (least stable).
    """
    if not results:
        return {
            "overall_stability": 1.0,
            "per_parameter": {},
            "finding_counts": {
                SEVERITY_LOW: 0,
                SEVERITY_MEDIUM: 0,
                SEVERITY_HIGH: 0,
                SEVERITY_CRITICAL: 0,
            },
        }

    counts: dict[str, int] = {
        SEVERITY_LOW: 0,
        SEVERITY_MEDIUM: 0,
        SEVERITY_HIGH: 0,
        SEVERITY_CRITICAL: 0,
    }
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1

    overall = counts[SEVERITY_LOW] / len(results)

    # Per-parameter stability
    per_param: dict[str, float] = {}
    param_names = sorted({p.parameter_name for p in perturbation_defs})
    for name in param_names:
        param_results = [r for r in results if r.parameter_name == name]
        if param_results:
            low_count = sum(1 for r in param_results if r.severity == SEVERITY_LOW)
            per_param[name] = low_count / len(param_results)
        else:
            per_param[name] = 1.0

    return {
        "overall_stability": overall,
        "per_parameter": per_param,
        "finding_counts": counts,
    }


# ── Serialization helpers ─────────────────────────────────────────────────────


def _pdef_to_dict(p: PerturbationDefinition) -> dict[str, Any]:
    return {
        "parameter_name": p.parameter_name,
        "field_path": p.field_path,
        "delta_type": p.delta_type,
        "delta_values": list(p.delta_values),
        "description": p.description,
    }


def _result_to_dict(r: SensitivityResult) -> dict[str, Any]:
    def _f(v: float) -> float | None:
        return None if math.isnan(v) else v

    return {
        "parameter_name": r.parameter_name,
        "baseline_value": _f(r.baseline_value),
        "perturbed_value": _f(r.perturbed_value),
        "perturbation_magnitude": r.perturbation_magnitude,
        "metric_deltas": normalize_nan(r.metric_deltas),
        "benchmark_delta": _f(r.benchmark_delta),
        "walkforward_delta": _f(r.walkforward_delta),
        "severity": r.severity,
        "deterministic_diff_summary": r.deterministic_diff_summary,
    }


def _finding_to_dict(f: InstabilityFinding) -> dict[str, Any]:
    def _f(v: float) -> float | None:
        return None if math.isnan(v) else v

    return {
        "parameter_name": f.parameter_name,
        "severity": f.severity,
        "perturbation_magnitude": f.perturbation_magnitude,
        "baseline_value": _f(f.baseline_value),
        "perturbed_value": _f(f.perturbed_value),
        "governance_threshold_crossed": f.governance_threshold_crossed,
        "deterministic_diff_summary": f.deterministic_diff_summary,
    }
