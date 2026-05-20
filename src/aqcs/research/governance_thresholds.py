"""Single-source governance threshold and scoring-weight constants for AQCS research.

This module is the canonical source of truth for governance constants shared
across research modules.  Modules that previously defined these values locally
now import from here, eliminating the silent drift risk from duplicated magic
numbers.

Constants defined here
----------------------
Governance thresholds (floor / ceiling values):
  RETURN_FLOOR     — total_return below this value is a governance concern
  DRAWDOWN_CEIL    — max_drawdown above this value is a governance concern
  SHARPE_FLOOR     — sharpe_ratio at or below this value is a governance concern

Benchmark scoring weights (advisory only):
  SCORE_WEIGHT_RETURN    — return component weight in the governance score
  SCORE_WEIGHT_DRAWDOWN  — drawdown component weight (penalty)
  SCORE_WEIGHT_SHARPE    — sharpe component weight

Change governance
-----------------
Any modification to these constants requires:
  1. An ADR in docs/decisions/ explaining the rationale.
  2. Explicit human approval before the ADR is committed.

These values are advisory governance parameters.  They are NEVER used for
automated strategy selection, live trading authorisation, or order execution.

Intentionally NOT here
-----------------------
- Severity level strings (regression_guard and sensitivity_audit use
  intentionally different severity systems; see docs/governance/ for the
  distinction between the three-level comparison-severity system and the
  four-level instability-magnitude system).
- Instability thresholds (INSTABILITY_*) — specific to sensitivity_audit.
- Drift thresholds (DRIFT_THRESHOLD_*) — specific to regression_guard.
- Issue counts (REGRESSION_ISSUE_CEIL) — specific to benchmark_suite.
- Score normalisation caps (_*_CAP) — implementation details of benchmark_suite.

Determinism
-----------
All values are Python float/int literals.  No runtime computation, no
environment-sensitive loading, no defaults from config files.
"""

from __future__ import annotations

# ── Governance floor / ceiling thresholds ─────────────────────────────────────
# Any change requires an ADR and explicit human approval.

RETURN_FLOOR: float = -0.10
"""total_return at or below which a governance concern is raised.

Used by benchmark_suite (REGRESSION_RETURN_FLOOR) and sensitivity_audit
(GOVERNANCE_RETURN_FLOOR).  A -10 % absolute return floor is the Phase-1B
minimum acceptability threshold for Phase-1 daily-bar strategies.
"""

DRAWDOWN_CEIL: float = 0.30
"""max_drawdown at or above which a governance concern is raised.

A 30 % drawdown ceiling reflects the Phase-1B tolerance for unrealised loss
in a long-only daily strategy.  Exceeding this threshold does not
auto-reject a strategy but requires explicit human review.
"""

SHARPE_FLOOR: float = 0.0
"""sharpe_ratio at or below which a governance concern is raised.

A Sharpe of zero or below means the strategy does not compensate for
volatility.  Phase-1B requires a positive risk-adjusted return to proceed.
"""

# ── Benchmark scoring weights (advisory, never used for automated decisions) ──
# Must sum to ≤ 1.0 (with SCORE_WEIGHT_WF_COVERAGE and SCORE_WEIGHT_ISSUE_PENALTY
# in benchmark_suite accounting for the remainder).
# Any change requires an ADR and explicit human approval.

SCORE_WEIGHT_RETURN: float = 0.30
"""Return component weight in the advisory governance score."""

SCORE_WEIGHT_DRAWDOWN: float = 0.25
"""Drawdown penalty component weight in the advisory governance score."""

SCORE_WEIGHT_SHARPE: float = 0.25
"""Sharpe component weight in the advisory governance score."""
