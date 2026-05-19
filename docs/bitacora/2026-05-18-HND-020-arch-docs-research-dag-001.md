## AI Handoff

### Handoff ID
`HND-020`

### Task ID
`TASK-ARCH-DOCS-RESEARCH-DAG-001`

### Objective
`OBJ-001 — Foundation Layer / Architecture Documentation`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Updated `docs/architecture/system-architecture-v1.md` (v1.0.0 → v1.0.1) to
document `aqcs.research` as a formally governed architecture component.

This closes the documentation gap that remained after
TASK-RESEARCH-DAG-GOVERNANCE-001 added `aqcs.research` to the enforced DAG.

### Branch
`docs/task-arch-docs-research-dag-001`

### Commit
`68d4b37` — docs(arch): add aqcs.research to system-architecture-v1.md §4 and §5

---

### Files Changed

```text
docs/architecture/system-architecture-v1.md  — new §4.10, updated §5, updated §8
docs/bitacora/2026-05-18-HND-020-arch-docs-research-dag-001.md — this handoff
```

**No source files, tests, or CI workflows were modified.**

---

## Documentation Updates

### §4 Table of Contents

Added:
```
- 4.10 [Research Layer](#410-research-layer)
```

### §4.10 Research Layer (new)

New section documenting `src/aqcs/research/`:
- **Responsibility**: Offline deterministic research orchestration
- **Current modules**: `research_validation.py`, `replay_certificate.py`
- **Inputs**: OHLCV Parquet, BacktestConfig, signal parameters, experiment directory
- **Outputs**: `ResearchValidationResult`, `ReplayCertificate`, experiment JSON
- **Allowed dependencies** (matching ALLOWED dict in CI test): `backtesting`, `data`, `experiments`, `features`, `monitoring`, `signals`, `utils`
- **Forbidden dependencies** (explicit): `execution`, `risk`, `portfolio`, `llm_oversight`
- **What it must NOT do**: submit orders, read private credentials, introduce look-ahead, modify raw data, produce wall-clock-dependent results, allow LLM signals into pipeline, bypass Phase Guard
- **Governance note**: references TASK-RESEARCH-DAG-GOVERNANCE-001

### §5 Dependency rules (updated)

Three changes:
1. Added `src/aqcs/research/` row with its full allowed dependency set
2. Added `src/aqcs/experiments/` row (was in the enforcement test but absent from the docs)
3. Added note: "`tests/architecture/test_dependency_boundaries.py` is the canonical source of truth"
4. Added explanatory sentence about research being an offline orchestration layer with its exclusions

### §8 Version history (updated)

Added `1.0.1 | 2026-05-18` entry summarising all changes.

Updated document header: `Version: 1.0.1`, `Date: 2026-05-18`.

---

## Tests Run

```bash
git diff --check docs/architecture/system-architecture-v1.md
# 2 trailing-whitespace findings (lines 3–4: intentional Markdown line-break
# sequences — two trailing spaces — pre-existing in the document's header block.
# The original lines 3–4 had identical trailing spaces; git diff --check flags
# them because they appear in changed lines.)

PYTHONPATH=src .venv/bin/pytest tests/architecture/ -q --no-cov
# 332 passed in 0.37s
```

## Validation Results

| Check | Result | Notes |
|---|---|---|
| `git diff --check` | 2 findings | Intentional Markdown `  ` line breaks in header (pre-existing pattern) |
| `pytest tests/architecture/` | **332/332 passed** | All boundary + forbidden + no-src-import + repo structure tests pass |
| No source files modified | PASS | Only `docs/` changed |
| No test files modified | PASS | |
| No CI workflows modified | PASS | |
| Allowed set matches enforcement test | PASS | §5 DAG matches `ALLOWED` dict in `test_dependency_boundaries.py` |

---

## Risks

- The `git diff --check` trailing-whitespace finding is cosmetic and pre-existing: the
  original document used `  ` (two spaces) as Markdown line breaks in the header block.
  Lines 3 and 4 retain this convention. Removing the trailing spaces would change the
  document's rendered formatting.
- `aqcs.features` and `aqcs.monitoring` are documented as permitted research dependencies
  even though no current research file imports them. This matches the governance decision
  in TASK-RESEARCH-DAG-GOVERNANCE-001 (pre-authorised, anticipated use).

## Unresolved Issues

- PR #13 (TASK-RESEARCH-DAG-GOVERNANCE-001) is still open. This documentation PR should
  be merged after or alongside PR #13. The two PRs are independent (docs vs. tests) but
  logically paired.
- PRs #10, #11, #12 also still open. No impact on this documentation task.

## Rollback Notes

Revert `docs/architecture/system-architecture-v1.md` to the previous version.
No runtime or test impact; pure documentation rollback.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master
- [x] PR #13 noted as open; documentation is independent
- [x] Only `docs/` files modified
- [x] §4.10 Research Layer added with correct allowed/forbidden sets
- [x] §5 dependency rules updated to match enforcement DAG
- [x] §8 version history updated
- [x] `git diff --check` run and findings noted
- [x] `pytest tests/architecture/` — 332 passed
- [x] PR opened against master
- [ ] Human approval for merge
