"""Governance regression tests for consolidated threshold and scoring-weight constants.

These tests verify that:
1. governance_thresholds.py is the single source of truth for shared constants.
2. benchmark_suite.py re-exports the canonical values under its own names.
3. sensitivity_audit.py re-exports the canonical values under its own names.
4. The three modules are always in sync — a change to governance_thresholds.py
   is automatically reflected everywhere.
5. The scoring weights sum to the expected total.
6. The severity systems in regression_guard.py and sensitivity_audit.py are
   intentionally distinct and remain unchanged.

Corruption classes guarded:
- Silent drift between benchmark_suite and sensitivity_audit governance thresholds
- Silent drift between benchmark_suite and sensitivity_audit scoring weights
- Accidental mutation of governance threshold values
- Severity string value changes in either module
"""

from __future__ import annotations

from aqcs.research.benchmark_suite import (
    REGRESSION_DRAWDOWN_CEIL,
    REGRESSION_RETURN_FLOOR,
    REGRESSION_SHARPE_FLOOR,
    SCORE_WEIGHT_MAX_DRAWDOWN,
    SCORE_WEIGHT_SHARPE,
    SCORE_WEIGHT_TOTAL_RETURN,
)
from aqcs.research.governance_thresholds import (
    DRAWDOWN_CEIL as _DRAWDOWN_CEIL,
)
from aqcs.research.governance_thresholds import (
    RETURN_FLOOR as _RETURN_FLOOR,
)
from aqcs.research.governance_thresholds import (
    SCORE_WEIGHT_DRAWDOWN as _SW_DRAWDOWN,
)
from aqcs.research.governance_thresholds import (
    SCORE_WEIGHT_RETURN as _SW_RETURN,
)
from aqcs.research.governance_thresholds import (
    SCORE_WEIGHT_SHARPE as _SW_SHARPE,
)
from aqcs.research.governance_thresholds import (
    SHARPE_FLOOR as _SHARPE_FLOOR,
)
from aqcs.research.regression_guard import (
    SEVERITY_CRITICAL as RG_SEVERITY_CRITICAL,
)
from aqcs.research.regression_guard import (
    SEVERITY_INFO as RG_SEVERITY_INFO,
)
from aqcs.research.regression_guard import (
    SEVERITY_WARNING as RG_SEVERITY_WARNING,
)
from aqcs.research.sensitivity_audit import (
    _BENCH_WEIGHT_DRAWDOWN,
    _BENCH_WEIGHT_RETURN,
    _BENCH_WEIGHT_SHARPE,
    GOVERNANCE_DRAWDOWN_CEIL,
    GOVERNANCE_RETURN_FLOOR,
    GOVERNANCE_SHARPE_FLOOR,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from aqcs.research.sensitivity_audit import (
    SEVERITY_CRITICAL as SA_SEVERITY_CRITICAL,
)

# ── Canonical values regression ──────────────────────────────────────────────


class TestCanonicalValues:
    """governance_thresholds.py holds the correct canonical values."""

    def test_return_floor_value(self) -> None:
        assert _RETURN_FLOOR == -0.10, f"RETURN_FLOOR must be -0.10. Got: {_RETURN_FLOOR}"

    def test_drawdown_ceil_value(self) -> None:
        assert _DRAWDOWN_CEIL == 0.30, f"DRAWDOWN_CEIL must be 0.30. Got: {_DRAWDOWN_CEIL}"

    def test_sharpe_floor_value(self) -> None:
        assert _SHARPE_FLOOR == 0.0, f"SHARPE_FLOOR must be 0.0. Got: {_SHARPE_FLOOR}"

    def test_score_weight_return_value(self) -> None:
        assert _SW_RETURN == 0.30, f"SCORE_WEIGHT_RETURN must be 0.30. Got: {_SW_RETURN}"

    def test_score_weight_drawdown_value(self) -> None:
        assert _SW_DRAWDOWN == 0.25, f"SCORE_WEIGHT_DRAWDOWN must be 0.25. Got: {_SW_DRAWDOWN}"

    def test_score_weight_sharpe_value(self) -> None:
        assert _SW_SHARPE == 0.25, f"SCORE_WEIGHT_SHARPE must be 0.25. Got: {_SW_SHARPE}"


# ── benchmark_suite re-export consistency ────────────────────────────────────


class TestBenchmarkSuiteReExports:
    """benchmark_suite.py constants match governance_thresholds.py values."""

    def test_regression_return_floor_matches_canonical(self) -> None:
        assert REGRESSION_RETURN_FLOOR == _RETURN_FLOOR, (
            f"benchmark_suite.REGRESSION_RETURN_FLOOR ({REGRESSION_RETURN_FLOOR}) "
            f"!= _RETURN_FLOOR ({_RETURN_FLOOR}). "
            "Change the canonical value in governance_thresholds.py, not here."
        )

    def test_regression_drawdown_ceil_matches_canonical(self) -> None:
        assert REGRESSION_DRAWDOWN_CEIL == _DRAWDOWN_CEIL, (
            f"benchmark_suite.REGRESSION_DRAWDOWN_CEIL ({REGRESSION_DRAWDOWN_CEIL}) "
            f"!= _DRAWDOWN_CEIL ({_DRAWDOWN_CEIL})."
        )

    def test_regression_sharpe_floor_matches_canonical(self) -> None:
        assert REGRESSION_SHARPE_FLOOR == _SHARPE_FLOOR, (
            f"benchmark_suite.REGRESSION_SHARPE_FLOOR ({REGRESSION_SHARPE_FLOOR}) "
            f"!= _SHARPE_FLOOR ({_SHARPE_FLOOR})."
        )

    def test_score_weight_total_return_matches_canonical(self) -> None:
        assert SCORE_WEIGHT_TOTAL_RETURN == _SW_RETURN, (
            f"benchmark_suite.SCORE_WEIGHT_TOTAL_RETURN ({SCORE_WEIGHT_TOTAL_RETURN}) "
            f"!= _SW_RETURN ({_SW_RETURN})."
        )

    def test_score_weight_max_drawdown_matches_canonical(self) -> None:
        assert SCORE_WEIGHT_MAX_DRAWDOWN == _SW_DRAWDOWN, (
            f"benchmark_suite.SCORE_WEIGHT_MAX_DRAWDOWN ({SCORE_WEIGHT_MAX_DRAWDOWN}) "
            f"!= _SW_DRAWDOWN ({_SW_DRAWDOWN})."
        )

    def test_score_weight_sharpe_matches_canonical(self) -> None:
        assert SCORE_WEIGHT_SHARPE == _SW_SHARPE, (
            f"benchmark_suite.SCORE_WEIGHT_SHARPE ({SCORE_WEIGHT_SHARPE}) "
            f"!= _SW_SHARPE ({_SW_SHARPE})."
        )


# ── sensitivity_audit re-export consistency ──────────────────────────────────


class TestSensitivityAuditReExports:
    """sensitivity_audit.py constants match governance_thresholds.py values."""

    def test_governance_return_floor_matches_canonical(self) -> None:
        assert GOVERNANCE_RETURN_FLOOR == _RETURN_FLOOR, (
            f"sensitivity_audit.GOVERNANCE_RETURN_FLOOR ({GOVERNANCE_RETURN_FLOOR}) "
            f"!= _RETURN_FLOOR ({_RETURN_FLOOR})."
        )

    def test_governance_drawdown_ceil_matches_canonical(self) -> None:
        assert GOVERNANCE_DRAWDOWN_CEIL == _DRAWDOWN_CEIL, (
            f"sensitivity_audit.GOVERNANCE_DRAWDOWN_CEIL ({GOVERNANCE_DRAWDOWN_CEIL}) "
            f"!= _DRAWDOWN_CEIL ({_DRAWDOWN_CEIL})."
        )

    def test_governance_sharpe_floor_matches_canonical(self) -> None:
        assert GOVERNANCE_SHARPE_FLOOR == _SHARPE_FLOOR, (
            f"sensitivity_audit.GOVERNANCE_SHARPE_FLOOR ({GOVERNANCE_SHARPE_FLOOR}) "
            f"!= _SHARPE_FLOOR ({_SHARPE_FLOOR})."
        )

    def test_bench_weight_return_matches_canonical(self) -> None:
        assert _BENCH_WEIGHT_RETURN == _SW_RETURN, (
            f"sensitivity_audit._BENCH_WEIGHT_RETURN ({_BENCH_WEIGHT_RETURN}) "
            f"!= _SW_RETURN ({_SW_RETURN})."
        )

    def test_bench_weight_drawdown_matches_canonical(self) -> None:
        assert _BENCH_WEIGHT_DRAWDOWN == _SW_DRAWDOWN, (
            f"sensitivity_audit._BENCH_WEIGHT_DRAWDOWN ({_BENCH_WEIGHT_DRAWDOWN}) "
            f"!= _SW_DRAWDOWN ({_SW_DRAWDOWN})."
        )

    def test_bench_weight_sharpe_matches_canonical(self) -> None:
        assert _BENCH_WEIGHT_SHARPE == _SW_SHARPE, (
            f"sensitivity_audit._BENCH_WEIGHT_SHARPE ({_BENCH_WEIGHT_SHARPE}) "
            f"!= _SW_SHARPE ({_SW_SHARPE})."
        )


# ── Cross-module consistency ──────────────────────────────────────────────────


class TestCrossModuleConsistency:
    """benchmark_suite and sensitivity_audit governance constants are identical."""

    def test_return_floor_consistent_across_modules(self) -> None:
        assert REGRESSION_RETURN_FLOOR == GOVERNANCE_RETURN_FLOOR, (
            f"Return floor diverged: benchmark_suite={REGRESSION_RETURN_FLOOR}, "
            f"sensitivity_audit={GOVERNANCE_RETURN_FLOOR}. "
            "Both should equal governance_thresholds.RETURN_FLOOR."
        )

    def test_drawdown_ceil_consistent_across_modules(self) -> None:
        assert REGRESSION_DRAWDOWN_CEIL == GOVERNANCE_DRAWDOWN_CEIL, (
            f"Drawdown ceiling diverged: benchmark_suite={REGRESSION_DRAWDOWN_CEIL}, "
            f"sensitivity_audit={GOVERNANCE_DRAWDOWN_CEIL}."
        )

    def test_sharpe_floor_consistent_across_modules(self) -> None:
        assert REGRESSION_SHARPE_FLOOR == GOVERNANCE_SHARPE_FLOOR, (
            f"Sharpe floor diverged: benchmark_suite={REGRESSION_SHARPE_FLOOR}, "
            f"sensitivity_audit={GOVERNANCE_SHARPE_FLOOR}."
        )

    def test_scoring_weights_consistent_across_modules(self) -> None:
        assert SCORE_WEIGHT_TOTAL_RETURN == _BENCH_WEIGHT_RETURN, (
            f"Return weight diverged: benchmark_suite={SCORE_WEIGHT_TOTAL_RETURN}, "
            f"sensitivity_audit={_BENCH_WEIGHT_RETURN}."
        )
        assert SCORE_WEIGHT_MAX_DRAWDOWN == _BENCH_WEIGHT_DRAWDOWN, (
            f"Drawdown weight diverged: benchmark_suite={SCORE_WEIGHT_MAX_DRAWDOWN}, "
            f"sensitivity_audit={_BENCH_WEIGHT_DRAWDOWN}."
        )
        assert SCORE_WEIGHT_SHARPE == _BENCH_WEIGHT_SHARPE, (
            f"Sharpe weight diverged: benchmark_suite={SCORE_WEIGHT_SHARPE}, "
            f"sensitivity_audit={_BENCH_WEIGHT_SHARPE}."
        )


# ── Scoring weight sum constraint ────────────────────────────────────────────


class TestScoringWeightConstraints:
    """Governance scoring weights sum to the documented total."""

    def test_main_three_weights_sum_to_080(self) -> None:
        """The three main weights (return + drawdown + sharpe) must sum to 0.80.

        The remaining 0.20 is allocated to walk-forward coverage (0.10) and
        issue penalty (0.10) in benchmark_suite.py.
        """
        total = _SW_RETURN + _SW_DRAWDOWN + _SW_SHARPE
        assert abs(total - 0.80) < 1e-10, (
            f"SCORE_WEIGHT_RETURN + SCORE_WEIGHT_DRAWDOWN + SCORE_WEIGHT_SHARPE "
            f"must equal 0.80. Got: {total}"
        )


# ── Severity system distinctness ─────────────────────────────────────────────


class TestSeveritySystemDistinctness:
    """The two severity systems must remain intentionally distinct."""

    def test_regression_guard_uses_lowercase_severity(self) -> None:
        """regression_guard uses lowercase severity strings (comparison domain)."""
        assert RG_SEVERITY_CRITICAL == "critical", (
            f"regression_guard.SEVERITY_CRITICAL must be lowercase 'critical'. "
            f"Got: {RG_SEVERITY_CRITICAL!r}"
        )
        assert RG_SEVERITY_WARNING == "warning"
        assert RG_SEVERITY_INFO == "info"

    def test_sensitivity_audit_uses_uppercase_severity(self) -> None:
        """sensitivity_audit uses uppercase severity strings (instability domain)."""
        assert SA_SEVERITY_CRITICAL == "CRITICAL", (
            f"sensitivity_audit.SEVERITY_CRITICAL must be uppercase 'CRITICAL'. "
            f"Got: {SA_SEVERITY_CRITICAL!r}"
        )
        assert SEVERITY_HIGH == "HIGH"
        assert SEVERITY_MEDIUM == "MEDIUM"
        assert SEVERITY_LOW == "LOW"

    def test_severity_systems_do_not_overlap(self) -> None:
        """The string values in the two systems must never collide."""
        rg_values = {RG_SEVERITY_CRITICAL, RG_SEVERITY_WARNING, RG_SEVERITY_INFO}
        sa_values = {SA_SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW}
        overlap = rg_values & sa_values
        assert not overlap, (
            f"Severity string values overlap between regression_guard and "
            f"sensitivity_audit: {overlap}. These systems must remain distinct "
            "to avoid misclassification when findings are compared."
        )
