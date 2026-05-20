"""Deterministic research regression guards for AQCS.

A RegressionReport is an immutable, self-certifying report comparing two sets
of research artifacts (baseline vs candidate) to detect regressions in:

  - metric drift       (numeric metrics changed beyond explicit thresholds)
  - hash mismatches    (self-certifying hashes changed → potential tampering)
  - replay drift       (replay certificate hashes differ)
  - artifact changes   (files added/removed between baseline and candidate)
  - version changes    (artifact schema version bumped)

The regression guard is advisory-only.  It NEVER:
  - auto-remediates regressions
  - auto-approves or auto-rejects merges
  - modifies compared artifacts
  - adapts thresholds from data
  - takes autonomous actions

All detection thresholds are explicit module-level constants.
Any change to thresholds requires an ADR and human approval.

Determinism
-----------
- Artifact traversal uses ``sorted()`` for cross-platform stability.
- ``regression_hash`` is ``canonical_hash(content_dict)`` excluding itself
  and ``generation_timestamp_utc``.
- ``regression_id`` is a UUID5 derived from ``regression_hash``.
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

from aqcs.utils.canonicalization import canonical_hash, normalize_nan, sha256_hex

# ── Version ───────────────────────────────────────────────────────────────────

REGRESSION_VERSION: str = "1"

# Fixed UUID5 namespace for deterministic regression_id derivation.
_REGRESSION_NS: uuid.UUID = uuid.UUID("a9b8c7d6-e5f4-3210-fedc-ba9876543210")

# ── Artifact type discriminating fields (mirrors campaign.py) ─────────────────

_MANIFEST_FIELDS: frozenset[str] = frozenset(
    {"manifest_version", "content_hash", "schema_hash", "exchange"}
)
_CERTIFICATE_FIELDS: frozenset[str] = frozenset(
    {"certificate_version", "certified_bars", "config_hash"}
)
_WALKFORWARD_FIELDS: frozenset[str] = frozenset(
    {"train_bars", "step_bars", "leakage_validated", "n_windows"}
)
_BASELINE_FIELDS: frozenset[str] = frozenset(
    {"benchmark_total_return", "disclaimer", "initial_capital"}
)
_CAMPAIGN_FIELDS: frozenset[str] = frozenset(
    {"campaign_version", "campaign_hash", "campaign_id", "total_experiments"}
)
_BENCHMARK_FIELDS: frozenset[str] = frozenset(
    {"benchmark_version", "benchmark_hash", "benchmark_id", "total_campaigns"}
)

# ── Finding types — explicit enumeration ──────────────────────────────────────

FINDING_HASH_MISMATCH: str = "hash_mismatch"
FINDING_METRIC_DRIFT: str = "metric_drift"
FINDING_REPLAY_DRIFT: str = "replay_drift"
FINDING_ARTIFACT_MISSING: str = "artifact_missing"
FINDING_ARTIFACT_ADDED: str = "artifact_added"
FINDING_VERSION_CHANGE: str = "version_change"
FINDING_SCHEMA_DRIFT: str = "schema_drift"
FINDING_DETERMINISM_FAILURE: str = "determinism_failure"
FINDING_GOVERNANCE_VIOLATION: str = "governance_violation"

# ── Severity levels ───────────────────────────────────────────────────────────
# Comparison-severity classification: three levels for artifact-comparison findings.
# Uses lowercase string values.  This is a distinct system from sensitivity_audit's
# four-level instability-magnitude system ("CRITICAL"/"HIGH"/"MEDIUM"/"LOW").
# See docs/governance/governance_constants.md for the distinction.

SEVERITY_CRITICAL: str = "critical"
SEVERITY_WARNING: str = "warning"
SEVERITY_INFO: str = "info"

# ── Metric drift thresholds — explicit constants, fully documented ─────────────
# Any change to these thresholds requires an ADR and human approval.

# Relative change threshold for WARNING findings (|delta| / |baseline| > this).
DRIFT_THRESHOLD_WARNING: float = 0.05  # 5% relative change

# Relative change threshold for CRITICAL findings.
DRIFT_THRESHOLD_CRITICAL: float = 0.20  # 20% relative change

# Metrics compared for baseline reports and campaigns.
# Only numeric metrics with governance significance are included.
_BASELINE_METRIC_KEYS: tuple[str, ...] = (
    "total_return",
    "max_drawdown",
    "sharpe_ratio",
    "win_rate",
    "exposure",
    "turnover_per_bar",
)

_CAMPAIGN_METRIC_KEYS: tuple[str, ...] = (
    "mean_total_return",
    "mean_sharpe_ratio",
    "mean_max_drawdown",
    "mean_turnover_per_bar",
    "mean_exposure",
)

_WALKFORWARD_METRIC_KEYS: tuple[str, ...] = (
    "mean_total_return",
    "mean_sharpe_ratio",
    "mean_max_drawdown",
)


# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegressionFinding:
    """A single detected regression or difference between baseline and candidate.

    ``severity`` is one of: ``"critical"``, ``"warning"``, ``"info"``.
    ``finding_type`` is one of the ``FINDING_*`` constants above.
    ``expected_value`` and ``observed_value`` are string representations of
    the baseline and candidate values respectively.
    ``deterministic_diff_summary`` is a human-readable description.
    """

    finding_type: str
    severity: str
    artifact_reference: str
    expected_value: str
    observed_value: str
    deterministic_diff_summary: str


@dataclass(frozen=True)
class RegressionReport:
    """Immutable self-certifying regression comparison report.

    ``regression_hash`` is SHA-256 of the report content excluding itself
    and ``generation_timestamp_utc``.  ``regression_id`` is a UUID5 of
    ``regression_hash``.

    The report is advisory only.  Findings do not authorize automated merges,
    artifact modifications, or strategy mutations.
    """

    regression_version: str
    regression_id: str
    generation_timestamp_utc: str
    regression_hash: str
    baseline_artifact_hashes: dict[str, str]
    candidate_artifact_hashes: dict[str, str]
    regression_findings: tuple[RegressionFinding, ...]
    benchmark_comparisons: dict[str, Any]
    metric_deltas: dict[str, Any]
    replay_validation_results: dict[str, Any]
    determinism_validation_results: dict[str, Any]
    governance_validation_results: dict[str, Any]
    warnings: tuple[str, ...]
    issues: tuple[str, ...]


# ── Public API ────────────────────────────────────────────────────────────────


def run_regression_guard(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    now_utc: datetime | None = None,
) -> RegressionReport:
    """Compare baseline and candidate artifact directories and return a report.

    Scans both directories for JSON artifact files, classifies each by type,
    matches same-named files between directories, and runs type-specific
    regression checks.

    Args:
        baseline_dir: Directory containing baseline (reference) artifacts.
        candidate_dir: Directory containing candidate (proposed) artifacts.
        now_utc: Reference UTC time.  Defaults to ``datetime.now(UTC)``.
            Inject a fixed value in tests for deterministic output.

    Returns:
        Immutable, self-certifying ``RegressionReport``.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)
    findings: list[RegressionFinding] = []
    issues: list[str] = []
    warnings: list[str] = []

    # ── 1. Scan artifact files ─────────────────────────────────────────────────
    baseline_files = _scan_json_files(Path(baseline_dir), issues)
    candidate_files = _scan_json_files(Path(candidate_dir), issues)

    baseline_hashes: dict[str, str] = {
        name: sha256_hex(data) for name, data in baseline_files.items()
    }
    candidate_hashes: dict[str, str] = {
        name: sha256_hex(data) for name, data in candidate_files.items()
    }

    # ── 2. Detect added/removed artifacts ──────────────────────────────────────
    baseline_names = set(baseline_files)
    candidate_names = set(candidate_files)

    for name in sorted(baseline_names - candidate_names):
        findings.append(
            RegressionFinding(
                finding_type=FINDING_ARTIFACT_MISSING,
                severity=SEVERITY_WARNING,
                artifact_reference=name,
                expected_value=name,
                observed_value="(absent)",
                deterministic_diff_summary=(
                    f"Artifact '{name}' present in baseline but absent in candidate"
                ),
            )
        )
        warnings.append(f"Artifact missing from candidate: '{name}'")

    for name in sorted(candidate_names - baseline_names):
        findings.append(
            RegressionFinding(
                finding_type=FINDING_ARTIFACT_ADDED,
                severity=SEVERITY_INFO,
                artifact_reference=name,
                expected_value="(absent)",
                observed_value=name,
                deterministic_diff_summary=(
                    f"Artifact '{name}' absent in baseline but present in candidate"
                ),
            )
        )

    # ── 3. Compare matched artifacts ───────────────────────────────────────────
    metric_deltas: dict[str, Any] = {}
    replay_results: dict[str, Any] = {}
    determinism_results: dict[str, Any] = {}
    benchmark_comparisons: dict[str, Any] = {}

    for name in sorted(baseline_names & candidate_names):
        try:
            b_dict = json.loads(baseline_files[name])
            c_dict = json.loads(candidate_files[name])
        except json.JSONDecodeError as exc:
            issues.append(f"Cannot parse artifact '{name}': {exc}")
            continue

        artifact_type = _detect_type(b_dict)
        candidate_type = _detect_type(c_dict)

        if artifact_type != candidate_type:
            findings.append(
                RegressionFinding(
                    finding_type=FINDING_SCHEMA_DRIFT,
                    severity=SEVERITY_CRITICAL,
                    artifact_reference=name,
                    expected_value=artifact_type,
                    observed_value=candidate_type,
                    deterministic_diff_summary=(
                        f"Artifact '{name}' type changed: "
                        f"baseline='{artifact_type}' candidate='{candidate_type}'"
                    ),
                )
            )
            continue

        # Version change check
        _check_version(name, b_dict, c_dict, findings)

        # Type-specific comparisons
        if artifact_type == "baseline":
            _compare_baseline(name, b_dict, c_dict, findings, metric_deltas)
        elif artifact_type == "walkforward":
            _compare_walkforward(name, b_dict, c_dict, findings, metric_deltas)
        elif artifact_type == "campaign":
            _compare_campaign(name, b_dict, c_dict, findings, metric_deltas)
        elif artifact_type == "certificate":
            _compare_certificate(name, b_dict, c_dict, findings, replay_results)
        elif artifact_type == "manifest":
            _compare_manifest(name, b_dict, c_dict, findings)
        elif artifact_type == "benchmark":
            _compare_benchmark(name, b_dict, c_dict, findings, benchmark_comparisons)

        # Determinism check: same artifact name, same content → same hash
        if baseline_hashes[name] == candidate_hashes[name]:
            determinism_results[name] = {"status": "identical", "hash": baseline_hashes[name]}
        else:
            determinism_results[name] = {
                "status": "changed",
                "baseline_hash": baseline_hashes[name],
                "candidate_hash": candidate_hashes[name],
            }

    # ── 4. Governance validation ───────────────────────────────────────────────
    governance_results = _check_governance(baseline_files, candidate_files, findings, warnings)

    # ── 5. Build content dict for hashing ─────────────────────────────────────
    findings_sorted = tuple(
        sorted(findings, key=lambda f: (f.severity, f.finding_type, f.artifact_reference))
    )

    content_dict: dict[str, Any] = {
        "regression_version": REGRESSION_VERSION,
        "baseline_artifact_hashes": dict(sorted(baseline_hashes.items())),
        "candidate_artifact_hashes": dict(sorted(candidate_hashes.items())),
        "regression_findings": [_finding_to_dict(f) for f in findings_sorted],
        "benchmark_comparisons": normalize_nan(benchmark_comparisons),
        "metric_deltas": normalize_nan(metric_deltas),
        "replay_validation_results": normalize_nan(replay_results),
        "determinism_validation_results": determinism_results,
        "governance_validation_results": governance_results,
        "drift_thresholds": {
            "warning": DRIFT_THRESHOLD_WARNING,
            "critical": DRIFT_THRESHOLD_CRITICAL,
        },
        "issues": sorted(issues),
        "warnings": sorted(warnings),
    }

    regression_hash = canonical_hash(content_dict)
    regression_id = str(uuid.uuid5(_REGRESSION_NS, regression_hash))

    return RegressionReport(
        regression_version=REGRESSION_VERSION,
        regression_id=regression_id,
        generation_timestamp_utc=_now.isoformat(),
        regression_hash=regression_hash,
        baseline_artifact_hashes=dict(sorted(baseline_hashes.items())),
        candidate_artifact_hashes=dict(sorted(candidate_hashes.items())),
        regression_findings=findings_sorted,
        benchmark_comparisons=benchmark_comparisons,
        metric_deltas=metric_deltas,
        replay_validation_results=replay_results,
        determinism_validation_results=determinism_results,
        governance_validation_results=governance_results,
        warnings=tuple(sorted(warnings)),
        issues=tuple(sorted(issues)),
    )


def validate_regression_report(report: RegressionReport) -> tuple[bool, list[str]]:
    """Validate a regression report's self-certifying hash and consistency.

    Returns:
        ``(is_valid, errors)`` — errors is empty when valid.
    """
    errors: list[str] = []

    d = regression_report_to_dict(report)
    d_no_hash = {
        k: v
        for k, v in d.items()
        if k not in {"regression_hash", "regression_id", "generation_timestamp_utc"}
    }
    expected = canonical_hash(d_no_hash)
    if expected != report.regression_hash:
        errors.append(
            f"regression_hash mismatch: stored={report.regression_hash[:16]}… "
            f"recomputed={expected[:16]}…"
        )

    expected_id = str(uuid.uuid5(_REGRESSION_NS, report.regression_hash))
    if expected_id != report.regression_id:
        errors.append(
            f"regression_id mismatch: stored={report.regression_id} " f"recomputed={expected_id}"
        )

    if report.regression_version != REGRESSION_VERSION:
        errors.append(
            f"regression_version '{report.regression_version}' != current '{REGRESSION_VERSION}'"
        )

    return len(errors) == 0, errors


def regression_report_to_dict(report: RegressionReport) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``RegressionReport``."""

    def _f(v: Any) -> Any:
        return None if isinstance(v, float) and math.isnan(v) else v

    def _clean(d: dict[str, Any]) -> dict[str, Any]:
        return {k: _f(v) for k, v in d.items()}

    return {
        "regression_version": report.regression_version,
        "regression_id": report.regression_id,
        "generation_timestamp_utc": report.generation_timestamp_utc,
        "regression_hash": report.regression_hash,
        "baseline_artifact_hashes": dict(report.baseline_artifact_hashes),
        "candidate_artifact_hashes": dict(report.candidate_artifact_hashes),
        "regression_findings": [_finding_to_dict(f) for f in report.regression_findings],
        "benchmark_comparisons": _clean(dict(report.benchmark_comparisons)),
        "metric_deltas": _clean(dict(report.metric_deltas)),
        "replay_validation_results": _clean(dict(report.replay_validation_results)),
        "determinism_validation_results": dict(report.determinism_validation_results),
        "governance_validation_results": dict(report.governance_validation_results),
        "drift_thresholds": {
            "warning": DRIFT_THRESHOLD_WARNING,
            "critical": DRIFT_THRESHOLD_CRITICAL,
        },
        "warnings": list(report.warnings),
        "issues": list(report.issues),
    }


def regression_report_from_dict(d: dict[str, Any]) -> RegressionReport:
    """Reconstruct a ``RegressionReport`` from a dict.

    Raises:
        KeyError: If any required field is missing.
    """
    findings = tuple(
        RegressionFinding(
            finding_type=str(f["finding_type"]),
            severity=str(f["severity"]),
            artifact_reference=str(f["artifact_reference"]),
            expected_value=str(f["expected_value"]),
            observed_value=str(f["observed_value"]),
            deterministic_diff_summary=str(f["deterministic_diff_summary"]),
        )
        for f in d["regression_findings"]
    )
    return RegressionReport(
        regression_version=str(d["regression_version"]),
        regression_id=str(d["regression_id"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        regression_hash=str(d["regression_hash"]),
        baseline_artifact_hashes=dict(d["baseline_artifact_hashes"]),
        candidate_artifact_hashes=dict(d["candidate_artifact_hashes"]),
        regression_findings=findings,
        benchmark_comparisons=dict(d["benchmark_comparisons"]),
        metric_deltas=dict(d["metric_deltas"]),
        replay_validation_results=dict(d["replay_validation_results"]),
        determinism_validation_results=dict(d["determinism_validation_results"]),
        governance_validation_results=dict(d["governance_validation_results"]),
        warnings=tuple(str(w) for w in d["warnings"]),
        issues=tuple(str(i) for i in d["issues"]),
    )


def save_regression_report(report: RegressionReport, path: Path) -> None:
    """Write a regression report to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(regression_report_to_dict(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_regression_report(path: Path) -> RegressionReport:
    """Load a regression report from a JSON file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in regression report '{path}': {exc}") from exc
    return regression_report_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _detect_type(d: dict[str, Any]) -> str:
    """Classify a JSON artifact dict by its discriminating fields."""
    keys = set(d.keys())
    if _BENCHMARK_FIELDS.issubset(keys):
        return "benchmark"
    if _CAMPAIGN_FIELDS.issubset(keys):
        return "campaign"
    if _MANIFEST_FIELDS.issubset(keys):
        return "manifest"
    if _CERTIFICATE_FIELDS.issubset(keys):
        return "certificate"
    if _WALKFORWARD_FIELDS.issubset(keys):
        return "walkforward"
    if _BASELINE_FIELDS.issubset(keys):
        return "baseline"
    return "unknown"


def _scan_json_files(directory: Path, issues: list[str]) -> dict[str, bytes]:
    """Return {filename: raw_bytes} for all *.json files in ``directory`` (sorted)."""
    result: dict[str, bytes] = {}
    if not directory.exists():
        issues.append(f"Directory not found: '{directory}'")
        return result
    for path in sorted(directory.rglob("*.json")):
        rel = str(path.relative_to(directory))
        try:
            result[rel] = path.read_bytes()
        except OSError as exc:
            issues.append(f"Cannot read '{rel}': {exc}")
    return result


def _nan(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _relative_delta(base: float, cand: float) -> float:
    """Return (cand - base) / |base|, or 0.0 if base is zero/NaN."""
    if math.isnan(base) or math.isnan(cand) or base == 0.0:
        return 0.0
    return (cand - base) / abs(base)


def _classify_drift(rel_delta: float) -> str:
    abs_delta = abs(rel_delta)
    if abs_delta >= DRIFT_THRESHOLD_CRITICAL:
        return SEVERITY_CRITICAL
    if abs_delta >= DRIFT_THRESHOLD_WARNING:
        return SEVERITY_WARNING
    return SEVERITY_INFO


def _check_metric_pair(
    name: str,
    metric_key: str,
    base_val: float,
    cand_val: float,
    findings: list[RegressionFinding],
    metric_deltas: dict[str, Any],
) -> None:
    """Compare one metric pair and append a finding if drift is detected."""
    rel = _relative_delta(base_val, cand_val)
    delta_key = f"{name}::{metric_key}"
    metric_deltas[delta_key] = {
        "baseline": base_val if not math.isnan(base_val) else None,
        "candidate": cand_val if not math.isnan(cand_val) else None,
        "absolute_delta": (
            (cand_val - base_val) if not (math.isnan(base_val) or math.isnan(cand_val)) else None
        ),
        "relative_delta": rel if not math.isnan(rel) else None,
    }

    severity = _classify_drift(rel)
    if severity in (SEVERITY_WARNING, SEVERITY_CRITICAL):
        findings.append(
            RegressionFinding(
                finding_type=FINDING_METRIC_DRIFT,
                severity=severity,
                artifact_reference=name,
                expected_value=f"{metric_key}={base_val:.6f}",
                observed_value=f"{metric_key}={cand_val:.6f}",
                deterministic_diff_summary=(
                    f"'{metric_key}' in '{name}': baseline={base_val:.6f} "
                    f"candidate={cand_val:.6f} rel_delta={rel:+.1%}"
                ),
            )
        )


def _check_version(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
) -> None:
    """Detect version field changes."""
    for vfield in (
        "manifest_version",
        "report_version",
        "campaign_version",
        "certificate_version",
        "benchmark_version",
        "regression_version",
    ):
        if vfield in b and vfield in c and b[vfield] != c[vfield]:
            findings.append(
                RegressionFinding(
                    finding_type=FINDING_VERSION_CHANGE,
                    severity=SEVERITY_WARNING,
                    artifact_reference=name,
                    expected_value=str(b[vfield]),
                    observed_value=str(c[vfield]),
                    deterministic_diff_summary=(
                        f"'{name}': {vfield} changed from '{b[vfield]}' to '{c[vfield]}'"
                    ),
                )
            )


def _check_hash_field(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    hash_field: str,
    findings: list[RegressionFinding],
) -> None:
    """Detect changes in a self-certifying hash field."""
    bh = str(b.get(hash_field, ""))
    ch = str(c.get(hash_field, ""))
    if bh and ch and bh != ch:
        findings.append(
            RegressionFinding(
                finding_type=FINDING_HASH_MISMATCH,
                severity=SEVERITY_CRITICAL,
                artifact_reference=name,
                expected_value=f"{hash_field}={bh[:16]}…",
                observed_value=f"{hash_field}={ch[:16]}…",
                deterministic_diff_summary=(
                    f"'{name}': {hash_field} changed — " f"baseline={bh[:16]}… candidate={ch[:16]}…"
                ),
            )
        )


def _compare_baseline(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
    metric_deltas: dict[str, Any],
) -> None:
    _check_hash_field(name, b, c, "report_hash", findings)
    for key in _BASELINE_METRIC_KEYS:
        bv = _nan(b.get(key))
        cv = _nan(c.get(key))
        _check_metric_pair(name, key, bv, cv, findings, metric_deltas)


def _compare_walkforward(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
    metric_deltas: dict[str, Any],
) -> None:
    _check_hash_field(name, b, c, "report_hash", findings)
    bs = b.get("summary", {})
    cs = c.get("summary", {})
    for key in _WALKFORWARD_METRIC_KEYS:
        bv = _nan(bs.get(key))
        cv = _nan(cs.get(key))
        _check_metric_pair(name, f"summary.{key}", bv, cv, findings, metric_deltas)

    # Leakage validation flag check
    bl = bool(b.get("leakage_validated", True))
    cl = bool(c.get("leakage_validated", True))
    if bl and not cl:
        findings.append(
            RegressionFinding(
                finding_type=FINDING_GOVERNANCE_VIOLATION,
                severity=SEVERITY_CRITICAL,
                artifact_reference=name,
                expected_value="leakage_validated=True",
                observed_value="leakage_validated=False",
                deterministic_diff_summary=(
                    f"'{name}': candidate walk-forward has leakage_validated=False "
                    f"while baseline was True — temporal integrity regression"
                ),
            )
        )


def _compare_campaign(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
    metric_deltas: dict[str, Any],
) -> None:
    _check_hash_field(name, b, c, "campaign_hash", findings)
    bm = b.get("aggregate_metrics", {})
    cm = c.get("aggregate_metrics", {})
    for key in _CAMPAIGN_METRIC_KEYS:
        bv = _nan(bm.get(key))
        cv = _nan(cm.get(key))
        _check_metric_pair(name, f"aggregate_metrics.{key}", bv, cv, findings, metric_deltas)


def _compare_certificate(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
    replay_results: dict[str, Any],
) -> None:
    """Compare replay certificates for replay drift."""
    hash_fields = ("metrics_hash", "trades_hash", "equity_hash", "signals_hash", "config_hash")
    drifted: list[str] = []
    for field in hash_fields:
        bh = str(b.get(field, ""))
        ch = str(c.get(field, ""))
        if bh and ch and bh != ch:
            drifted.append(field)

    if drifted:
        findings.append(
            RegressionFinding(
                finding_type=FINDING_REPLAY_DRIFT,
                severity=SEVERITY_CRITICAL,
                artifact_reference=name,
                expected_value=f"fields={drifted} unchanged",
                observed_value=f"fields={drifted} differ",
                deterministic_diff_summary=(
                    f"'{name}': replay certificate drift in {drifted} — "
                    f"experiment cannot be reproduced identically"
                ),
            )
        )

    replay_results[name] = {
        "drifted_fields": drifted,
        "replay_compatible": len(drifted) == 0,
        "baseline_certified_bars": b.get("certified_bars"),
        "candidate_certified_bars": c.get("certified_bars"),
    }


def _compare_manifest(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
) -> None:
    """Compare dataset manifests for content or schema drift."""
    for field in ("content_hash", "schema_hash"):
        _check_hash_field(name, b, c, field, findings)

    b_rows = b.get("row_count", 0)
    c_rows = c.get("row_count", 0)
    if b_rows != c_rows:
        findings.append(
            RegressionFinding(
                finding_type=FINDING_METRIC_DRIFT,
                severity=SEVERITY_WARNING,
                artifact_reference=name,
                expected_value=f"row_count={b_rows}",
                observed_value=f"row_count={c_rows}",
                deterministic_diff_summary=(
                    f"'{name}': manifest row_count changed from {b_rows} to {c_rows}"
                ),
            )
        )


def _compare_benchmark(
    name: str,
    b: dict[str, Any],
    c: dict[str, Any],
    findings: list[RegressionFinding],
    benchmark_comparisons: dict[str, Any],
) -> None:
    """Compare benchmark suites for regression flag changes."""
    _check_hash_field(name, b, c, "benchmark_hash", findings)

    b_flags = set(b.get("regression_flags", []))
    c_flags = set(c.get("regression_flags", []))
    new_flags = sorted(c_flags - b_flags)
    resolved_flags = sorted(b_flags - c_flags)

    if new_flags:
        findings.append(
            RegressionFinding(
                finding_type=FINDING_METRIC_DRIFT,
                severity=SEVERITY_CRITICAL,
                artifact_reference=name,
                expected_value=f"regression_flags={sorted(b_flags)}",
                observed_value=f"new_flags={new_flags}",
                deterministic_diff_summary=(
                    f"'{name}': benchmark acquired {len(new_flags)} new regression flag(s): "
                    f"{new_flags}"
                ),
            )
        )

    benchmark_comparisons[name] = {
        "new_regression_flags": new_flags,
        "resolved_regression_flags": resolved_flags,
        "baseline_total_campaigns": b.get("total_campaigns"),
        "candidate_total_campaigns": c.get("total_campaigns"),
    }


def _check_governance(
    baseline_files: dict[str, bytes],
    candidate_files: dict[str, bytes],
    findings: list[RegressionFinding],
    warnings: list[str],
) -> dict[str, Any]:
    """Detect governance violations in candidate artifacts."""
    violations: list[str] = []

    for name, raw in sorted(candidate_files.items()):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        artifact_type = _detect_type(d)

        # Check: baseline reports must carry a non-empty disclaimer
        if artifact_type == "baseline":
            disclaimer = str(d.get("disclaimer", ""))
            if not disclaimer:
                violations.append(f"'{name}': baseline report missing mandatory disclaimer")
                findings.append(
                    RegressionFinding(
                        finding_type=FINDING_GOVERNANCE_VIOLATION,
                        severity=SEVERITY_CRITICAL,
                        artifact_reference=name,
                        expected_value="disclaimer=(non-empty)",
                        observed_value="disclaimer=(empty)",
                        deterministic_diff_summary=(
                            f"'{name}': missing mandatory disclaimer — governance violation"
                        ),
                    )
                )

        # Check: walk-forward reports must have leakage validated
        if artifact_type == "walkforward" and not d.get("leakage_validated", True):
            violations.append(f"'{name}': walk-forward report has leakage_validated=False")

    return {
        "violations": violations,
        "violation_count": len(violations),
        "governance_clean": len(violations) == 0,
    }


def _finding_to_dict(f: RegressionFinding) -> dict[str, str]:
    return {
        "finding_type": f.finding_type,
        "severity": f.severity,
        "artifact_reference": f.artifact_reference,
        "expected_value": f.expected_value,
        "observed_value": f.observed_value,
        "deterministic_diff_summary": f.deterministic_diff_summary,
    }
