"""Deterministic benchmark suite infrastructure for AQCS research campaigns.

A BenchmarkSuite is an immutable, self-certifying report that compares one or
more ResearchCampaign JSON artifacts against each other and against explicit,
documented benchmark expectations.

The suite provides:
  - campaign self-hash validation
  - campaign lineage reference validation
  - deterministic campaign comparison metrics
  - transparent, documented scoring
  - deterministic regression flag detection
  - self-certifying benchmark_hash
  - advisory-only ranking (never deployment recommendations)

Safety and scope
----------------
This module NEVER:
  - mutates campaign artifacts
  - selects or recommends strategies for deployment
  - performs parameter optimisation
  - applies ML/RL scoring
  - makes alpha claims
  - generates new strategies

Scoring weights are explicit constants defined in this module, fully auditable
and never derived from data or optimization.

Determinism
-----------
- Campaigns are ordered by ``(campaign_hash, campaign_id)`` before comparison.
- ``benchmark_hash`` excludes ``generation_timestamp_utc`` and itself.
- ``canonical_hash`` from ``aqcs.utils.canonicalization`` is used for hashing.
- NaN is normalized to ``None`` before serialization.
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

from aqcs.research.campaign import (
    ResearchCampaign,
    load_campaign,
    validate_campaign,
)
from aqcs.research.governance_thresholds import (
    DRAWDOWN_CEIL,
    RETURN_FLOOR,
    SCORE_WEIGHT_DRAWDOWN,
    SCORE_WEIGHT_RETURN,
    SCORE_WEIGHT_SHARPE,
    SHARPE_FLOOR,
)
from aqcs.utils.canonicalization import (
    canonical_hash,
    normalize_nan,
)

# ── Version ───────────────────────────────────────────────────────────────────

BENCHMARK_VERSION: str = "1"

# Fixed UUID5 namespace for deterministic benchmark_id derivation.
_BENCHMARK_NS: uuid.UUID = uuid.UUID("b1c2d3e4-f5a6-7890-bcde-f01234567890")

# ── Scoring weights — sourced from governance_thresholds (single source of truth)
# These weights define the AQCS baseline governance scoring function.
# They are ADVISORY ONLY — never used for automated strategy selection.
# Any change requires an ADR and human approval.

SCORE_WEIGHT_TOTAL_RETURN: float = SCORE_WEIGHT_RETURN
SCORE_WEIGHT_MAX_DRAWDOWN: float = SCORE_WEIGHT_DRAWDOWN  # penalises large drawdowns
SCORE_WEIGHT_WF_COVERAGE: float = 0.10  # more walk-forward windows → broader temporal evidence
SCORE_WEIGHT_ISSUE_PENALTY: float = 0.10  # deduct for campaign issues
# SCORE_WEIGHT_SHARPE is imported directly from governance_thresholds

# Regression thresholds — sourced from governance_thresholds (single source of truth).
REGRESSION_RETURN_FLOOR: float = RETURN_FLOOR  # total_return below this → regression flag
REGRESSION_DRAWDOWN_CEIL: float = DRAWDOWN_CEIL  # max_drawdown above this → regression flag
REGRESSION_SHARPE_FLOOR: float = SHARPE_FLOOR  # sharpe_ratio at or below this → regression flag
REGRESSION_ISSUE_CEIL: int = 5  # more than this many issues → regression flag

# Normalisation caps for score components.
_RETURN_CAP: float = 1.0  # cap total_return contribution at 100%
_DRAWDOWN_CAP: float = 1.0  # drawdown penalty saturates at 100%
_SHARPE_CAP: float = 3.0  # cap sharpe contribution (avoid outlier inflation)
_WF_WINDOW_SCALE: float = 100  # 100 windows → full WF score

# ── Data models ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CampaignComparisonEntry:
    """Deterministic benchmark entry for a single campaign.

    ``score`` is a [0, 1] advisory governance score based on the explicit
    weights above.  It is NEVER used for automated strategy selection.
    ``rank`` is 1-indexed, with 1 being the highest scoring campaign.
    ``regression_flags`` lists explicit threshold violations.
    """

    campaign_id: str
    campaign_name: str
    campaign_hash: str
    total_experiments: int
    total_walkforward_windows: int
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    aggregate_metrics: dict[str, Any]
    aggregate_drawdown: dict[str, Any]
    aggregate_turnover: dict[str, Any]
    aggregate_exposure: dict[str, Any]
    score_components: dict[str, float]
    score: float
    rank: int
    regression_flags: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkSuite:
    """Immutable self-certifying benchmark suite report.

    ``benchmark_hash`` is SHA-256 of the report content excluding itself and
    ``generation_timestamp_utc``.  ``benchmark_id`` is a UUID5 of ``benchmark_hash``.

    Rankings in ``comparison_entries`` are advisory only and must not be used
    for automated strategy selection or deployment decisions.
    """

    benchmark_version: str
    benchmark_id: str
    benchmark_name: str
    generation_timestamp_utc: str
    benchmark_hash: str
    campaign_hashes: tuple[str, ...]
    campaign_ids: tuple[str, ...]
    campaign_names: tuple[str, ...]
    total_campaigns: int
    comparison_entries: tuple[CampaignComparisonEntry, ...]
    comparison_metrics: dict[str, Any]
    ranking_metrics: dict[str, Any]
    regression_flags: tuple[str, ...]
    warnings: tuple[str, ...]
    issues: tuple[str, ...]


# ── Public API ────────────────────────────────────────────────────────────────


def build_benchmark_suite(
    campaign_jsons: list[Path],
    benchmark_name: str,
    *,
    now_utc: datetime | None = None,
) -> BenchmarkSuite:
    """Build a deterministic benchmark suite from a list of campaign JSON files.

    Args:
        campaign_jsons: Sorted list of campaign JSON file paths.  The caller
            is responsible for providing a deterministic order; this function
            also re-sorts by ``(campaign_hash, campaign_id)`` for stability.
        benchmark_name: Human-readable benchmark name.
        now_utc: Reference UTC time for ``generation_timestamp_utc``.
            Defaults to ``datetime.now(UTC)``.  Inject a fixed value in tests.

    Returns:
        Immutable, self-certifying ``BenchmarkSuite``.

    Raises:
        ValueError: If no valid campaigns are provided.
    """
    _now = now_utc if now_utc is not None else datetime.now(UTC)
    issues: list[str] = []
    warnings: list[str] = []

    # ── 1. Load and validate each campaign ───────────────────────────────────
    campaigns: list[ResearchCampaign] = []
    seen_hashes: set[str] = set()

    for path in sorted(campaign_jsons):
        try:
            campaign = load_campaign(path)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            issues.append(f"Cannot load campaign '{path.name}': {exc}")
            continue

        # Validate self-certifying hash
        is_valid, hash_errors = validate_campaign(campaign)
        if not is_valid:
            # Filter to only hash/id errors (exclude campaign issues re-raised)
            hash_errors_only = [
                e for e in hash_errors if "campaign_hash" in e or "campaign_id" in e
            ]
            if hash_errors_only:
                issues.append(
                    f"Campaign '{campaign.campaign_name}' failed hash validation: "
                    + "; ".join(hash_errors_only)
                )
                continue

        # Reject duplicates
        if campaign.campaign_hash in seen_hashes:
            issues.append(
                f"Duplicate campaign hash detected: '{campaign.campaign_name}' "
                f"({campaign.campaign_hash[:16]}…) — skipping"
            )
            continue
        seen_hashes.add(campaign.campaign_hash)

        # Record campaign-level issues as warnings (non-blocking for benchmark)
        if campaign.issues:
            warnings.append(
                f"Campaign '{campaign.campaign_name}' has {len(campaign.issues)} recorded issue(s)"
            )

        campaigns.append(campaign)

    if not campaign_jsons:
        raise ValueError("campaign_jsons list is empty.  Provide at least one campaign JSON path.")

    # ── 2. Sort campaigns deterministically by (campaign_hash, campaign_id) ──
    campaigns.sort(key=lambda c: (c.campaign_hash, c.campaign_id))

    # ── 3. Build comparison entries with scores ───────────────────────────────
    raw_entries = [_build_entry(c, rank=0) for c in campaigns]

    # ── 4. Rank by score descending, stable sort preserving hash order ────────
    sorted_entries = sorted(raw_entries, key=lambda e: (-e.score, e.campaign_hash))
    ranked_entries = tuple(_replace_rank(e, rank + 1) for rank, e in enumerate(sorted_entries))

    # ── 5. Collect suite-level regression flags ───────────────────────────────
    regression_flags = tuple(sorted({flag for e in ranked_entries for flag in e.regression_flags}))

    # ── 6. Suite-level comparison metrics ─────────────────────────────────────
    comparison_metrics = _compute_suite_comparison_metrics(ranked_entries)
    ranking_metrics = _compute_ranking_metrics(ranked_entries)

    # ── 7. Build content dict for hashing ────────────────────────────────────
    content_dict: dict[str, Any] = {
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_name": benchmark_name,
        "campaign_hashes": [c.campaign_hash for c in campaigns],
        "campaign_ids": [c.campaign_id for c in campaigns],
        "campaign_names": [c.campaign_name for c in campaigns],
        "total_campaigns": len(campaigns),
        "comparison_metrics": normalize_nan(comparison_metrics),
        "ranking_metrics": normalize_nan(ranking_metrics),
        "regression_flags": sorted(regression_flags),
        "score_weights": {
            "total_return": SCORE_WEIGHT_TOTAL_RETURN,
            "max_drawdown": SCORE_WEIGHT_MAX_DRAWDOWN,
            "sharpe": SCORE_WEIGHT_SHARPE,
            "wf_coverage": SCORE_WEIGHT_WF_COVERAGE,
            "issue_penalty": SCORE_WEIGHT_ISSUE_PENALTY,
        },
        "regression_thresholds": {
            "return_floor": REGRESSION_RETURN_FLOOR,
            "drawdown_ceil": REGRESSION_DRAWDOWN_CEIL,
            "sharpe_floor": REGRESSION_SHARPE_FLOOR,
            "issue_ceil": REGRESSION_ISSUE_CEIL,
        },
        "issues": sorted(issues),
        "warnings": sorted(warnings),
        "comparison_entries": [_entry_to_dict(e) for e in ranked_entries],
    }

    benchmark_hash = canonical_hash(content_dict)
    benchmark_id = str(uuid.uuid5(_BENCHMARK_NS, benchmark_hash))

    return BenchmarkSuite(
        benchmark_version=BENCHMARK_VERSION,
        benchmark_id=benchmark_id,
        benchmark_name=benchmark_name,
        generation_timestamp_utc=_now.isoformat(),
        benchmark_hash=benchmark_hash,
        campaign_hashes=tuple(c.campaign_hash for c in campaigns),
        campaign_ids=tuple(c.campaign_id for c in campaigns),
        campaign_names=tuple(c.campaign_name for c in campaigns),
        total_campaigns=len(campaigns),
        comparison_entries=ranked_entries,
        comparison_metrics=comparison_metrics,
        ranking_metrics=ranking_metrics,
        regression_flags=regression_flags,
        warnings=tuple(sorted(warnings)),
        issues=tuple(sorted(issues)),
    )


def validate_benchmark(suite: BenchmarkSuite) -> tuple[bool, list[str]]:
    """Validate a benchmark suite's self-certifying hash and consistency.

    Returns:
        ``(is_valid, errors)`` — errors is empty when valid.
    """
    errors: list[str] = []

    d = benchmark_to_dict(suite)
    # Exclude the same fields that were excluded during build:
    # benchmark_hash (self-reference), benchmark_id (derived from hash),
    # generation_timestamp_utc (wall-clock only).
    d_no_hash = {
        k: v
        for k, v in d.items()
        if k not in {"benchmark_hash", "benchmark_id", "generation_timestamp_utc"}
    }
    expected = canonical_hash(d_no_hash)
    if expected != suite.benchmark_hash:
        errors.append(
            f"benchmark_hash mismatch: stored={suite.benchmark_hash[:16]}… "
            f"recomputed={expected[:16]}…"
        )

    expected_id = str(uuid.uuid5(_BENCHMARK_NS, suite.benchmark_hash))
    if expected_id != suite.benchmark_id:
        errors.append(
            f"benchmark_id mismatch: stored={suite.benchmark_id} " f"recomputed={expected_id}"
        )

    if suite.benchmark_version != BENCHMARK_VERSION:
        errors.append(
            f"benchmark_version '{suite.benchmark_version}' != current '{BENCHMARK_VERSION}'"
        )

    if suite.total_campaigns != len(suite.comparison_entries):
        errors.append(
            f"total_campaigns ({suite.total_campaigns}) != "
            f"len(comparison_entries) ({len(suite.comparison_entries)})"
        )

    return len(errors) == 0, errors


def benchmark_to_dict(suite: BenchmarkSuite) -> dict[str, Any]:
    """Return a JSON-serializable dict from a ``BenchmarkSuite``."""

    def _f(v: Any) -> Any:
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    def _clean(d: dict[str, Any]) -> dict[str, Any]:
        return {k: _f(v) for k, v in d.items()}

    return {
        "benchmark_version": suite.benchmark_version,
        "benchmark_id": suite.benchmark_id,
        "benchmark_name": suite.benchmark_name,
        "generation_timestamp_utc": suite.generation_timestamp_utc,
        "benchmark_hash": suite.benchmark_hash,
        "campaign_hashes": list(suite.campaign_hashes),
        "campaign_ids": list(suite.campaign_ids),
        "campaign_names": list(suite.campaign_names),
        "total_campaigns": suite.total_campaigns,
        "comparison_metrics": _clean(suite.comparison_metrics),
        "ranking_metrics": _clean(suite.ranking_metrics),
        "regression_flags": list(suite.regression_flags),
        "warnings": list(suite.warnings),
        "issues": list(suite.issues),
        "score_weights": {
            "total_return": SCORE_WEIGHT_TOTAL_RETURN,
            "max_drawdown": SCORE_WEIGHT_MAX_DRAWDOWN,
            "sharpe": SCORE_WEIGHT_SHARPE,
            "wf_coverage": SCORE_WEIGHT_WF_COVERAGE,
            "issue_penalty": SCORE_WEIGHT_ISSUE_PENALTY,
        },
        "regression_thresholds": {
            "return_floor": REGRESSION_RETURN_FLOOR,
            "drawdown_ceil": REGRESSION_DRAWDOWN_CEIL,
            "sharpe_floor": REGRESSION_SHARPE_FLOOR,
            "issue_ceil": REGRESSION_ISSUE_CEIL,
        },
        "comparison_entries": [_entry_to_dict(e) for e in suite.comparison_entries],
    }


def benchmark_from_dict(d: dict[str, Any]) -> BenchmarkSuite:
    """Reconstruct a ``BenchmarkSuite`` from a dict.

    Raises:
        KeyError: If any required field is missing.
    """

    def _fn(v: Any) -> Any:
        return float("nan") if v is None else v

    def _restore(d2: dict[str, Any]) -> dict[str, Any]:
        return {k: _fn(v) for k, v in d2.items()}

    entries = tuple(
        CampaignComparisonEntry(
            campaign_id=str(e["campaign_id"]),
            campaign_name=str(e["campaign_name"]),
            campaign_hash=str(e["campaign_hash"]),
            total_experiments=int(e["total_experiments"]),
            total_walkforward_windows=int(e["total_walkforward_windows"]),
            symbols=tuple(str(s) for s in e["symbols"]),
            timeframes=tuple(str(t) for t in e["timeframes"]),
            aggregate_metrics=_restore(dict(e["aggregate_metrics"])),
            aggregate_drawdown=_restore(dict(e["aggregate_drawdown"])),
            aggregate_turnover=_restore(dict(e["aggregate_turnover"])),
            aggregate_exposure=_restore(dict(e["aggregate_exposure"])),
            score_components=dict(e["score_components"]),
            score=float(e["score"]),
            rank=int(e["rank"]),
            regression_flags=tuple(str(f) for f in e["regression_flags"]),
        )
        for e in d["comparison_entries"]
    )

    return BenchmarkSuite(
        benchmark_version=str(d["benchmark_version"]),
        benchmark_id=str(d["benchmark_id"]),
        benchmark_name=str(d["benchmark_name"]),
        generation_timestamp_utc=str(d["generation_timestamp_utc"]),
        benchmark_hash=str(d["benchmark_hash"]),
        campaign_hashes=tuple(str(h) for h in d["campaign_hashes"]),
        campaign_ids=tuple(str(i) for i in d["campaign_ids"]),
        campaign_names=tuple(str(n) for n in d["campaign_names"]),
        total_campaigns=int(d["total_campaigns"]),
        comparison_entries=entries,
        comparison_metrics=_restore(dict(d["comparison_metrics"])),
        ranking_metrics=_restore(dict(d["ranking_metrics"])),
        regression_flags=tuple(str(f) for f in d["regression_flags"]),
        warnings=tuple(str(w) for w in d["warnings"]),
        issues=tuple(str(i) for i in d["issues"]),
    )


def save_benchmark(suite: BenchmarkSuite, path: Path) -> None:
    """Write a benchmark suite to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(benchmark_to_dict(suite), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_benchmark(path: Path) -> BenchmarkSuite:
    """Load a benchmark suite from a JSON file.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the file is not valid JSON or is missing required fields.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in benchmark file '{path}': {exc}") from exc
    return benchmark_from_dict(raw)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _nan(v: Any) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    return float(v)


def _clamp(v: float, lo: float, hi: float) -> float:
    if math.isnan(v):
        return 0.0
    return max(lo, min(hi, v))


def _compute_score(campaign: ResearchCampaign) -> tuple[float, dict[str, float]]:
    """Compute an advisory governance score for one campaign.

    Scoring formula (all components in [0, 1], weights sum to 1.0):

      score = (
          SCORE_WEIGHT_TOTAL_RETURN   * return_component    +
          SCORE_WEIGHT_MAX_DRAWDOWN   * (1 - drawdown_component) +
          SCORE_WEIGHT_SHARPE         * sharpe_component    +
          SCORE_WEIGHT_WF_COVERAGE    * wf_component        +
          SCORE_WEIGHT_ISSUE_PENALTY  * (1 - issue_component)
      )

    All components are [0, 1].  The drawdown and issue penalty terms are
    SUBTRACTED (higher drawdown/more issues → lower score).

    This scoring is ADVISORY ONLY.  The weights are explicit constants; no
    learning, adaptation, or optimisation is applied.
    """
    am = campaign.aggregate_metrics
    ad = campaign.aggregate_drawdown

    mean_return = _nan(am.get("mean_total_return"))
    mean_drawdown = _nan(ad.get("mean_max_drawdown"))
    mean_sharpe = _nan(am.get("mean_sharpe_ratio"))
    wf_windows = campaign.total_walkforward_windows
    issue_count = len(campaign.issues)

    # Return component: normalise to [0, 1] capped at _RETURN_CAP
    return_component = _clamp(
        (mean_return / _RETURN_CAP if not math.isnan(mean_return) else 0.0),
        0.0,
        1.0,
    )

    # Drawdown component: higher drawdown → higher penalty (capped at 1)
    drawdown_component = _clamp(
        (mean_drawdown / _DRAWDOWN_CAP if not math.isnan(mean_drawdown) else 0.0),
        0.0,
        1.0,
    )

    # Sharpe component: normalise to [0, 1] capped at _SHARPE_CAP
    sharpe_component = _clamp(
        (mean_sharpe / _SHARPE_CAP if not math.isnan(mean_sharpe) else 0.0),
        0.0,
        1.0,
    )

    # Walk-forward coverage component: scale by _WF_WINDOW_SCALE
    wf_component = _clamp(wf_windows / _WF_WINDOW_SCALE, 0.0, 1.0)

    # Issue penalty component: linear penalty up to REGRESSION_ISSUE_CEIL
    issue_component = _clamp(issue_count / max(REGRESSION_ISSUE_CEIL, 1), 0.0, 1.0)

    score = (
        SCORE_WEIGHT_TOTAL_RETURN * return_component
        + SCORE_WEIGHT_MAX_DRAWDOWN * (1.0 - drawdown_component)
        + SCORE_WEIGHT_SHARPE * sharpe_component
        + SCORE_WEIGHT_WF_COVERAGE * wf_component
        + SCORE_WEIGHT_ISSUE_PENALTY * (1.0 - issue_component)
    )

    components: dict[str, float] = {
        "return_component": return_component,
        "drawdown_component": drawdown_component,
        "sharpe_component": sharpe_component,
        "wf_component": wf_component,
        "issue_component": issue_component,
    }

    return round(score, 8), components


def _compute_regression_flags(campaign: ResearchCampaign) -> tuple[str, ...]:
    """Return explicit regression flag strings for a campaign."""
    flags: list[str] = []
    am = campaign.aggregate_metrics
    ad = campaign.aggregate_drawdown

    mean_return = _nan(am.get("mean_total_return"))
    mean_drawdown = _nan(ad.get("mean_max_drawdown"))
    mean_sharpe = _nan(am.get("mean_sharpe_ratio"))
    issue_count = len(campaign.issues)

    if not math.isnan(mean_return) and mean_return < REGRESSION_RETURN_FLOOR:
        flags.append(f"mean_total_return {mean_return:.4f} < floor {REGRESSION_RETURN_FLOOR}")
    if not math.isnan(mean_drawdown) and mean_drawdown > REGRESSION_DRAWDOWN_CEIL:
        flags.append(f"mean_max_drawdown {mean_drawdown:.4f} > ceiling {REGRESSION_DRAWDOWN_CEIL}")
    if not math.isnan(mean_sharpe) and mean_sharpe <= REGRESSION_SHARPE_FLOOR:
        flags.append(f"mean_sharpe_ratio {mean_sharpe:.4f} <= floor {REGRESSION_SHARPE_FLOOR}")
    if issue_count > REGRESSION_ISSUE_CEIL:
        flags.append(f"campaign has {issue_count} issues > ceiling {REGRESSION_ISSUE_CEIL}")

    return tuple(sorted(flags))


def _build_entry(campaign: ResearchCampaign, rank: int) -> CampaignComparisonEntry:
    """Build a comparison entry (rank is a placeholder, set to 0 initially)."""
    score, components = _compute_score(campaign)
    flags = _compute_regression_flags(campaign)
    return CampaignComparisonEntry(
        campaign_id=campaign.campaign_id,
        campaign_name=campaign.campaign_name,
        campaign_hash=campaign.campaign_hash,
        total_experiments=campaign.total_experiments,
        total_walkforward_windows=campaign.total_walkforward_windows,
        symbols=campaign.symbols,
        timeframes=campaign.timeframes,
        aggregate_metrics=dict(campaign.aggregate_metrics),
        aggregate_drawdown=dict(campaign.aggregate_drawdown),
        aggregate_turnover=dict(campaign.aggregate_turnover),
        aggregate_exposure=dict(campaign.aggregate_exposure),
        score_components=components,
        score=score,
        rank=rank,
        regression_flags=flags,
    )


def _replace_rank(entry: CampaignComparisonEntry, rank: int) -> CampaignComparisonEntry:
    """Return a new entry with the updated rank (frozen dataclass)."""
    return CampaignComparisonEntry(
        campaign_id=entry.campaign_id,
        campaign_name=entry.campaign_name,
        campaign_hash=entry.campaign_hash,
        total_experiments=entry.total_experiments,
        total_walkforward_windows=entry.total_walkforward_windows,
        symbols=entry.symbols,
        timeframes=entry.timeframes,
        aggregate_metrics=entry.aggregate_metrics,
        aggregate_drawdown=entry.aggregate_drawdown,
        aggregate_turnover=entry.aggregate_turnover,
        aggregate_exposure=entry.aggregate_exposure,
        score_components=entry.score_components,
        score=entry.score,
        rank=rank,
        regression_flags=entry.regression_flags,
    )


def _compute_suite_comparison_metrics(
    entries: tuple[CampaignComparisonEntry, ...],
) -> dict[str, Any]:
    """Compute suite-level aggregate comparison statistics."""
    scores = [e.score for e in entries]
    returns = [_nan(e.aggregate_metrics.get("mean_total_return")) for e in entries]
    drawdowns = [_nan(e.aggregate_drawdown.get("mean_max_drawdown")) for e in entries]
    sharpes = [_nan(e.aggregate_metrics.get("mean_sharpe_ratio")) for e in entries]
    finite_r = [v for v in returns if not math.isnan(v)]
    finite_d = [v for v in drawdowns if not math.isnan(v)]
    finite_s = [v for v in sharpes if not math.isnan(v)]
    n = len(entries)

    return {
        "n_campaigns": n,
        "n_with_regressions": sum(1 for e in entries if e.regression_flags),
        "mean_score": sum(scores) / n if n else float("nan"),
        "max_score": max(scores) if scores else float("nan"),
        "min_score": min(scores) if scores else float("nan"),
        "mean_return_across_campaigns": sum(finite_r) / len(finite_r) if finite_r else float("nan"),
        "mean_drawdown_across_campaigns": (
            sum(finite_d) / len(finite_d) if finite_d else float("nan")
        ),
        "mean_sharpe_across_campaigns": sum(finite_s) / len(finite_s) if finite_s else float("nan"),
    }


def _compute_ranking_metrics(
    entries: tuple[CampaignComparisonEntry, ...],
) -> dict[str, Any]:
    """Produce ranking metadata (advisory only)."""
    if not entries:
        return {"top_campaign_id": None, "top_campaign_name": None, "top_score": float("nan")}
    top = min(entries, key=lambda e: e.rank)
    return {
        "top_campaign_id": top.campaign_id,
        "top_campaign_name": top.campaign_name,
        "top_score": top.score,
        "advisory_disclaimer": (
            "Rankings are for governance review ONLY. "
            "They do not constitute deployment recommendations."
        ),
    }


def _entry_to_dict(entry: CampaignComparisonEntry) -> dict[str, Any]:
    def _f(v: Any) -> Any:
        return None if isinstance(v, float) and math.isnan(v) else v

    def _clean(d: dict[str, Any]) -> dict[str, Any]:
        return {k: _f(v) for k, v in d.items()}

    return {
        "campaign_id": entry.campaign_id,
        "campaign_name": entry.campaign_name,
        "campaign_hash": entry.campaign_hash,
        "total_experiments": entry.total_experiments,
        "total_walkforward_windows": entry.total_walkforward_windows,
        "symbols": list(entry.symbols),
        "timeframes": list(entry.timeframes),
        "aggregate_metrics": _clean(entry.aggregate_metrics),
        "aggregate_drawdown": _clean(entry.aggregate_drawdown),
        "aggregate_turnover": _clean(entry.aggregate_turnover),
        "aggregate_exposure": _clean(entry.aggregate_exposure),
        "score_components": dict(entry.score_components),
        "score": entry.score,
        "rank": entry.rank,
        "regression_flags": list(entry.regression_flags),
    }
