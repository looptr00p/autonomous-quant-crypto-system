"""Deterministic research campaign orchestration for AQCS.

A ResearchCampaign is an immutable, self-certifying orchestration artifact
that links together:

  - DatasetManifest JSON artifacts
  - ReplayCertificate JSON artifacts
  - WalkForwardReport JSON artifacts
  - BaselineReport JSON artifacts

The campaign provides:
  - artifact lineage traceability
  - deterministic aggregate metrics
  - self-certifying hash for reproducibility verification
  - validation of artifact integrity and consistency

Determinism
-----------
- Artifact traversal uses ``sorted()`` for cross-platform stability.
- ``campaign_hash`` excludes ``generation_timestamp_utc``, ``campaign_hash``,
  and ``campaign_id`` — making it purely content-addressable.
- ``campaign_id`` is a UUID5 derived deterministically from ``campaign_hash``.
- All float aggregates use explicit NaN handling (serialised as ``null``).
- Canonical JSON uses ``sort_keys=True, separators=(",", ":")``.

Artifact type detection
-----------------------
JSON files are classified by the presence of discriminating fields:

  DatasetManifest    : has ``manifest_version``, ``content_hash``, ``schema_hash``
  ReplayCertificate  : has ``certificate_version``, ``certified_bars``
  WalkForwardReport  : has ``train_bars``, ``step_bars``, ``leakage_validated``
  BaselineReport     : has ``benchmark_total_return``, ``disclaimer``

Unrecognised files are recorded as warnings and excluded from aggregation.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aqcs.utils.canonicalization import canonical_hash, legacy_hash

CAMPAIGN_VERSION: str = "1"

# Fixed UUID5 namespace — never changes.
_CAMPAIGN_NS: uuid.UUID = uuid.UUID("c3a2b1d0-e5f6-7890-abcd-123456789abc")

# ── Discriminating field sets for artifact type detection ─────────────────────

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

# Required fields for schema validation per artifact type
_MANIFEST_REQUIRED: tuple[str, ...] = (
    "manifest_version",
    "content_hash",
    "schema_hash",
    "symbol",
    "timeframe",
    "exchange",
    "row_count",
    "start_timestamp_utc",
    "end_timestamp_utc",
)
_CERTIFICATE_REQUIRED: tuple[str, ...] = (
    "certificate_version",
    "experiment_id",
    "dataset_content_hash",
    "dataset_schema_hash",
    "config_hash",
    "metrics_hash",
    "certified_bars",
    "certified_trades",
)
_WALKFORWARD_REQUIRED: tuple[str, ...] = (
    "report_version",
    "train_bars",
    "test_bars",
    "step_bars",
    "n_windows",
    "report_hash",
    "leakage_validated",
    "summary",
)
_BASELINE_REQUIRED: tuple[str, ...] = (
    "report_version",
    "experiment_id",
    "report_hash",
    "total_return",
    "max_drawdown",
    "sharpe_ratio",
    "exposure",
    "disclaimer",
    "benchmark_total_return",
)


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResearchCampaign:
    """Immutable deterministic research campaign.

    ``campaign_hash`` is a SHA-256 of all fields except itself,
    ``campaign_id``, and ``generation_timestamp_utc``.
    ``campaign_id`` is a UUID5 derived from ``campaign_hash``.

    All float values use ``float("nan")`` for undefined metrics;
    JSON export serialises NaN as ``null``.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    campaign_version: str
    campaign_id: str
    campaign_name: str
    generation_timestamp_utc: str
    campaign_hash: str

    # ── Artifact reference hashes ─────────────────────────────────────────────
    dataset_manifest_hashes: tuple[str, ...]
    replay_certificate_hashes: tuple[str, ...]
    walkforward_report_hashes: tuple[str, ...]
    baseline_report_hashes: tuple[str, ...]

    # ── Counts ────────────────────────────────────────────────────────────────
    total_experiments: int
    total_walkforward_windows: int

    # ── Dataset coverage ──────────────────────────────────────────────────────
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    aggregate_metrics: dict[str, Any]
    aggregate_drawdown: dict[str, Any]
    aggregate_turnover: dict[str, Any]
    aggregate_exposure: dict[str, Any]

    # ── Artifact content hashes (SHA-256 of raw file bytes) ───────────────────
    artifact_hashes: dict[str, str]

    # ── Validation ────────────────────────────────────────────────────────────
    issues: tuple[str, ...]
    warnings: tuple[str, ...]


# ── Public API ────────────────────────────────────────────────────────────────


def build_campaign(
    artifacts_dir: Path,
    campaign_name: str,
    *,
    now_utc: datetime | None = None,
) -> ResearchCampaign:
    """Scan ``artifacts_dir`` and build a deterministic research campaign.

    Discovers JSON artifacts by field-based type detection, validates each
    artifact's required fields and self-certifying hash, aggregates metrics,
    and produces an immutable campaign object.

    Args:
        artifacts_dir: Root directory to scan for artifact JSON files.
        campaign_name: Human-readable campaign name (stored in the object).
        now_utc: Reference UTC time.  Defaults to ``datetime.now(UTC)``.
            Inject a fixed value in tests for deterministic output.

    Returns:
        Immutable ``ResearchCampaign`` with full lineage and aggregates.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)

    scanned = _scan_artifacts(Path(artifacts_dir))

    manifests = scanned["manifests"]
    certificates = scanned["certificates"]
    walkforwards = scanned["walkforwards"]
    baselines = scanned["baselines"]
    artifact_hashes = scanned["artifact_hashes"]
    issues: list[str] = list(scanned["issues"])
    warnings: list[str] = list(scanned["warnings"])

    # ── Validate required fields and self-certifying hashes ───────────────────
    for i, m in enumerate(manifests):
        issues.extend(_check_required(m, _MANIFEST_REQUIRED, f"manifest[{i}]"))

    for i, c in enumerate(certificates):
        issues.extend(_check_required(c, _CERTIFICATE_REQUIRED, f"certificate[{i}]"))

    for i, w in enumerate(walkforwards):
        issues.extend(_check_required(w, _WALKFORWARD_REQUIRED, f"walkforward[{i}]"))
        if "report_hash" in w and not _verify_self_hash(w, "report_hash"):
            issues.append(f"walkforward[{i}]: report_hash mismatch (artifact may be tampered)")

    for i, b in enumerate(baselines):
        issues.extend(_check_required(b, _BASELINE_REQUIRED, f"baseline[{i}]"))
        if "report_hash" in b and not _verify_self_hash(b, "report_hash"):
            issues.append(f"baseline[{i}]: report_hash mismatch (artifact may be tampered)")

    # ── Warnings for missing artifact types ───────────────────────────────────
    if not manifests:
        warnings.append("No DatasetManifest artifacts found in artifacts_dir")
    if not certificates:
        warnings.append("No ReplayCertificate artifacts found in artifacts_dir")
    if not walkforwards:
        warnings.append("No WalkForwardReport artifacts found in artifacts_dir")
    if not baselines:
        warnings.append("No BaselineReport artifacts found in artifacts_dir")

    # ── Duplicate detection ───────────────────────────────────────────────────
    all_hashes = list(artifact_hashes.values())
    if len(all_hashes) != len(set(all_hashes)):
        issues.append("Duplicate artifact files detected (same SHA-256 content)")

    # ── Reference hash extraction ─────────────────────────────────────────────
    manifest_content_hashes = tuple(
        sorted(str(m.get("content_hash", "")) for m in manifests if m.get("content_hash"))
    )
    cert_hashes = tuple(
        sorted(str(c.get("config_hash", "")) for c in certificates if c.get("config_hash"))
    )
    wf_hashes = tuple(
        sorted(str(w.get("report_hash", "")) for w in walkforwards if w.get("report_hash"))
    )
    baseline_hashes = tuple(
        sorted(str(b.get("report_hash", "")) for b in baselines if b.get("report_hash"))
    )

    # ── Dataset coverage ──────────────────────────────────────────────────────
    symbols = tuple(sorted({str(m.get("symbol", "")) for m in manifests if m.get("symbol")}))
    timeframes = tuple(
        sorted({str(m.get("timeframe", "")) for m in manifests if m.get("timeframe")})
    )

    # ── Counts ────────────────────────────────────────────────────────────────
    total_experiments = len(baselines)
    total_wf_windows = sum(int(w.get("n_windows", 0)) for w in walkforwards)

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    agg_metrics = _aggregate_baseline_metrics(baselines)
    agg_drawdown = _aggregate_drawdown(baselines)
    agg_turnover = _aggregate_turnover(baselines)
    agg_exposure = _aggregate_exposure(baselines)

    # Add walk-forward summary aggregates
    if walkforwards:
        wf_agg = _aggregate_walkforward(walkforwards)
        agg_metrics.update(wf_agg)

    # ── Build content dict for hashing (excludes hash, id, timestamp) ─────────
    content_dict: dict[str, Any] = {
        "campaign_version": CAMPAIGN_VERSION,
        "campaign_name": campaign_name,
        "dataset_manifest_hashes": list(manifest_content_hashes),
        "replay_certificate_hashes": list(cert_hashes),
        "walkforward_report_hashes": list(wf_hashes),
        "baseline_report_hashes": list(baseline_hashes),
        "total_experiments": total_experiments,
        "total_walkforward_windows": total_wf_windows,
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "aggregate_metrics": _nan_to_none(agg_metrics),
        "aggregate_drawdown": _nan_to_none(agg_drawdown),
        "aggregate_turnover": _nan_to_none(agg_turnover),
        "aggregate_exposure": _nan_to_none(agg_exposure),
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "issues": sorted(issues),
        "warnings": sorted(warnings),
    }

    campaign_hash = _compute_campaign_hash(content_dict)
    campaign_id = str(uuid.uuid5(_CAMPAIGN_NS, campaign_hash))

    return ResearchCampaign(
        campaign_version=CAMPAIGN_VERSION,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        generation_timestamp_utc=_now.isoformat(),
        campaign_hash=campaign_hash,
        dataset_manifest_hashes=manifest_content_hashes,
        replay_certificate_hashes=cert_hashes,
        walkforward_report_hashes=wf_hashes,
        baseline_report_hashes=baseline_hashes,
        total_experiments=total_experiments,
        total_walkforward_windows=total_wf_windows,
        symbols=symbols,
        timeframes=timeframes,
        aggregate_metrics=agg_metrics,
        aggregate_drawdown=agg_drawdown,
        aggregate_turnover=agg_turnover,
        aggregate_exposure=agg_exposure,
        artifact_hashes=dict(sorted(artifact_hashes.items())),
        issues=tuple(sorted(issues)),
        warnings=tuple(sorted(warnings)),
    )


def validate_campaign(campaign: ResearchCampaign) -> tuple[bool, list[str]]:
    """Validate a campaign's self-certifying hash and internal consistency.

    Returns:
        ``(is_valid, errors)`` — errors is empty when valid.
    """
    errors: list[str] = []

    d = campaign_to_dict(campaign)
    d_no_hash = {
        k: v
        for k, v in d.items()
        if k not in {"campaign_hash", "campaign_id", "generation_timestamp_utc"}
    }
    expected_hash = _compute_campaign_hash(d_no_hash)
    if expected_hash != campaign.campaign_hash:
        errors.append(
            f"campaign_hash mismatch: stored={campaign.campaign_hash[:16]}… "
            f"recomputed={expected_hash[:16]}…"
        )

    expected_id = str(uuid.uuid5(_CAMPAIGN_NS, campaign.campaign_hash))
    if expected_id != campaign.campaign_id:
        errors.append(
            f"campaign_id mismatch: stored={campaign.campaign_id} " f"recomputed={expected_id}"
        )

    if campaign.campaign_version != CAMPAIGN_VERSION:
        errors.append(
            f"campaign_version '{campaign.campaign_version}' != current '{CAMPAIGN_VERSION}'"
        )

    if campaign.issues:
        errors.extend(f"recorded issue: {i}" for i in campaign.issues)

    return len(errors) == 0, errors


def campaign_to_dict(campaign: ResearchCampaign) -> dict[str, Any]:
    """Return a JSON-serializable dict.  NaN floats become ``null``."""

    def _s(v: Any) -> Any:
        if isinstance(v, float) and math.isnan(v):
            return None
        if isinstance(v, dict):
            return {k: _s(vv) for k, vv in v.items()}
        return v

    return {
        "campaign_version": campaign.campaign_version,
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.campaign_name,
        "generation_timestamp_utc": campaign.generation_timestamp_utc,
        "campaign_hash": campaign.campaign_hash,
        "dataset_manifest_hashes": list(campaign.dataset_manifest_hashes),
        "replay_certificate_hashes": list(campaign.replay_certificate_hashes),
        "walkforward_report_hashes": list(campaign.walkforward_report_hashes),
        "baseline_report_hashes": list(campaign.baseline_report_hashes),
        "total_experiments": campaign.total_experiments,
        "total_walkforward_windows": campaign.total_walkforward_windows,
        "symbols": list(campaign.symbols),
        "timeframes": list(campaign.timeframes),
        "aggregate_metrics": _s(dict(campaign.aggregate_metrics)),
        "aggregate_drawdown": _s(dict(campaign.aggregate_drawdown)),
        "aggregate_turnover": _s(dict(campaign.aggregate_turnover)),
        "aggregate_exposure": _s(dict(campaign.aggregate_exposure)),
        "artifact_hashes": dict(campaign.artifact_hashes),
        "issues": list(campaign.issues),
        "warnings": list(campaign.warnings),
    }


def campaign_from_dict(d: dict[str, Any]) -> ResearchCampaign:
    """Reconstruct a ``ResearchCampaign`` from a dict.

    Raises:
        KeyError: If any required field is missing.
    """

    def _fn(v: Any) -> Any:
        if v is None:
            return float("nan")
        if isinstance(v, dict):
            return {k: _fn(vv) for k, vv in v.items()}
        return v

    return ResearchCampaign(
        campaign_version=str(d["campaign_version"]),
        campaign_id=str(d["campaign_id"]),
        campaign_name=str(d["campaign_name"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        campaign_hash=str(d["campaign_hash"]),
        dataset_manifest_hashes=tuple(str(h) for h in d["dataset_manifest_hashes"]),
        replay_certificate_hashes=tuple(str(h) for h in d["replay_certificate_hashes"]),
        walkforward_report_hashes=tuple(str(h) for h in d["walkforward_report_hashes"]),
        baseline_report_hashes=tuple(str(h) for h in d["baseline_report_hashes"]),
        total_experiments=int(d["total_experiments"]),
        total_walkforward_windows=int(d["total_walkforward_windows"]),
        symbols=tuple(str(s) for s in d["symbols"]),
        timeframes=tuple(str(t) for t in d["timeframes"]),
        aggregate_metrics=_fn(dict(d["aggregate_metrics"])),
        aggregate_drawdown=_fn(dict(d["aggregate_drawdown"])),
        aggregate_turnover=_fn(dict(d["aggregate_turnover"])),
        aggregate_exposure=_fn(dict(d["aggregate_exposure"])),
        artifact_hashes=dict(d["artifact_hashes"]),
        issues=tuple(str(i) for i in d["issues"]),
        warnings=tuple(str(w) for w in d["warnings"]),
    )


def save_campaign(campaign: ResearchCampaign, path: Path) -> None:
    """Write campaign to a JSON file.  Keys are sorted; separators are compact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(campaign_to_dict(campaign), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_campaign(path: Path) -> ResearchCampaign:
    """Load a campaign from a JSON file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in campaign file '{path}': {exc}") from exc
    return campaign_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _detect_artifact_type(d: dict[str, Any]) -> str:
    """Classify a JSON dict by its discriminating fields."""
    keys = set(d.keys())
    if _MANIFEST_FIELDS.issubset(keys):
        return "manifest"
    if _CERTIFICATE_FIELDS.issubset(keys):
        return "certificate"
    if _WALKFORWARD_FIELDS.issubset(keys):
        return "walkforward"
    if _BASELINE_FIELDS.issubset(keys):
        return "baseline"
    return "unknown"


def _scan_artifacts(
    artifacts_dir: Path,
) -> dict[str, Any]:
    """Recursively scan a directory for artifact JSON files.

    Files are sorted by path for deterministic traversal ordering.
    Returns a dict with keys: manifests, certificates, walkforwards, baselines,
    artifact_hashes, issues, warnings.
    """
    manifests: list[dict[str, Any]] = []
    certificates: list[dict[str, Any]] = []
    walkforwards: list[dict[str, Any]] = []
    baselines: list[dict[str, Any]] = []
    artifact_hashes: dict[str, str] = {}
    issues: list[str] = []
    warnings: list[str] = []

    json_files = sorted(artifacts_dir.rglob("*.json"))

    for path in json_files:
        rel = str(path.relative_to(artifacts_dir))
        try:
            raw_bytes = path.read_bytes()
            file_hash = hashlib.sha256(raw_bytes).hexdigest()
            artifact_hashes[rel] = file_hash
            d: dict[str, Any] = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(f"Cannot load '{rel}': {exc}")
            continue

        artifact_type = _detect_artifact_type(d)
        if artifact_type == "manifest":
            manifests.append(d)
        elif artifact_type == "certificate":
            certificates.append(d)
        elif artifact_type == "walkforward":
            walkforwards.append(d)
        elif artifact_type == "baseline":
            baselines.append(d)
        else:
            warnings.append(f"Unrecognised artifact type for '{rel}'; excluded from campaign")

    # Sort each list deterministically by a stable key
    manifests.sort(key=lambda m: str(m.get("content_hash", "")))
    certificates.sort(key=lambda c: str(c.get("experiment_id", "")))
    walkforwards.sort(key=lambda w: str(w.get("report_hash", "")))
    baselines.sort(key=lambda b: str(b.get("report_hash", "")))

    return {
        "manifests": manifests,
        "certificates": certificates,
        "walkforwards": walkforwards,
        "baselines": baselines,
        "artifact_hashes": artifact_hashes,
        "issues": issues,
        "warnings": warnings,
    }


def _check_required(
    d: dict[str, Any],
    required: tuple[str, ...],
    label: str,
) -> list[str]:
    """Return issue strings for any missing required fields."""
    return [f"{label}: missing required field '{f}'" for f in required if f not in d]


def _verify_self_hash(d: dict[str, Any], hash_field: str) -> bool:
    """Re-derive the hash and compare to the stored value.

    External artifact types (baseline reports, walk-forward reports) compute
    their self-certifying hash using the legacy default-separator format
    (``json.dumps(..., sort_keys=True)``).  This function matches that format
    via ``legacy_hash`` so that verification is correct for artifacts produced
    by ``baseline_report.py`` and ``walkforward.py``.

    See ``aqcs.utils.canonicalization`` for the full backward-compatibility note.
    """
    stored: str = str(d.get(hash_field, ""))
    d_no_hash: dict[str, Any] = {k: v for k, v in d.items() if k != hash_field}
    recomputed: str = legacy_hash(d_no_hash)
    return stored == recomputed


def _nan(v: Any) -> float:
    """Convert None/NaN to float NaN for internal aggregation."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    return float(v)


def _nan_to_none(d: dict[str, Any]) -> dict[str, Any]:
    """Replace NaN float values with None for JSON serialization."""
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}


def _safe_mean(values: list[float]) -> float:
    finite = [v for v in values if not math.isnan(v)]
    return sum(finite) / len(finite) if finite else float("nan")


def _safe_std(values: list[float]) -> float:
    finite = [v for v in values if not math.isnan(v)]
    if len(finite) < 2:
        return float("nan")
    mean = _safe_mean(finite)
    var = sum((v - mean) ** 2 for v in finite) / (len(finite) - 1)
    return math.sqrt(var)


def _aggregate_baseline_metrics(
    baselines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute aggregate performance metrics across all baseline reports."""
    returns = [_nan(b.get("total_return")) for b in baselines]
    sharpes = [_nan(b.get("sharpe_ratio")) for b in baselines]
    trade_counts = [_nan(b.get("trade_count")) for b in baselines]
    win_rates = [_nan(b.get("win_rate")) for b in baselines]
    profitable = sum(1 for v in returns if not math.isnan(v) and v > 0)
    n = len(baselines)

    return {
        "n_experiments": n,
        "n_profitable": profitable,
        "mean_total_return": _safe_mean(returns),
        "std_total_return": _safe_std(returns),
        "min_total_return": min((v for v in returns if not math.isnan(v)), default=float("nan")),
        "max_total_return": max((v for v in returns if not math.isnan(v)), default=float("nan")),
        "mean_sharpe_ratio": _safe_mean(sharpes),
        "mean_trade_count": _safe_mean(trade_counts),
        "mean_win_rate": _safe_mean(win_rates),
    }


def _aggregate_drawdown(baselines: list[dict[str, Any]]) -> dict[str, Any]:
    drawdowns = [_nan(b.get("max_drawdown")) for b in baselines]
    finite = [v for v in drawdowns if not math.isnan(v)]
    return {
        "mean_max_drawdown": _safe_mean(drawdowns),
        "max_max_drawdown": max(finite, default=float("nan")),
        "min_max_drawdown": min(finite, default=float("nan")),
        "std_max_drawdown": _safe_std(drawdowns),
    }


def _aggregate_turnover(baselines: list[dict[str, Any]]) -> dict[str, Any]:
    turnover = [_nan(b.get("turnover_per_bar")) for b in baselines]
    fees = [_nan(b.get("total_fees_paid")) for b in baselines]
    slippage = [_nan(b.get("total_slippage_cost")) for b in baselines]
    return {
        "mean_turnover_per_bar": _safe_mean(turnover),
        "mean_total_fees_paid": _safe_mean(fees),
        "mean_total_slippage_cost": _safe_mean(slippage),
    }


def _aggregate_exposure(baselines: list[dict[str, Any]]) -> dict[str, Any]:
    exposure = [_nan(b.get("exposure")) for b in baselines]
    holding = [_nan(b.get("avg_holding_period_bars")) for b in baselines]
    return {
        "mean_exposure": _safe_mean(exposure),
        "std_exposure": _safe_std(exposure),
        "mean_avg_holding_period_bars": _safe_mean(holding),
    }


def _aggregate_walkforward(walkforwards: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate walk-forward summary statistics into the metrics dict."""
    total_windows = sum(int(w.get("n_windows", 0)) for w in walkforwards)
    profitable_windows: list[int] = []
    evaluated_windows: list[int] = []
    mean_returns: list[float] = []
    mean_sharpes: list[float] = []
    for w in walkforwards:
        s = w.get("summary", {})
        if isinstance(s, dict):
            profitable_windows.append(int(s.get("n_windows_profitable", 0)))
            evaluated_windows.append(int(s.get("n_windows_evaluated", 0)))
            v = _nan(s.get("mean_total_return"))
            if not math.isnan(v):
                mean_returns.append(v)
            sh = _nan(s.get("mean_sharpe_ratio"))
            if not math.isnan(sh):
                mean_sharpes.append(sh)
    return {
        "wf_n_reports": len(walkforwards),
        "wf_total_windows": total_windows,
        "wf_total_profitable_windows": sum(profitable_windows),
        "wf_total_evaluated_windows": sum(evaluated_windows),
        "wf_mean_window_total_return": _safe_mean(mean_returns),
        "wf_mean_window_sharpe_ratio": _safe_mean(mean_sharpes),
    }


def _compute_campaign_hash(content_dict: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON representation of the campaign content.

    Uses the canonical compact-separator format from
    ``aqcs.utils.canonicalization.canonical_hash``.
    """
    result: str = canonical_hash(content_dict)
    return result
