# ADR-008: Statistical Governance Threshold Policy

**Status:** Accepted  
**Date:** 2026-05-19  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-005 (Research Core), Phase-1B

---

## Context

AQCS Phase 1 introduced four sets of numeric governance thresholds distributed across
three source modules:

1. **Regression guard** (`src/aqcs/research/regression_guard.py`):
   - `DRIFT_THRESHOLD_WARNING = 0.05` — 5% relative metric change triggers a warning finding
   - `DRIFT_THRESHOLD_CRITICAL = 0.20` — 20% relative metric change triggers a critical finding

2. **Benchmark suite** (`src/aqcs/research/benchmark_suite.py`):
   - `SCORE_WEIGHT_TOTAL_RETURN = 0.30`
   - `SCORE_WEIGHT_MAX_DRAWDOWN = 0.25`
   - `SCORE_WEIGHT_SHARPE = 0.25`
   - `SCORE_WEIGHT_WF_COVERAGE = 0.10`
   - `SCORE_WEIGHT_ISSUE_PENALTY = 0.10`
   - `REGRESSION_RETURN_FLOOR = -0.10`
   - `REGRESSION_DRAWDOWN_CEIL = 0.30`
   - `REGRESSION_SHARPE_FLOOR = 0.0`
   - `REGRESSION_ISSUE_CEIL = 5`

3. **Sensitivity audit** (`src/aqcs/research/sensitivity_audit.py`):
   - `INSTABILITY_LOW_THRESHOLD = 0.05`
   - `INSTABILITY_MEDIUM_THRESHOLD = 0.20`
   - `INSTABILITY_HIGH_THRESHOLD = 0.50`
   - `GOVERNANCE_RETURN_FLOOR = -0.10` (mirrors benchmark `REGRESSION_RETURN_FLOOR`)
   - `GOVERNANCE_DRAWDOWN_CEIL = 0.30` (mirrors benchmark `REGRESSION_DRAWDOWN_CEIL`)
   - `GOVERNANCE_SHARPE_FLOOR = 0.0` (mirrors benchmark `REGRESSION_SHARPE_FLOOR`)

Each module's docstring notes that changes require an ADR and human approval, but no ADR
previously formalized this governance commitment.

The absence of this ADR is a Phase-1B readiness blocker identified in AUD-007 (R-001).

---

## Decision

**AQCS adopts a formal statistical threshold governance policy. All governance-critical
numeric constants in the research layer are treated as source-controlled policy
decisions, not implementation details.**

The following rules apply immediately and to all future additions:

### Rule 1 — Thresholds are governance controls, not optimization targets

Thresholds govern what AQCS reports as a finding, warning, or regression. They are
selected by human judgment based on research context, not derived from data, optimized
to maximize any metric, or adjusted adaptively at runtime.

Any process that tunes, searches, or adapts a threshold to improve backtest scores,
benchmark rankings, or regression rates is **prohibited**.

### Rule 2 — All governed thresholds are registered here

The canonical list of governed thresholds is maintained in the **Governed Constants
Register** section at the end of this ADR. Any new governance threshold added to the
research layer must be registered here at the time it is introduced.

### Rule 3 — Change process

A threshold may be changed only by:
1. The Human Founder proposing the new value with documented rationale
2. A new ADR or amendment to this ADR recording the change, the rationale, and the
   evidence supporting the new value
3. A code change submitted as a PR with the ADR reference in the commit message
4. Human review and approval of the PR before merge

No agent session, automated process, or CI pipeline may change a threshold value.

### Rule 4 — Thresholds must not trigger autonomous actions

Benchmark rankings, regression findings, and instability findings are advisory.
They inform human review. They **must not** automatically:
- promote a strategy to live trading or paper trading
- approve a merge without human review
- modify artifact schemas or stored results
- change `CURRENT_PHASE` in `phase_guard.py`
- trigger any execution-layer operation

This prohibition applies regardless of how the threshold is crossed or what severity
is reported.

### Rule 5 — Mirror constants must stay synchronized

`sensitivity_audit.py` maintains `GOVERNANCE_*` mirror copies of the benchmark
regression floors/ceilings. Until a single-source module is introduced, these mirrors
must be updated in the same commit as any change to the corresponding
`REGRESSION_*` constant in `benchmark_suite.py`.

AUD-007 (R-005) identified this duplication as a future risk. Resolution — either
a shared `aqcs.utils.governance_constants` module or an import from `benchmark_suite`
— requires a separate implementation task with its own review.

### Rule 6 — Prohibition on hidden threshold drift

No threshold may change its effective value through:
- float arithmetic that produces a different comparison boundary
- NaN normalization that silently bypasses a check
- Version-bumped artifact schemas that redefine field semantics
- Feature flags or environment variables

Any such change is treated as an unauthorized threshold modification subject to
Rules 2–3.

### Rule 7 — Future threshold additions

Any new governance constant added to `aqcs.research.*` or `aqcs.utils.*` must:
- be declared as a module-level constant (not inline)
- carry a docstring comment explaining its governance role
- be registered in this ADR's Governed Constants Register via amendment
- reference this ADR in its module docstring or inline comment

---

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| No policy, trust code comments | Code comments do not create a formal change-control obligation. A future contributor can change a threshold with a "minor update" commit message and no review escalation. |
| Single `aqcs.utils.governance_constants` module now | Technically desirable but a source-code change requiring implementation, testing, and migration of all three modules. Deferred to a dedicated task to keep this ADR documentation-only. |
| Dynamic thresholds loaded from config file | Makes threshold changes invisible to code review. Config-file changes can bypass PR review. Incompatible with determinism and auditability requirements. |
| Statistical derivation of thresholds (e.g., 1 standard deviation) | Adapts thresholds to data, creating an optimization loop that violates Rule 1. |

---

## Consequences

**Positive:**
- Changes to any governance-critical constant now require a documented rationale and
  human approval, preventing silent drift
- The governed constants register provides a single reference point for auditors
- The rule against autonomous threshold-triggered actions is formally stated

**Negative:**
- Changing a threshold requires more steps than editing a constant — this is intentional
- Mirror constants in `sensitivity_audit.py` add maintenance overhead until a
  single-source solution is implemented

**Neutral:**
- Current threshold values are accepted as-is; this ADR does not change any values
- The duplication between `benchmark_suite.py` and `sensitivity_audit.py` is acknowledged
  but not resolved here

---

## Governed Constants Register

*Last updated: 2026-05-19*

### `src/aqcs/research/regression_guard.py`

| Constant | Value | Meaning | Governs |
|---|---|---|---|
| `DRIFT_THRESHOLD_WARNING` | `0.05` | 5% relative metric change | warning-severity finding in regression reports |
| `DRIFT_THRESHOLD_CRITICAL` | `0.20` | 20% relative metric change | critical-severity finding in regression reports |

### `src/aqcs/research/benchmark_suite.py`

| Constant | Value | Meaning | Governs |
|---|---|---|---|
| `SCORE_WEIGHT_TOTAL_RETURN` | `0.30` | Return component weight | benchmark advisory score |
| `SCORE_WEIGHT_MAX_DRAWDOWN` | `0.25` | Drawdown penalty weight | benchmark advisory score |
| `SCORE_WEIGHT_SHARPE` | `0.25` | Sharpe component weight | benchmark advisory score |
| `SCORE_WEIGHT_WF_COVERAGE` | `0.10` | Walk-forward coverage weight | benchmark advisory score |
| `SCORE_WEIGHT_ISSUE_PENALTY` | `0.10` | Issue penalty weight | benchmark advisory score |
| `REGRESSION_RETURN_FLOOR` | `-0.10` | Return floor | benchmark regression flag |
| `REGRESSION_DRAWDOWN_CEIL` | `0.30` | Drawdown ceiling | benchmark regression flag |
| `REGRESSION_SHARPE_FLOOR` | `0.0` | Sharpe floor | benchmark regression flag |
| `REGRESSION_ISSUE_CEIL` | `5` | Max acceptable issues | benchmark regression flag |

### `src/aqcs/research/sensitivity_audit.py`

| Constant | Value | Meaning | Governs |
|---|---|---|---|
| `INSTABILITY_LOW_THRESHOLD` | `0.05` | 5% relative change | LOW-severity finding |
| `INSTABILITY_MEDIUM_THRESHOLD` | `0.20` | 20% relative change | MEDIUM-severity finding |
| `INSTABILITY_HIGH_THRESHOLD` | `0.50` | 50% relative change | HIGH-severity finding; above → CRITICAL |
| `GOVERNANCE_RETURN_FLOOR` | `-0.10` | Return floor (mirror of `REGRESSION_RETURN_FLOOR`) | CRITICAL breach detection |
| `GOVERNANCE_DRAWDOWN_CEIL` | `0.30` | Drawdown ceiling (mirror) | CRITICAL breach detection |
| `GOVERNANCE_SHARPE_FLOOR` | `0.0` | Sharpe floor (mirror) | CRITICAL breach detection |

---

## Related documents

- `docs/audits/2026-05-19-AUD-007-phase-1b-readiness-audit-001.md` — identified this gap (R-001, R-005)
- `src/aqcs/research/regression_guard.py` — governs DRIFT_THRESHOLD_*
- `src/aqcs/research/benchmark_suite.py` — governs SCORE_WEIGHT_* and REGRESSION_*
- `src/aqcs/research/sensitivity_audit.py` — governs INSTABILITY_* and GOVERNANCE_*
- `src/aqcs/utils/phase_guard.py` — governs CURRENT_PHASE (separate governance)
- ADR-007: Minimal backtesting engine (predecessor governance)
- ADR-009: Canonicalization & Artifact Migration Policy (companion ADR)
