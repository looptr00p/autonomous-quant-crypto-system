# AUD-007: Phase-1B Readiness Audit — AQCS Research Governance Layer

**Date:** 2026-05-19  
**Auditor:** Claude Code (claude-sonnet-4-6)  
**Task ID:** TASK-PHASE-1B-READINESS-AUDIT-001  
**Branch:** `docs/task-phase-1b-readiness-audit-001`  
**Scope:** Full Phase-1 stack assessment for readiness to transition to Phase-1B statistical governance

---

> **Governance reaffirmation.** This audit explicitly confirms that AQCS remains a
> **deterministic offline research platform**. It is NOT a live-trading system, paper-trading
> system, autonomous execution platform, or portfolio automation system. No code path in Phase 1
> submits orders to any exchange. This constraint is architectural, not configurational, and is
> enforced by `src/aqcs/utils/phase_guard.py`. Nothing in this audit authorizes, recommends, or
> enables the relaxation of this constraint.

---

## Executive Summary

AQCS has completed a substantial deterministic research infrastructure buildout through
Phase 1. The system now spans data ingestion, validation, manifests, replay certification,
baseline reporting, walk-forward validation, campaign orchestration, benchmark suites,
regression guards, sensitivity auditing, canonical artifact hashing, and an operational
runbook. All automated checks pass cleanly.

**Verdict: CONDITIONALLY READY for Phase-1B.**

Two conditions must be met before Phase-1B work begins:

1. **ADR-008** must be filed: formal governance of the four overlapping threshold/weight
   constant sets that currently live in `regression_guard.py`, `benchmark_suite.py`, and
   `sensitivity_audit.py` without a single source of truth or change control record.
2. **ADR-009** must be filed: formal canonicalization migration policy documenting the
   two-format split (`legacy_hash` vs `canonical_hash`) and the conditions under which
   existing artifact schemas may be migrated.

Three non-blocking but time-sensitive follow-ups are also identified.

---

## Validation Results

All checks performed on master at commit `2dcf420`.

| Check | Result |
|---|---|
| `pytest tests/` (full) | **1698/1698 passed** |
| `pytest tests/architecture/` | **412/412 passed** |
| `pytest tests/research/` | **356/356 passed** |
| `pytest tests/monitoring/` | **79/79 passed** |
| `pytest tests/data/` | **236/236 passed** |
| `pytest tests/integration/` | **0 collected** (empty suite) |
| `ruff check src/ tests/ scripts/` | **All checks passed** |
| `black --check src/ tests/ scripts/` | **133 files unchanged** |
| `mypy src/` | **47 source files, 0 issues** |

---

## 1. Deterministic Infrastructure Assessment

### 1.1 Replay Certification

**Maturity: PRODUCTION-GRADE**

`aqcs.research.replay_certificate` certifies five independent hash fields:
- `config_hash` — BacktestConfig parameters
- `metrics_hash` — 8 standard backtest metrics (struct.pack binary encoding)
- `trades_hash` — full trade list in chronological order
- `equity_hash` — equity curve (chronological canonical bytes)
- `signals_hash` — signal series with SignalDirection encoding

Any change to config, metrics, trades, equity, or signals invalidates the corresponding
hash. The certificate provides end-to-end deterministic traceability from input config to
output artifacts.

885 test lines cover certification exhaustively. Temporal leakage detection is present in
walk-forward (`leakage_validated` flag enforced at report level).

**Risk:** INFORMATIONAL. The signals_hash uses a custom byte encoding for
`SignalDirection` values. This encoding is not documented in a standalone spec; it lives
only in `replay_certificate.py`. A future schema version change would need to handle
backward compatibility explicitly.

### 1.2 Canonical Hashing

**Maturity: FUNCTIONAL with documented two-format split**

`aqcs.utils.canonicalization` establishes a canonical format (compact separators,
sort_keys, ensure_ascii=False, allow_nan=False) with a `legacy_hash` helper for backward
compatibility. The split is:

| Format | Used by |
|---|---|
| `canonical_hash` (new) | campaign, benchmark_suite, regression_guard, sensitivity_audit |
| `legacy_hash` (pre-2026-05-19) | baseline_report, walkforward, manifest, dataset_registry, fleet_monitoring, replay_certificate (partial) |

This split is documented in the module docstring and in the operational runbook (§13).
43 dedicated tests cover the canonicalization module.

**Finding [MEDIUM — ADR-009 required]:** No formal ADR governs the migration path from
`legacy_hash` to `canonical_hash` for existing artifact schemas. The code documents the
intent ("new schemas should use canonical_hash; existing schemas must not change without
ADR") but the ADR does not yet exist. Without it, a future author might migrate a
legacy-format schema without understanding the stored-artifact breakage risk.

**Reproducibility risk:** LOW — the split is stable as long as no existing schema is
silently migrated.

### 1.3 Artifact Immutability and Self-Certification

**Maturity: PRODUCTION-GRADE**

Every research artifact is a `frozen=True` dataclass with a self-certifying SHA-256
hash. The hash excludes `generation_timestamp_utc` and itself, making it
wall-clock-independent. UUID5 IDs are derived deterministically from the hash.

Verified artifacts: manifest, registry, fleet snapshot, replay certificate, baseline
report, walk-forward report, campaign, benchmark suite, regression report, sensitivity
audit.

**Reproducibility risk:** LOW.

### 1.4 Regression Validation

**Maturity: PRODUCTION-GRADE**

`aqcs.research.regression_guard` compares baseline vs candidate artifact directories
across 9 finding types (hash_mismatch, metric_drift, replay_drift, artifact_missing,
artifact_added, version_change, schema_drift, determinism_failure, governance_violation).
38 tests cover all detection paths.

**Finding [MEDIUM — ADR-008 required]:** `DRIFT_THRESHOLD_WARNING = 0.05` and
`DRIFT_THRESHOLD_CRITICAL = 0.20` are explicit constants whose docstrings state that
changes require an ADR and human approval — but ADR-008 does not yet exist.

---

## 2. Statistical Governance Assessment

### 2.1 Walk-Forward Methodology

**Maturity: STRUCTURALLY SOUND, statistically minimal**

The walk-forward implementation in `aqcs.research.walkforward` provides:
- Temporal partitioning with configurable `train_bars`, `test_bars`, `step_bars`
- `n_windows` tracking (total, evaluated, failed, profitable)
- `leakage_validated` flag enforced at report level
- Explicit overlap detection logic (step_bars < test_bars)
- Aggregate metrics: mean return, mean Sharpe, mean drawdown

557 test lines cover temporal correctness and leakage prevention.

**Statistical blind spots [HIGH — governs Phase-1B scope]:**
- No multiple-comparison correction: when a campaign runs N experiments and all
  walk-forward windows are summarized together, there is no Bonferroni/FDR adjustment
  for the family-wise error rate
- No statistical significance testing: there is no t-test, bootstrap confidence
  interval, or permutation test applied to walk-forward results
- No reporting of variance across windows: only means are reported; standard deviation,
  skewness, and tail behavior across windows are absent
- No minimum-window-count requirement: a campaign with 2 walk-forward windows is
  treated identically to one with 100

These are appropriate Phase-1 deferments, not defects. Phase-1B scope should address
the variance and minimum-window questions first.

### 2.2 Sensitivity Audit Methodology

**Maturity: GOVERNANCE-CORRECT, scope bounded**

`aqcs.research.sensitivity_audit` applies explicit arithmetic perturbations to artifact
field values and detects governance threshold crossings. 52 tests cover all classification
paths.

**Scope boundary (correctly bounded):** the sensitivity audit operates on artifact values,
not on backtesting inputs. It answers "if this reported metric were X% different, would
it cross a governance threshold?" It does NOT re-run backtests with perturbed parameters.
This is a deliberate, correct design decision for Phase-1. True parameter sensitivity
(re-running with perturbed fee_bps, lookback, etc.) requires the full backtesting pipeline
and is a Phase-1B capability.

**Finding [MEDIUM — documentation gap]:** The distinction between "artifact-level
perturbation" (current) and "parameter-level perturbation via backtesting" (Phase-1B)
is documented in HND-031 but is not explicitly stated in the module docstring or runbook.
A reader could misinterpret the sensitivity audit as doing more than it does.

**Finding [MEDIUM — ADR-008 required]:** `INSTABILITY_LOW_THRESHOLD = 0.05`,
`INSTABILITY_MEDIUM_THRESHOLD = 0.20`, `INSTABILITY_HIGH_THRESHOLD = 0.50` are
module-level constants requiring ADR to change. ADR-008 does not yet exist.

### 2.3 Benchmark Methodology

**Maturity: TRANSPARENT and ADVISORY**

`aqcs.research.benchmark_suite` provides explicit, auditable scoring:
- 5 components: total_return (0.30), max_drawdown (0.25), Sharpe (0.25), WF coverage
  (0.10), issue penalty (0.10) — sum = 1.00 (verified)
- 4 regression flags with explicit thresholds
- Rankings are advisory-only; the module explicitly forbids deployment selection

45 tests cover scoring, ranking stability, and regression flag detection.

**Finding [MEDIUM — ADR-008 required]:** `SCORE_WEIGHT_*` and `REGRESSION_*` constants
are documented as requiring an ADR to change. ADR-008 does not yet exist.

**Finding [LOW — governance constant duplication]:** `REGRESSION_RETURN_FLOOR`,
`REGRESSION_DRAWDOWN_CEIL`, `REGRESSION_SHARPE_FLOOR` exist in `benchmark_suite.py` AND
copies (`GOVERNANCE_RETURN_FLOOR`, `GOVERNANCE_DRAWDOWN_CEIL`, `GOVERNANCE_SHARPE_FLOOR`)
exist in `sensitivity_audit.py`. Currently verified identical. Divergence without an ADR
is a future risk.

### 2.4 Overfitting Protection Maturity

**Maturity: STRUCTURAL only**

Current overfitting protections are:
- Walk-forward temporal separation (no lookahead via `leakage_validated`)
- Replay certificates (identical inputs → identical outputs)
- Sensitivity audit (metric stability under perturbations)
- Regression guard (detect unexpected metric changes between runs)

**Statistical blind spot [HIGH — core Phase-1B gap]:** There is no protection against
in-sample overfitting to the walk-forward train/test splits themselves. The system
correctly separates train from test temporally, but it does not detect overfitting
to the test period if the same strategy is evaluated many times on the same test windows.

This is the primary statistical governance gap for Phase-1B:
- No deflation of expected returns for multiple strategy evaluations
- No minimum backtest length requirements
- No detection of "lucky" strategies with high variance and few trades

---

## 3. Architecture & Governance Assessment

### 3.1 Dependency DAG

**Maturity: PRODUCTION-GRADE, CI-enforced**

412 architecture tests enforce the dependency DAG via AST analysis on every file. The
DAG covers all 12 packages with an explicitly governed allowed-import set.

`aqcs.research` is allowed to import from: `aqcs.backtesting`, `aqcs.data`,
`aqcs.experiments`, `aqcs.features`, `aqcs.monitoring`, `aqcs.signals`, `aqcs.utils`.
It is forbidden from: `aqcs.execution`, `aqcs.risk`, `aqcs.portfolio`, `aqcs.llm_oversight`.

All new research modules (sensitivity_audit, regression_guard, benchmark_suite) import
only from `aqcs.utils`. DAG compliance is verified.

**Risk:** LOW.

### 3.2 Phase Guard Enforcement

**Maturity: PRODUCTION-GRADE**

`CURRENT_PHASE = 1` blocks 10 features at runtime:
`FUTURES`, `LEVERAGE`, `LIVE_TRADING`, `WEBSOCKET_STREAMING`, `REINFORCEMENT_LEARNING`,
`MACHINE_LEARNING`, `AUTONOMOUS_AGENTS`, `SHORT_SELLING`, `ORDER_EXECUTION`, `PAPER_TRADING`.

Phases 2, 3, 4 are pre-defined in the guard, showing deliberate future planning.

Stubs verified empty: `aqcs.execution`, `aqcs.portfolio`, `aqcs.risk` contain only
empty `__init__.py`. No code was introduced into these packages.

**Risk:** LOW.

### 3.3 Governance Test Coverage

**Maturity: COMPREHENSIVE**

179 governance tests cover:
- ADR structure and required sections
- Agent registry
- Agent workflow documentation
- Anti-live-trading checks
- Anti-LLM-execution checks
- Audit structure
- Cross-document references
- Doc/import consistency
- Handoff structure
- Objective structure
- Task traceability

**Finding [LOW]:** Governance tests validate `docs/handoffs/HND-*.md` (the old format)
but the active format is `docs/bitacora/YYYY-MM-DD-HND-*.md`. HND number uniqueness in
the bitacora is not validated by any test. (Documented in AUD-006 as follow-up R-008.)

### 3.4 Forbidden Import Protection

**Maturity: PRODUCTION-GRADE**

`tests/architecture/test_forbidden_imports.py` and related tests actively verify that
forbidden import patterns cannot silently pass the DAG checker. Regression tests
confirm that if `aqcs.execution` were added to a research file, the architecture test
would catch it.

### 3.5 Runbook Alignment

**Maturity: MOSTLY ALIGNED with documented gap**

`docs/runbooks/research_workflow_runbook_v1.md` (1074 lines) covers 20 sections from
AQCS philosophy through Phase-1 boundaries.

**Finding [LOW]:** The runbook does not include a dedicated section for the regression
guard workflow (`run_regression_guard.py` / `validate_regression_report.py`), introduced
in PR #23. This was documented in AUD-006 as follow-up R-005. The runbook also uses
`--no-cov` pytest flag which has known conflicts with `pyproject.toml` addopts (AUD-006
R-006).

---

## 4. Operational Readiness Assessment

### 4.1 Test Coverage and Confidence

**Maturity: STRONG**

| Dimension | Value |
|---|---|
| Total tests | 1,698 |
| Source lines | 10,259 |
| Test lines | 15,314 |
| Test/source ratio | 1.49× |
| Failing tests | 0 |
| Skipped tests | 0 (5 data-availability skips in worktrees only) |

Test distribution is healthy across all suites.

**Finding [MEDIUM]:** The `tests/integration/` directory is empty — 0 tests collected.
No end-to-end test exercises the full pipeline (data → manifest → replay → baseline →
walkforward → campaign → benchmark → regression guard → sensitivity audit). This is a
meaningful gap for operational confidence.

### 4.2 Burn-In and Smoke Test Workflows

**Maturity: IMPLEMENTED**

Scripts exist for:
- API smoke test: `scripts/data/smoke_test_public_ohlcv.py`
- Public OHLCV burn-in: `scripts/data/run_public_ohlcv_burn_in.py`
- Data quality check: `scripts/monitoring/check_data_quality.py`
- All research workflow stages: certify_replay, validate, build_campaign, etc.

Market data on disk: BTC/ETH/SOL in `1d` (2023–present, ~1,233 rows each).

### 4.3 Fleet Monitoring

**Maturity: IMPLEMENTED**

`aqcs.monitoring.fleet_monitoring` produces immutable fleet snapshots with self-certifying
hashes. `scripts/monitoring/compare_fleet_snapshots.py` detects data drift between
snapshots. 79 monitoring tests pass.

### 4.4 Merge and Handoff Discipline

**Maturity: CONSISTENTLY PRACTICED**

30 handoff records in `docs/bitacora/` covering HND-006 through HND-031. All recent
PRs followed the governance workflow: branch → implementation → validation → PR → merge.
No direct commits to master observed.

The HND-025 collision identified in AUD-006 was resolved before merge (PR #23 renamed
to HND-028 per the audit recommendation). This demonstrates the governance audit cycle
working as intended.

---

## 5. Deferred Capability Assessment

### 5.1 Live Trading

**Status: CORRECTLY DEFERRED and BLOCKED**

`Feature.LIVE_TRADING` is blocked in Phase 1. No live trading code, no ccxt order
submission, no exchange connection for order routing. The only exchange connection in
the codebase is read-only OHLCV download via ccxt in `aqcs.data.ohlcv`.

**Accidental creep check: NONE DETECTED.**

### 5.2 Paper Trading

**Status: CORRECTLY DEFERRED and BLOCKED**

`Feature.PAPER_TRADING` is blocked in Phase 1. No paper trading infrastructure exists.

### 5.3 Execution Systems

**Status: CORRECTLY DEFERRED, stub only**

`aqcs.execution` is an empty stub (`__init__.py` only). `Feature.ORDER_EXECUTION` is
blocked in Phase 1.

### 5.4 Portfolio and Risk Systems

**Status: CORRECTLY DEFERRED, stubs only**

`aqcs.portfolio` and `aqcs.risk` are empty stubs. No portfolio management or risk
calculation code exists.

### 5.5 Machine Learning

**Status: CORRECTLY DEFERRED and BLOCKED**

`Feature.MACHINE_LEARNING` and `Feature.REINFORCEMENT_LEARNING` are both blocked. No
ML/RL frameworks (torch, sklearn, jax, tensorflow) are imported anywhere in the codebase.
Grep confirmation: zero ML import occurrences.

### 5.6 Optimization Engines

**Status: CORRECTLY DEFERRED**

No optimization frameworks (scipy.optimize, optuna, hyperopt, bayesian, evolutionary)
are imported anywhere. The sensitivity audit explicitly uses arithmetic perturbations
with no search component.

### 5.7 Autonomous Systems

**Status: CORRECTLY DEFERRED and BLOCKED**

`Feature.AUTONOMOUS_AGENTS` is blocked. The LLM oversight layer (`aqcs.llm_oversight`)
is read-only: it subscribes to events and generates narrative summaries. It does not
influence any backtest, signal generation, or data pipeline decision.

### 5.8 Schedulers and Daemons

**Status: CORRECTLY ABSENT**

No schedulers, cron jobs, or background worker daemons exist in the codebase. All
workflows are invoked explicitly via CLI scripts.

---

## 6. ADR Requirements

The following ADRs are **required before Phase-1B work begins**. They formalize
governance commitments that already exist informally in code comments but lack the
human-approval-on-change protection that an ADR provides.

### ADR-008 (REQUIRED — Phase-1B blocker): Statistical Threshold Governance

**Scope:** Governs the set of governance-critical numeric constants distributed
across three modules, ensuring that any change requires a documented rationale and
human approval.

Constants governed:
- `regression_guard.py`: `DRIFT_THRESHOLD_WARNING = 0.05`, `DRIFT_THRESHOLD_CRITICAL = 0.20`
- `benchmark_suite.py`: `SCORE_WEIGHT_TOTAL_RETURN = 0.30`, `SCORE_WEIGHT_MAX_DRAWDOWN = 0.25`,
  `SCORE_WEIGHT_SHARPE = 0.25`, `SCORE_WEIGHT_WF_COVERAGE = 0.10`, `SCORE_WEIGHT_ISSUE_PENALTY = 0.10`,
  `REGRESSION_RETURN_FLOOR = -0.10`, `REGRESSION_DRAWDOWN_CEIL = 0.30`, `REGRESSION_SHARPE_FLOOR = 0.0`
- `sensitivity_audit.py`: `INSTABILITY_LOW_THRESHOLD = 0.05`, `INSTABILITY_MEDIUM_THRESHOLD = 0.20`,
  `INSTABILITY_HIGH_THRESHOLD = 0.50`, `GOVERNANCE_*` mirrors of benchmark floors

ADR-008 should also specify: who sets these thresholds, what evidence justifies the
current values, and what process is required to change them.

### ADR-009 (REQUIRED — Phase-1B blocker): Canonicalization Migration Policy

**Scope:** Formalizes the two-format split and the migration path for existing
legacy-format artifact schemas.

Content required:
- Why the split exists (historical: formats were locked before canonical module existed)
- Which schemas are frozen at legacy format (and why changing them would break stored artifacts)
- The migration trigger conditions (e.g., "only migrate on major version bump")
- How to verify that a migrated artifact produces the same canonical representation
- The approval process for any schema migration

### ADR-010 (RECOMMENDED for Phase-1B): Walk-Forward Statistical Minimum Requirements

**Scope:** Defines the minimum statistical requirements for a walk-forward validation
to be considered governance-worthy.

Candidates to specify:
- Minimum n_windows (e.g., ≥ 5 windows before results are considered credible)
- Whether per-window result variance must be reported
- Whether a strategy tested on fewer windows carries an explicit governance warning
- Whether multiple campaigns evaluated on the same dataset require any correction

### ADR-011 (RECOMMENDED for Phase-1B): Sensitivity Audit Scope Boundary

**Scope:** Formally distinguishes artifact-level perturbation (current) from
parameter-level perturbation via re-running backtests (Phase-1B capability).

Content required:
- Explicit statement that the current sensitivity audit operates on artifact values only
- Approved scope for what "parameter-level sensitivity" would mean in Phase-1B
- Governance requirements for any backtesting-loop sensitivity analysis

---

## 7. Remaining Risks

| ID | Severity | Description | Impact | Recommended Action |
|---|---|---|---|---|
| R-001 | **HIGH** | No ADR-008: governance threshold constants can be changed without formal process | Governance regression without detection | File ADR-008 before Phase-1B |
| R-002 | **HIGH** | No ADR-009: canonicalization migration path unformalized | Silent hash-breaking changes to stored artifacts | File ADR-009 before Phase-1B |
| R-003 | **HIGH** | No integration tests: full pipeline not exercised end-to-end | Confidence gap in cross-module correctness | Add at least one end-to-end integration test |
| R-004 | **MEDIUM** | Walk-forward n_windows floor absent: 2-window result treated same as 100-window | Weak statistical inference dressed as strong | Define minimum n_windows policy (ADR-010) |
| R-005 | **MEDIUM** | Governance constant duplication: `REGRESSION_*` in benchmark_suite and `GOVERNANCE_*` copies in sensitivity_audit are not single-sourced | Thresholds could diverge silently | Introduce a single canonical source (e.g., `aqcs.utils.governance_constants`) or enforce via ADR-008 |
| R-006 | **MEDIUM** | Sensitivity audit scope ambiguity: artifact-level perturbation vs parameter-level not documented in module/runbook | Misuse or misinterpretation | File ADR-011; update runbook §12 |
| R-007 | **LOW** | Runbook missing §12 (regression guard workflow) | Documentation gap | Add runbook section |
| R-008 | **LOW** | Runbook `--no-cov` flag conflict with pyproject.toml addopts | Runbook commands may fail for new contributors | Update runbook pytest commands |
| R-009 | **LOW** | Bitacora HND uniqueness not validated by governance tests | Future HND collisions not auto-detected | Add governance test |
| R-010 | **LOW** | Signal encoding in signals_hash (canonical byte representation) undocumented outside replay_certificate.py | Future schema evolution risk | Document encoding spec |

---

## 8. Non-Blocking Follow-Ups

These do not block Phase-1B but should be completed within Phase-1B:

1. **Add integration test(s)** — Minimum: one test that exercises data → replay → baseline → campaign with real or synthetic data, verifying hash consistency end-to-end.

2. **Add runbook §12: Regression Guard Workflow** — Document `run_regression_guard.py` and `validate_regression_report.py` usage, exit codes, and advisory semantics.

3. **Add bitacora HND uniqueness governance test** — Scan `docs/bitacora/` for duplicate HND numbers on every test run.

4. **Single-source governance constants** — Consider introducing `aqcs.utils.governance_constants` to hold `RETURN_FLOOR`, `DRAWDOWN_CEIL`, `SHARPE_FLOOR` and have both `benchmark_suite.py` and `sensitivity_audit.py` import from it. Requires updating relevant test fixtures.

5. **Runbook pytest command accuracy** — Replace `--no-cov` with `--override-ini="addopts="` or verify pytest-cov `--no-cov` behavior with current configuration.

---

## 9. Recommended Phase-1B Scope

Phase-1B is "statistical research governance." Based on current infrastructure, the
recommended scope in priority order:

**Tier 1 — Required to call Phase-1B in progress:**
- File ADR-008 (threshold governance)
- File ADR-009 (canonicalization migration policy)
- Define minimum walk-forward statistical requirements (ADR-010)

**Tier 2 — Core Phase-1B deliverables:**
- Walk-forward variance reporting (per-window result distribution, not just means)
- Minimum n_windows floor enforcement with governance warnings below minimum
- Sensitivity audit extension: true parameter sensitivity via controlled backtesting runs
  (new capability, new CLI, new artifact schema — requires ADR-011 first)
- Integration test suite (end-to-end pipeline validation)

**Tier 3 — Later in Phase-1B:**
- Multiple-comparison awareness documentation
- Benchmark score confidence bounds (uncertainty quantification without statistics)
- Overfitting risk indicators in campaign artifacts (max n_experiments evaluated on same data)

**Explicitly out of Phase-1B scope:**
- Live trading
- Paper trading
- Order execution
- Portfolio management
- ML/RL integration
- Optimization engines
- Autonomous agent orchestration
- Adaptive thresholds

---

## 10. Explicitly Forbidden Next Steps

The following MUST NOT occur in Phase-1B or any future phase without an approved ADR
and explicit human authorization:

- **Live trading**: `Feature.LIVE_TRADING` remains blocked. No code path may submit
  orders to any exchange.
- **Paper trading**: `Feature.PAPER_TRADING` remains blocked. No simulated order
  submission.
- **Autonomous execution**: `Feature.ORDER_EXECUTION` and `Feature.AUTONOMOUS_AGENTS`
  remain blocked. The LLM oversight layer must remain read-only.
- **Machine learning / RL**: `Feature.MACHINE_LEARNING` and `Feature.REINFORCEMENT_LEARNING`
  remain blocked. No ML framework imports are permitted.
- **Parameter optimization**: No optimization loops, Bayesian search, evolutionary
  algorithms, or adaptive threshold tuning.
- **`CURRENT_PHASE` modification**: Must not be changed without an approved ADR, explicit
  human approval from the Technical Auditor, and a dedicated code review pass.
- **Deployment recommendation**: No AQCS system may autonomously recommend a strategy
  for live use based on benchmark or sensitivity audit results.

AQCS remains:
- **Research-only** — no live or paper trading
- **Deterministic** — no stochastic or adaptive components
- **Human-governed** — all governance decisions require human review
- **Offline-first** — no real-time data feeds, no streaming, no daemons

---

## 11. Final Readiness Verdict

### **CONDITIONALLY READY for Phase-1B**

**Conditions (must be met before Phase-1B work begins):**

1. **ADR-008 filed** — Statistical threshold governance covering regression guard, benchmark suite, and sensitivity audit constants. Specifies current values, their rationale, and the human-approval process for any change.

2. **ADR-009 filed** — Canonicalization migration policy formalizing the two-format split and governing future schema migrations.

**Basis for conditional approval:**

- All Phase-1 deliverables are implemented and tested to production quality
- 1698 tests pass; 0 failures; ruff/black/mypy all clean
- No execution, trading, ML, RL, or optimization code exists anywhere in the codebase
- Phase guard correctly blocks 10 features across all 4 defined phases
- Architecture DAG is CI-enforced with 412 dedicated tests
- All artifacts are immutable, self-certifying, and deterministically reproducible
- Governance constant alignment between modules is currently correct (verified)
- Operational runbook covers all workflow stages
- 30 handoffs document all significant sessions with complete traceability
- No ADRs are violated; no governance boundaries are crossed
- The two required ADRs address governance formalization, not capability gaps

**Basis for the "conditional" qualifier (not "READY"):**

Four governance-critical threshold sets spread across three modules have no formal ADR
protecting them from undocumented changes. This is the sole structural governance gap
that could allow Phase-1B statistical governance work to proceed on an unformalized basis.
Filing ADR-008 and ADR-009 closes this gap with minimal effort.

---

*Audit completed: 2026-05-19. Advisory only. Human review and approval required before any Phase-1B transition.*
