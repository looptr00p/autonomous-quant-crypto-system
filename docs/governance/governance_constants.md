# Governance Constants Reference

**Task:** TASK-GOVERNANCE-CONSOLIDATION-001  
**Date:** 2026-05-19  
**Status:** Implemented

---

## Overview

This document describes the AQCS governance constant system after the
Phase-1B consolidation performed in TASK-GOVERNANCE-CONSOLIDATION-001.

Prior to consolidation, identical governance threshold values were defined
independently in both `benchmark_suite.py` and `sensitivity_audit.py`, with
explicit "MUST stay in sync" comments that relied on manual discipline to
prevent silent drift. This task eliminated that risk.

---

## Single Source of Truth

`src/aqcs/research/governance_thresholds.py` is the canonical source for
governance thresholds and benchmark scoring weights shared across research
modules.

**Change governance:** Any modification to values in this file requires:
1. An ADR in `docs/decisions/` explaining the rationale.
2. Explicit human approval before the ADR is committed.

---

## Governance Thresholds

| Canonical name | Value | Description |
|---|---|---|
| `RETURN_FLOOR` | `-0.10` | total_return at or below which governance raises a concern |
| `DRAWDOWN_CEIL` | `0.30` | max_drawdown at or above which governance raises a concern |
| `SHARPE_FLOOR` | `0.0` | sharpe_ratio at or below which governance raises a concern |

These thresholds reflect Phase-1B acceptability bounds for long-only daily
strategies. Exceeding these bounds does not auto-reject; it flags for human review.

### Re-exports by consuming modules

| Module | Local name | Maps to |
|---|---|---|
| `benchmark_suite` | `REGRESSION_RETURN_FLOOR` | `RETURN_FLOOR` |
| `benchmark_suite` | `REGRESSION_DRAWDOWN_CEIL` | `DRAWDOWN_CEIL` |
| `benchmark_suite` | `REGRESSION_SHARPE_FLOOR` | `SHARPE_FLOOR` |
| `sensitivity_audit` | `GOVERNANCE_RETURN_FLOOR` | `RETURN_FLOOR` |
| `sensitivity_audit` | `GOVERNANCE_DRAWDOWN_CEIL` | `DRAWDOWN_CEIL` |
| `sensitivity_audit` | `GOVERNANCE_SHARPE_FLOOR` | `SHARPE_FLOOR` |

---

## Benchmark Scoring Weights

These weights define the advisory governance scoring function. They are
NEVER used for automated strategy selection or deployment decisions.

| Canonical name | Value | Description |
|---|---|---|
| `SCORE_WEIGHT_RETURN` | `0.30` | Return component weight |
| `SCORE_WEIGHT_DRAWDOWN` | `0.25` | Drawdown penalty weight |
| `SCORE_WEIGHT_SHARPE` | `0.25` | Sharpe component weight |

The three main weights sum to 0.80. The remaining 0.20 is allocated to
walk-forward coverage (0.10) and issue penalty (0.10) within `benchmark_suite.py`.

### Re-exports by consuming modules

| Module | Local name | Maps to |
|---|---|---|
| `benchmark_suite` | `SCORE_WEIGHT_TOTAL_RETURN` | `SCORE_WEIGHT_RETURN` |
| `benchmark_suite` | `SCORE_WEIGHT_MAX_DRAWDOWN` | `SCORE_WEIGHT_DRAWDOWN` |
| `benchmark_suite` | `SCORE_WEIGHT_SHARPE` | `SCORE_WEIGHT_SHARPE` (direct) |
| `sensitivity_audit` | `_BENCH_WEIGHT_RETURN` | `SCORE_WEIGHT_RETURN` |
| `sensitivity_audit` | `_BENCH_WEIGHT_DRAWDOWN` | `SCORE_WEIGHT_DRAWDOWN` |
| `sensitivity_audit` | `_BENCH_WEIGHT_SHARPE` | `SCORE_WEIGHT_SHARPE` |

---

## Intentionally Separate Severity Systems

AQCS uses two distinct severity classification systems for different purposes.
They must NOT be merged.

### Comparison-Severity (regression_guard.py)

A three-level lowercase system for classifying artifact-comparison findings:

| Constant | Value | Meaning |
|---|---|---|
| `SEVERITY_CRITICAL` | `"critical"` | Hash mismatch, governance violation, determinism failure |
| `SEVERITY_WARNING` | `"warning"` | Metric drift above WARNING threshold |
| `SEVERITY_INFO` | `"info"` | Minor change, artifact added/removed |

**Domain:** Comparing two sets of research artifacts (baseline vs candidate).  
**Threshold:** `DRIFT_THRESHOLD_WARNING = 0.05` (5%), `DRIFT_THRESHOLD_CRITICAL = 0.20` (20%).

### Instability-Magnitude (sensitivity_audit.py)

A four-level uppercase system for classifying perturbation instability:

| Constant | Value | Meaning |
|---|---|---|
| `SEVERITY_CRITICAL` | `"CRITICAL"` | Governance threshold crossed, or >50% relative change |
| `SEVERITY_HIGH` | `"HIGH"` | 20–50% relative change |
| `SEVERITY_MEDIUM` | `"MEDIUM"` | 5–20% relative change |
| `SEVERITY_LOW` | `"LOW"` | < 5% relative change |

**Domain:** Evaluating stability of a single strategy under parameter perturbation.  
**Thresholds:** `INSTABILITY_LOW_THRESHOLD = 0.05`, `INSTABILITY_MEDIUM_THRESHOLD = 0.20`, `INSTABILITY_HIGH_THRESHOLD = 0.50`.

### Why not merge them?

- The regression guard classifies inter-experiment differences (binary concern).
- The sensitivity audit classifies intra-experiment instability (magnitude gradient).
- They use different string cases to prevent accidental string comparison equality.
- Merging would either collapse the four-level instability system into three
  levels (losing resolution) or introduce complexity into the regression guard
  that has no legitimate use case.

The governance regression test `TestSeveritySystemDistinctness` enforces that
the string values never overlap.

---

## Constants NOT Centralized

The following constants are specific to their modules and are intentionally NOT
in `governance_thresholds.py`:

| Module | Constant | Reason not centralized |
|---|---|---|
| `benchmark_suite` | `REGRESSION_ISSUE_CEIL = 5` | Specific to campaign issue counting |
| `benchmark_suite` | `SCORE_WEIGHT_WF_COVERAGE = 0.10` | Specific to walk-forward coverage scoring |
| `benchmark_suite` | `SCORE_WEIGHT_ISSUE_PENALTY = 0.10` | Specific to issue penalty scoring |
| `benchmark_suite` | `_RETURN_CAP, _DRAWDOWN_CAP, _SHARPE_CAP` | Normalisation caps, internal detail |
| `regression_guard` | `DRIFT_THRESHOLD_WARNING/CRITICAL` | Specific to regression comparison |
| `sensitivity_audit` | `INSTABILITY_*_THRESHOLD` | Specific to instability magnitude |

---

## Governance Regression Tests

`tests/governance/test_governance_constants.py` enforces consistency with 26 tests:

- `TestCanonicalValues` — verifies the canonical values are correct
- `TestBenchmarkSuiteReExports` — verifies benchmark_suite re-exports match canonical
- `TestSensitivityAuditReExports` — verifies sensitivity_audit re-exports match canonical
- `TestCrossModuleConsistency` — verifies the two modules are always in sync
- `TestScoringWeightConstraints` — verifies the three main weights sum to 0.80
- `TestSeveritySystemDistinctness` — verifies the two severity systems never overlap

These tests act as the automated enforcement of the "MUST stay in sync" rule
that was previously manual.
