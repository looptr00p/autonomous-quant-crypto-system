## AI Handoff

### Handoff ID
`HND-019`

### Task ID
`TASK-RESEARCH-DAG-GOVERNANCE-001`

### Objective
`OBJ-001 — Foundation Layer / Architecture Governance`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Closed the architecture governance gap for `aqcs.research`.

`aqcs.research` was previously exempt from the dependency boundary check:
the `test_import_boundary` parametrized test has an early-return path
(`if owner not in ALLOWED: return`) that silently skipped all research files.
This meant forbidden imports in research would never fail CI.

### Branch
`fix/task-research-dag-governance-001`

### Commit
`103a6a2` — fix(arch): add aqcs.research to enforced architecture DAG

---

### Files Changed

```text
tests/architecture/test_dependency_boundaries.py  — DAG entry + 5 governance tests
docs/bitacora/2026-05-18-HND-019-research-dag-governance-001.md — this handoff
```

**No source files were modified.** Only the architecture test and handoff docs.

---

## Current Research Imports

Audited before any changes:

**`src/aqcs/research/research_validation.py`**:
- `aqcs.backtesting` (BacktestConfig, BacktestResult, run_backtest)
- `aqcs.data` (validate_ohlcv)
- `aqcs.experiments` (ExperimentTracker, ExperimentRecord)
- `aqcs.signals` (combined_momentum_trend_signal)

**`src/aqcs/research/replay_certificate.py`**:
- `aqcs.backtesting` (BacktestConfig, BacktestResult, EquityCurvePoint, Trade)
- `aqcs.experiments` (ExperimentRecord)
- `aqcs.utils` (SignalDirection)

All imports are within safe quant-core boundaries.
No violations found. No runtime behavior was changed.

---

## DAG Decision

**Decision: ADD `aqcs.research` to the enforced DAG with an explicit allowed set.**

Rationale:
1. All current research imports are safe (quant-core only).
2. The governance gap was creating risk: a future developer could add a
   forbidden import (e.g., `from aqcs.execution import ...`) and CI would
   silently pass.
3. Closing the gap costs nothing — no behavior changes, just enforcement.

**Allowed set for `aqcs.research`:**

```python
"aqcs.research": {
    "aqcs.backtesting",   # deterministic backtest engine
    "aqcs.data",          # OHLCV ingestion and validation
    "aqcs.experiments",   # experiment record persistence
    "aqcs.features",      # feature computation (returns, trend, vol)
    "aqcs.monitoring",    # data-quality checks for pre-research gates
    "aqcs.signals",       # signal generation
    "aqcs.utils",         # config, logging, events, phase guard
},
```

**Explicitly excluded** (not in allowed set):
- `aqcs.execution` — order submission, live trading
- `aqcs.risk` — live risk management
- `aqcs.portfolio` — live portfolio state
- `aqcs.llm_oversight` — LLM decision layer

**Note on `aqcs.features` and `aqcs.monitoring`:** These are included in the
allowed set even though no current research file imports them directly.
This pre-authorises anticipated legitimate uses (feature computation in
research pipelines, data-quality gates before research runs) while keeping
the excluded set meaningful.

---

## Enforcement Changes

### Before (gap)

The `test_import_boundary` parametrized test had:
```python
if owner not in ALLOWED:
    return  # silently skipped research files
```

With `aqcs.research` absent from ALLOWED, all research files were skipped.

### After (closed)

`aqcs.research` is now a key in ALLOWED. The parametrized test now runs the
full boundary check for every file in `src/aqcs/research/`. Any future forbidden
import will fail CI immediately.

### New tests added

| Test | What it verifies |
|---|---|
| `test_research_is_in_allowed_dag` | `aqcs.research` is explicitly listed in ALLOWED |
| `test_research_allowed_set_excludes_execution_layer` | Execution, risk, portfolio, llm_oversight absent from research's set |
| `test_research_current_files_pass_dag` | All current research files pass the boundary check |
| `test_research_forbidden_execution_import_is_detected` | An `aqcs.execution` import in a fake research file is flagged (regression) |
| `test_research_forbidden_llm_oversight_import_is_detected` | An `aqcs.llm_oversight` import is flagged (regression) |

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/architecture/test_dependency_boundaries.py -q --no-cov
# 47 passed in 0.08s  (was 42; +5 new governance tests)

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1124 passed in 4.55s  (master baseline; PRs #10-12 unmerged)

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 94 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 38 source files
```

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy | PASS (38 source files) |
| pytest architecture (47 tests) | PASS |
| pytest full suite (1124 tests) | PASS |
| No source files modified | PASS |
| No runtime behavior changed | PASS |
| No forbidden files modified | PASS |
| Existing architecture checks not weakened | PASS |

---

## Risks

- `aqcs.features` and `aqcs.monitoring` are in the allowed set but not
  currently imported by any research file. Including them is a governance
  pre-authorisation for anticipated use. If policy changes and these should
  be excluded, the allowed set must be updated.
- The `test_research_current_files_pass_dag` test will fail immediately if
  any new research file is added with a forbidden import — this is intentional
  and the desired behavior.

## Unresolved Issues

- PRs #10, #11, #12 are still open. They add scripts but no new `src/aqcs/`
  packages, so they don't affect this governance decision.
- `docs/architecture/system-architecture-v1.md §5` should be updated to
  reflect the `aqcs.research` DAG entry. That document was not modified here
  because it was outside the allowed files for this task. A follow-up docs
  chore is recommended.

## Rollback Notes

Revert `tests/architecture/test_dependency_boundaries.py` to the previous
version. No source code changes; rollback has zero runtime risk.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Audit performed: all current research imports verified safe
- [x] No source files modified
- [x] `aqcs.research` added to ALLOWED with explicit set
- [x] Execution layer excluded from research's allowed set
- [x] 5 new enforcement tests added
- [x] All existing checks preserved (parametrized test unchanged)
- [x] black / ruff / mypy pass
- [x] 47 architecture tests pass (up from 42)
- [x] 1124 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
