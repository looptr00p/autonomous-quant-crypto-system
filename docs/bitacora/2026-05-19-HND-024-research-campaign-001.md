## AI Handoff

### Handoff ID
`HND-024`

### Task ID
`TASK-RESEARCH-CAMPAIGN-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-010 Deterministic Research Campaign Orchestration`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-19

### Status
complete — PR open, pending human review

---

### What was changed

Implemented deterministic research campaign orchestration in
`src/aqcs/research/campaign.py`.  A `ResearchCampaign` is an immutable,
self-certifying orchestration artifact that links DatasetManifest,
ReplayCertificate, WalkForwardReport, and BaselineReport JSON artifacts into
a reproducible campaign object with aggregate metrics and full lineage.

### Branch
`feat/task-research-campaign-001`

### Commit
`61e2a8b` — TASK-RESEARCH-CAMPAIGN-001: add deterministic research campaign orchestration

---

### Files Changed

```text
src/aqcs/research/campaign.py        — core orchestration module
scripts/research/build_campaign.py   — CLI: scan artifacts, build campaign
scripts/research/validate_campaign.py — CLI: validate existing campaign
tests/research/test_campaign.py      — 53 tests
docs/bitacora/2026-05-19-HND-024-research-campaign-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

### Design note: no import of unmerged modules

PRs #10–17 all open. The campaign does NOT import from `aqcs.research.walkforward`
(PR #17) or `aqcs.research.baseline_report` (PR #16). Instead, it reads persisted
JSON artifacts and classifies them by field-based type detection. This makes the
campaign fully self-contained on current master.

---

## Campaign Schema

**`ResearchCampaign`** (frozen dataclass — 20 fields):

| Field | Type | Notes |
|---|---|---|
| `campaign_version` | `str` | Always `"1"` |
| `campaign_id` | `str` | UUID5 derived from `campaign_hash` |
| `campaign_name` | `str` | Caller-supplied |
| `generation_timestamp_utc` | `str` | ISO-8601; excluded from hash |
| `campaign_hash` | `str` | SHA-256 of all other fields (compact JSON) |
| `dataset_manifest_hashes` | `tuple[str, ...]` | Sorted `content_hash` values |
| `replay_certificate_hashes` | `tuple[str, ...]` | Sorted `config_hash` values |
| `walkforward_report_hashes` | `tuple[str, ...]` | Sorted `report_hash` values |
| `baseline_report_hashes` | `tuple[str, ...]` | Sorted `report_hash` values |
| `total_experiments` | `int` | len(baseline artifacts) |
| `total_walkforward_windows` | `int` | sum of n_windows across WF reports |
| `symbols` | `tuple[str, ...]` | Sorted unique symbols from manifests |
| `timeframes` | `tuple[str, ...]` | Sorted unique timeframes from manifests |
| `aggregate_metrics` | `dict[str, Any]` | Return/Sharpe/trades/win_rate/WF stats |
| `aggregate_drawdown` | `dict[str, Any]` | mean/max/min/std drawdown |
| `aggregate_turnover` | `dict[str, Any]` | mean turnover/fees/slippage |
| `aggregate_exposure` | `dict[str, Any]` | mean exposure/holding period |
| `artifact_hashes` | `dict[str, str]` | `{relative_path: sha256_of_file_bytes}` |
| `issues` | `tuple[str, ...]` | Sorted validation issues |
| `warnings` | `tuple[str, ...]` | Sorted advisory warnings |

---

## Determinism Strategy

| Property | Implementation |
|---|---|
| `campaign_hash` | SHA-256 of `json.dumps(content, sort_keys=True, separators=(",", ":"))` excluding `campaign_hash`, `campaign_id`, `generation_timestamp_utc` |
| `campaign_id` | `uuid.uuid5(_CAMPAIGN_NS, campaign_hash)` with fixed namespace |
| Artifact traversal | `sorted(artifacts_dir.rglob("*.json"))` |
| Hash reference lists | All reference hash tuples sorted alphabetically |
| Artifact sort order | Manifests by `content_hash`; certs by `experiment_id`; WF by `report_hash`; baselines by `report_hash` |
| NaN handling | `float("nan")` → `null` in JSON; `null` → `float("nan")` on load |
| Wall-clock | Only `generation_timestamp_utc`; excluded from hash computation |

---

## Artifact Linkage Logic

**Type detection by discriminating fields:**

| Type | Required discriminating fields |
|---|---|
| DatasetManifest | `manifest_version`, `content_hash`, `schema_hash`, `exchange` |
| ReplayCertificate | `certificate_version`, `certified_bars`, `config_hash` |
| WalkForwardReport | `train_bars`, `step_bars`, `leakage_validated`, `n_windows` |
| BaselineReport | `benchmark_total_return`, `disclaimer`, `initial_capital` |

Unrecognised files → `warnings`. Malformed JSON → `issues`.

**`artifact_hashes`**: SHA-256 of raw file bytes for each JSON file (keyed by path relative to `artifacts_dir`). This is a Merkle-leaf structure — any file change changes the campaign_hash.

**Self-certifying hash verification**: for WalkForwardReport and BaselineReport (which have `report_hash` fields), the campaign re-derives the hash and records a mismatch in `issues`.

---

## Validation Logic

`validate_campaign(campaign)`:
1. Re-derives `campaign_hash` from content dict (excluding hash, id, timestamp)
2. Re-derives `campaign_id = uuid5(NAMESPACE, campaign_hash)`
3. Checks `campaign_version == CAMPAIGN_VERSION`
4. Re-raises all `campaign.issues` as errors

Returns `(is_valid: bool, errors: list[str])`.

---

## CLI Behavior

**`build_campaign.py`**
```bash
PYTHONPATH=src python scripts/research/build_campaign.py \
  --artifacts-dir experiments/campaign_inputs/ \
  --campaign-name baseline_campaign \
  --output-json reports/campaign_report.json
```
- Exit 0: no issues; 1: issues detected; 2: config errors

**`validate_campaign.py`**
```bash
PYTHONPATH=src python scripts/research/validate_campaign.py \
  --campaign-json reports/campaign_report.json
```
- Exit 0: valid; 1: invalid; 2: load error

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/research/test_campaign.py -q --no-cov
# 53 passed in 0.74s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1180 passed in 4.53s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 98 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 39 source files
```

## Test Coverage Summary

| Class | Tests | What is verified |
|---|---|---|
| `TestArtifactTypeDetection` | 6 | Manifest, cert, WF, baseline detected; unknown; empty |
| `TestCampaignGeneration` | 8 | All fields, UUID5 id, timestamp injection, symbols, timeframes, counts, empty warnings, unknown file warning |
| `TestCampaignHash` | 4 | Deterministic, changes on artifact change, excludes timestamp, changes on name change |
| `TestValidation` | 7 | Valid passes, tampered hash, tampered id, missing manifest field, missing baseline field, tampered report hash, duplicate artifact |
| `TestAggregateMetrics` | 8 | Mean return, profitable count, mean drawdown, exposure, turnover, WF aggregate, empty NaN, manifest hashes sorted |
| `TestSerialization` | 9 | Round-trip dict (JSON), NaN→null, null→NaN, JSON deterministic, save/load, invalid JSON, missing field, immutable, save creates dirs |
| `TestDeterminism` | 2 | Two builds same hash, different file order same hash |
| `TestCLIBuild` | 4 | Exit 0, exit 1 (issues), writes JSON, stdout summary |
| `TestCLIValidate` | 4 | Exit 0, exit 1 (tampered), exit 2 (malformed), required fields |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (39 source files) | PASS |
| pytest campaign (53 tests) | PASS |
| pytest full suite (1180 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies | PASS |
| No optimization/ML/RL | PASS |
| No execution logic | PASS |

---

## Risks

- Campaign does NOT import from `aqcs.research.walkforward` or `aqcs.research.baseline_report` (PRs #16/#17, unmerged). Field-based type detection is robust but relies on discriminating fields being stable across artifact versions. If those artifact schemas change, the detection fields should be reviewed.
- `_verify_self_hash` for baseline/WF reports uses the same compact JSON format (`separators=(",", ":")`) as the reference hash computation. If those modules change their hash computation format, re-verification will produce false mismatches. This is a known risk of cross-module hash verification without shared constants.
- `validate_campaign` promotes `campaign.issues` to errors. A campaign with missing artifact type warnings (e.g., no manifests) will have those warnings in `campaign.warnings`, not `campaign.issues`, so `validate_campaign` can return `valid=True` even when only baselines are present.

## Unresolved Issues

PRs #10–17 still open. No dependency on any of them.

## Rollback Notes

Delete 4 new files. No existing files modified.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master
- [x] PRs #10-17 noted as open; no import dependency on any
- [x] No forbidden files modified
- [x] No optimization, ML/RL, execution logic
- [x] Determinism: content-addressable hash, UUID5 id, sorted traversal
- [x] black / ruff / mypy pass
- [x] 53 campaign tests pass
- [x] 1180 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
