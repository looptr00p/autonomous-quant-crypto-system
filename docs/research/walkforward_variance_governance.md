# Walk-Forward Variance Governance

**Task:** TASK-WALKFORWARD-VARIANCE-001  
**Date:** 2026-05-19  
**Status:** Implemented (REPORT_VERSION "2")

---

## Overview

This document describes the walk-forward variance and governance advisory
metrics added in Phase-1B.  These metrics provide **governance visibility**
into fold-level instability, dispersion, and acceptability.

**Advisory-only status:** These metrics are for human review.  They do NOT:
- auto-approve or auto-reject strategies
- rank deployment candidates
- trigger execution of any kind
- mutate strategy parameters
- imply trading readiness

---

## New Metrics (WalkForwardSummary v2)

### Total Return Dispersion

| Field | Formula | NaN when |
|---|---|---|
| `mean_total_return` | mean across evaluated folds | no evaluated folds |
| `std_total_return` | sample std dev (n−1) | < 2 evaluated folds |
| `min_total_return` | minimum across folds | no evaluated folds |
| `max_total_return` | maximum across folds | no evaluated folds |
| `range_total_return` | max − min | < 2 evaluated folds |
| `cv_total_return` | std / \|mean\| | \|mean\| < 1e-10, or < 2 folds |

### Sharpe Ratio Dispersion (new in v2)

| Field | Formula | NaN when |
|---|---|---|
| `mean_sharpe_ratio` | mean across evaluated folds | no evaluated folds |
| `std_sharpe_ratio` | sample std dev (n−1) | < 2 evaluated folds |
| `min_sharpe_ratio` | minimum across folds | no evaluated folds |
| `max_sharpe_ratio` | maximum across folds | no evaluated folds |

### Max Drawdown Dispersion (new in v2)

| Field | Formula | NaN when |
|---|---|---|
| `mean_max_drawdown` | mean across evaluated folds | no evaluated folds |
| `std_max_drawdown` | sample std dev (n−1) | < 2 evaluated folds |
| `min_max_drawdown` | minimum across folds | no evaluated folds |
| `max_max_drawdown` | maximum across folds | no evaluated folds |

---

## Governance Advisory Counts (new in v2)

These counts identify folds that breach Phase-1B acceptability thresholds.
A breach count > 0 is an advisory signal requiring human review — it is NOT
an automatic rejection.

| Field | Condition | Threshold |
|---|---|---|
| `n_windows_below_return_floor` | return < −10% | `_RETURN_FLOOR = −0.10` |
| `n_windows_above_drawdown_ceil` | drawdown > 30% | `_DRAWDOWN_CEIL = 0.30` |
| `n_windows_below_sharpe_floor` | sharpe ≤ 0.0 | `_SHARPE_FLOOR = 0.0` |

**Threshold ownership:** These values mirror the AQCS governance thresholds
from `TASK-GOVERNANCE-CONSOLIDATION-001` (`governance_thresholds.py`).  Once
that PR merges to master, `walkforward.py` should import from there instead
of defining private constants.  Any change to these values requires an ADR.

---

## Coefficient of Variation (CV)

The CV (`cv_total_return = std / |mean|`) is a dimensionless measure of
relative dispersion.  A high CV suggests that fold performance is highly
variable relative to the mean — a signal of potential instability.

**Interpretation guidance:**
- CV < 0.5: relatively consistent performance across folds
- 0.5 ≤ CV < 1.0: moderate fold-to-fold variation
- CV ≥ 1.0: high relative variance — inspect individual fold results

**Limitations:**
- CV is undefined when `|mean| < 1e-10` (near-zero mean)
- CV requires at least 2 evaluated folds
- CV captures symmetrical variance; one-sided risk requires inspecting min/max

**Do NOT use CV to**:
- rank strategies
- approve deployment
- set position sizing
- conclude that a strategy is "good" or "bad"

---

## Report Version

`REPORT_VERSION` was bumped from `"1"` to `"2"` with this change.
`validate_report` flags v1 reports as outdated.  Old v1 reports can still
be loaded via `report_from_dict` — missing new fields default to NaN/0.

---

## Determinism Guarantees

- All new metrics are computed from deterministic inputs only.
- No wall-clock values appear in summary fields.
- `now_utc` injection is preserved for test determinism.
- `report_hash` commits to all summary fields including new v2 fields.
- Repeated calls with identical inputs produce identical `report_hash`.

---

## Known Limitations

1. **Failed windows excluded:** Folds with `failed=True` contribute 0 to
   governance counts and are excluded from all metric calculations.  A
   strategy with many failed folds may appear to have cleaner metrics.

2. **NaN metric exclusion:** Within a succeeded window, NaN metric values
   (e.g., NaN sharpe from a zero-volatility fold) are excluded per-metric.
   A fold can contribute to `mean_total_return` but not `mean_sharpe_ratio`.

3. **CV undefined at zero mean:** A strategy with exactly 0 mean return
   produces `cv_total_return = NaN`.  This is not the same as "zero CV";
   it means the CV is undefined.

4. **No temporal ordering in summary:** Summary statistics aggregate across
   folds without preserving fold order.  Temporal degradation (later folds
   performing worse than earlier ones) is not captured in the summary — it
   requires examining individual `WalkForwardResult` objects.

5. **Threshold alignment:** `_RETURN_FLOOR`, `_DRAWDOWN_CEIL`, `_SHARPE_FLOOR`
   in `walkforward.py` are private constants that must match
   `governance_thresholds.py` once TASK-GOVERNANCE-CONSOLIDATION-001 merges.
   The governance regression tests in `test_governance_constants.py` will
   enforce alignment after that PR lands.

---

## What These Metrics Cannot Tell You

- Whether the strategy will be profitable in the future
- Whether the strategy is suitable for live or paper trading
- Which parameter values are optimal
- Whether the variance is "acceptable" in absolute terms

These metrics support **human review** of temporal robustness and stability.
All deployment decisions remain human-authorized.
