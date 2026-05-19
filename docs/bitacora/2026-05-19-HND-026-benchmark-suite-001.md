## AI Handoff

### Handoff ID
`HND-026`

### Task ID
`TASK-BENCHMARK-SUITE-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-011 Deterministic Benchmark Suite`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-19

### Status
complete — PR open, pending human review

---

### What was changed

Implemented `src/aqcs/research/benchmark_suite.py` — deterministic benchmark
suite infrastructure for AQCS research campaigns.  Also includes
`src/aqcs/utils/canonicalization.py` from PR #20 (prerequisite, not yet merged).

### Branch
`feat/task-benchmark-suite-001`

### Commit
`e4a3381` — TASK-BENCHMARK-SUITE-001: add deterministic benchmark suite infrastructure

---

### Files Changed

```text
src/aqcs/utils/canonicalization.py         — prerequisite from PR #20
src/aqcs/research/benchmark_suite.py       — core benchmark suite module
scripts/research/build_benchmark_suite.py  — CLI: scan campaigns, build suite
scripts/research/validate_benchmark_suite.py — CLI: validate existing suite
tests/research/test_benchmark_suite.py     — 45 tests
docs/bitacora/2026-05-19-HND-026-benchmark-suite-001.md — this handoff
```

---

## Benchmark Schema

**`BenchmarkSuite`** (frozen dataclass — 15 fields):

| Field | Type | Notes |
|---|---|---|
| `benchmark_version` | `str` | Always `"1"` |
| `benchmark_id` | `str` | UUID5 of `benchmark_hash` |
| `benchmark_name` | `str` | Caller-supplied |
| `generation_timestamp_utc` | `str` | ISO-8601; excluded from hash |
| `benchmark_hash` | `str` | SHA-256 via `canonical_hash` |
| `campaign_hashes` | `tuple[str, ...]` | Campaign hashes in sort order |
| `campaign_ids` | `tuple[str, ...]` | |
| `campaign_names` | `tuple[str, ...]` | |
| `total_campaigns` | `int` | Valid campaigns loaded |
| `comparison_entries` | `tuple[CampaignComparisonEntry, ...]` | Ranked |
| `comparison_metrics` | `dict` | Suite-level stats |
| `ranking_metrics` | `dict` | Top campaign + advisory disclaimer |
| `regression_flags` | `tuple[str, ...]` | Union of all entry flags |
| `warnings` | `tuple[str, ...]` | Non-blocking observations |
| `issues` | `tuple[str, ...]` | Load/validation failures |

**`CampaignComparisonEntry`** — 15 fields including `score`, `rank`, `score_components`, `regression_flags`.

---

## Determinism Strategy

| Property | Implementation |
|---|---|
| `benchmark_hash` | `canonical_hash(content_dict)` excluding `benchmark_hash`, `benchmark_id`, `generation_timestamp_utc` |
| `benchmark_id` | `uuid5(_BENCHMARK_NS, benchmark_hash)` — fixed namespace |
| Campaign ordering | Sorted by `(campaign_hash, campaign_id)` |
| Ranking ordering | Descending score, ties broken by `campaign_hash` |
| Regression flags | Sorted set union across all entries |
| NaN | Normalized to `None` before hashing and serialization |
| Wall-clock | Only `generation_timestamp_utc`; excluded from hash |

---

## Scoring Rules

All weights are **explicit module constants** — advisory only, never for automated selection:

| Component | Weight | Formula |
|---|---|---|
| Return | 0.30 | `clamp(mean_total_return / 1.0, 0, 1)` |
| Drawdown penalty | 0.25 | `1 - clamp(mean_max_drawdown / 1.0, 0, 1)` |
| Sharpe | 0.25 | `clamp(mean_sharpe_ratio / 3.0, 0, 1)` |
| WF coverage | 0.10 | `clamp(wf_windows / 100, 0, 1)` |
| Issue penalty | 0.10 | `1 - clamp(issue_count / 5, 0, 1)` |

**Sum = 1.0 (verified by test).**

No learned weights, no adaptive weights, no optimization. Any weight change requires ADR + human approval.

---

## Regression Logic

Explicit thresholds (module constants):

| Threshold | Constant | Direction |
|---|---|---|
| `REGRESSION_RETURN_FLOOR = -0.10` | `mean_total_return < floor` → flag |
| `REGRESSION_DRAWDOWN_CEIL = 0.30` | `mean_max_drawdown > ceil` → flag |
| `REGRESSION_SHARPE_FLOOR = 0.0` | `mean_sharpe_ratio ≤ floor` → flag |
| `REGRESSION_ISSUE_CEIL = 5` | `issue_count > ceil` → flag |

---

## Validation Logic

`validate_benchmark(suite)`:
1. Re-derive `benchmark_hash` using `canonical_hash(d_no_hash)` where `d_no_hash` excludes `benchmark_hash`, `benchmark_id`, `generation_timestamp_utc`
2. Re-derive `benchmark_id = uuid5(_BENCHMARK_NS, benchmark_hash)`
3. Check `benchmark_version == BENCHMARK_VERSION`
4. Check `total_campaigns == len(comparison_entries)`

`build_benchmark_suite`:
- Raises `ValueError` only when `campaign_jsons` list is empty
- For non-empty lists where all campaigns fail: returns suite with 0 campaigns and documented issues
- Rejects duplicates (same `campaign_hash`)
- Rejects tampered campaigns (hash mismatch in `validate_campaign`)
- Non-blocking: campaigns with `campaign.issues` become warnings

---

## CLI Behavior

```bash
PYTHONPATH=src python scripts/research/build_benchmark_suite.py \
  --campaigns-dir reports/campaigns/ \
  --benchmark-name baseline_benchmark_suite \
  --output-json reports/benchmark_suite.json
```
- Exit 0: no issues/regressions; 1: issues or regressions; 2: config errors

```bash
PYTHONPATH=src python scripts/research/validate_benchmark_suite.py \
  --benchmark-json reports/benchmark_suite.json
```
- Exit 0: valid; 1: invalid; 2: load error

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/research/test_benchmark_suite.py -q --no-cov
# 45 passed in 0.85s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1547 passed in 8.56s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 123 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success — 45 source files
```

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS (123 files) |
| ruff | PASS |
| mypy (45 source files) | PASS |
| pytest benchmark (45) | PASS |
| pytest full suite (1547) | PASS |
| No forbidden files modified | PASS |
| No new dependencies | PASS |
| No optimization/ML/RL | PASS |
| Score weights sum to 1.0 | PASS (test verified) |
| Advisory disclaimer present | PASS |
| No campaign mutation | PASS (test verified) |

---

## Risks

- `canonicalization.py` is duplicated from PR #20. Recommended merge order: PR #20 → this PR.
- `campaign.issues` is promoted to `warnings` in the benchmark (non-blocking). Campaigns with many issues are scored lower via the `issue_component` but are NOT rejected — this is correct for governance auditability where the campaign itself captures the issues.
- Scoring cap `_SHARPE_CAP = 3.0` means campaigns with Sharpe > 3.0 get full Sharpe score. This is intentional and documented.

## Unresolved Issues

PR #20 open (canonicalization). Included on this branch for self-containment.

## Rollback Notes

Delete 5 new files (including canonicalization.py if PR #20 not merged). No existing files modified.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Benchmark suite is deterministic and self-certifying
- [x] Score weights are explicit constants (sum to 1.0)
- [x] Rankings are advisory only with explicit disclaimer
- [x] No strategy mutation, optimization, or ML/RL
- [x] Campaign artifacts are not mutated
- [x] Duplicate and tampered campaigns are rejected
- [x] black / ruff / mypy pass
- [x] 45 tests pass
- [x] 1547 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
