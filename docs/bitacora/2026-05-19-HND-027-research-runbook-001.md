## AI Handoff

### Handoff ID
`HND-027`

### Task ID
`TASK-RESEARCH-RUNBOOK-001`

### Objective
`OBJ-001 — Foundation Layer / Operational Documentation`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-19

### Status
complete — PR open, pending human review

---

### What was changed

Created `docs/runbooks/research_workflow_runbook_v1.md` — a formal operational
runbook documenting the complete approved AQCS Phase-1 deterministic research
lifecycle.

No source code, tests, scripts, CI workflows, or dependency files were modified.

### Branch
`docs/task-research-runbook-001`

### Commit
`1a9a3fb` — docs(runbook): add Phase-1 deterministic research workflow runbook

---

### Files Changed

```text
docs/runbooks/research_workflow_runbook_v1.md  — new (1,074 lines)
docs/bitacora/2026-05-19-HND-027-research-runbook-001.md — this handoff
```

---

## Runbook Sections (all 20 required sections present)

| # | Section | Content summary |
|---|---|---|
| 1 | AQCS Research Philosophy | Determinism, auditability, human-ownership-of-deployment |
| 2 | Governance Principles | DAG enforcement, phase guard, immutability, LLM boundary, no silent defaults |
| 3 | Deterministic Guarantees | Table of guarantees with mechanisms |
| 4 | Approved Operational Workflow | 11-step numbered sequence with final human review gate |
| 5 | Dataset Lifecycle | Smoke test, burn-in, data quality validation with commands |
| 6 | Manifest Lifecycle | Schema, generation, verification, deterministic guarantees |
| 7 | Replay Certification Workflow | Command, schema, hash encoding details, human checkpoint |
| 8 | Baseline Reporting Workflow | Command, schema, disclaimer, human checkpoint |
| 9 | Walk-Forward Validation Workflow | Window layout, command, leakage checks, schema |
| 10 | Research Campaign Workflow | Artifact directory structure, command, schema, type detection table |
| 11 | Benchmark Suite Workflow | Command, scoring table (weights), regression thresholds, mandatory gate |
| 12 | Artifact Lineage | ASCII diagram showing hash linkage across all artifact types |
| 13 | Canonical Hashing Rules | Canonical vs legacy format, migration policy, excluded fields |
| 14 | Operational Validation Checklist | Four required commands + targeted suites |
| 15 | Human Review Requirements | Table of decisions requiring human approval |
| 16 | Forbidden Activities | Trading, autonomous systems, streaming, data manipulation |
| 17 | Incident / Drift Investigation | Hash mismatch, replay drift, validation failures, regressions |
| 18 | Merge / Review Discipline | Branch conventions, commit format, pre-merge checklist |
| 19 | Future Work Explicitly Deferred | Table of 14 deferred capabilities with reasons |
| 20 | Phase-1 Boundaries | What is/isn't supported; enforcement mechanisms |

---

## Workflow Coverage

The runbook documents the complete approved workflow:

```
Step 1:  Public OHLCV smoke test (connectivity)
Step 2:  Public OHLCV burn-in (data acquisition)
         ↓
Step 3:  Data quality validation
         ↓
Step 4:  Manifest generation + verification
         ↓
Step 5:  Dataset registry update
         ↓
Step 6:  Fleet monitoring snapshot
         ↓
Step 7:  Research pipeline + experiment persistence
         ↓
Step 8:  Replay certification
         ↓
Step 9:  Baseline report generation
         ↓
Step 10: Walk-forward validation
         ↓
Step 11: Research campaign assembly
         ↓
Step 12: Benchmark suite generation
         ↓
         ── MANDATORY HUMAN REVIEW GATE ──
```

Each step includes: purpose, commands, exit codes, artifact outputs, validation expectations, governance boundaries, and human review checkpoints.

---

## Governance Coverage

Explicit governance statements included:

**AQCS does NOT support (§16 Forbidden Activities):**
- Live trading
- Paper trading
- Execution automation
- Portfolio automation
- Exchange account access
- Autonomous strategy mutation
- ML/RL strategy generation
- Hidden optimization loops
- Schedulers / daemons / background workers
- Autonomous deployment decisions
- Implicit gap filling
- Silent schema coercion
- Dataset mutation

**Enforcement mechanisms documented:**
- `phase_guard.py` (runtime)
- `tests/architecture/test_dependency_boundaries.py` (CI)
- `tests/governance/test_anti_live_trading.py` (CI)
- `tests/governance/test_anti_llm_execution.py` (CI)
- Human review requirements on all merges

---

## Validation Commands Included

All four canonical validation commands documented (§14):

```bash
black --check src tests scripts
ruff check src tests scripts
mypy src
PYTHONPATH=src pytest tests/ -q --no-cov
```

Plus targeted suites for architecture, research, monitoring, and data layers.

---

## Tests Run

```bash
git diff --check docs/runbooks/research_workflow_runbook_v1.md
# PASS — no trailing whitespace or merge markers

PYTHONPATH=src .venv/bin/pytest tests/architecture/ -q --no-cov
# 381 passed in 0.53s
```

## Validation Results

| Check | Result |
|---|---|
| `git diff --check` | PASS |
| `pytest tests/architecture/` | **381/381 passed** |
| No source files modified | PASS |
| No test files modified | PASS |
| No CI files modified | PASS |

---

## Risks

- PRs #20 and #21 (canonicalization + benchmark suite) were still open at documentation time. The runbook references `aqcs.utils.canonicalization` and benchmark suite scoring — both are documented as pending PRs. The runbook is accurate for the current state of master plus these pending capabilities.
- The runbook is v1.0. It should be updated whenever a new major infrastructure component is added, a phase transition occurs, or governance rules change.

## Unresolved Issues

PRs #19, #20, #21 still open. The runbook documents both the merged infrastructure and the pending PRs, noting where capabilities are upcoming.

## Rollback Notes

Delete `docs/runbooks/research_workflow_runbook_v1.md`. No runtime impact. Pure documentation rollback.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] All 20 required sections present
- [x] Complete workflow coverage (11 steps + human gate)
- [x] All forbidden activities explicitly documented
- [x] All validation commands documented
- [x] All example commands use public-only APIs and local paths
- [x] Artifact lineage diagram included
- [x] Canonical hashing rules documented
- [x] No runtime/source/test files modified
- [x] `git diff --check` passes
- [x] `pytest tests/architecture/` — 381 passed
- [x] PR opened against master
- [ ] Human approval for merge
