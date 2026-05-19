## AI Handoff

### Handoff ID
`HND-025`

### Task ID
`TASK-RESEARCH-ARTIFACT-CANONICALIZATION-001`

### Objective
`OBJ-001 — Foundation Layer / Serialization Governance`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-19

### Status
complete — PR open, pending human review

---

### What was changed

Implemented `src/aqcs/utils/canonicalization.py` — a centralized canonical
serialization and hashing layer.  Fixed a latent bug in
`src/aqcs/research/campaign.py` where `_verify_self_hash` used compact
separators to verify artifact hashes that were actually computed with default
separators.

### Branch
`feat/task-research-artifact-canonicalization-001`

### Commit
`b37ed43` — feat(utils): add canonical serialization layer; fix campaign hash divergence

---

### Files Changed

```text
src/aqcs/utils/canonicalization.py      — new canonical serialization module
src/aqcs/research/campaign.py           — fixed _verify_self_hash; _compute_campaign_hash now uses canonical_hash
tests/utils/__init__.py                 — new package
tests/utils/test_canonicalization.py    — 43 tests
tests/research/test_campaign.py         — test helpers now use legacy_bytes for report_hash
docs/bitacora/2026-05-19-HND-025-research-artifact-canonicalization-001.md
```

### No forbidden files modified

Verified: execution, risk, portfolio, signals, llm_oversight, phase_guard,
CI, dependencies — untouched.

---

## Canonicalization Strategy

### Two-format model

The canonicalization layer explicitly defines two formats:

**Canonical format** (`canonical_hash`) — for NEW artifact schemas post-2026-05-19:
- `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`
- NaN pre-normalized to None via `normalize_nan`
- UTF-8 encoded

**Legacy format** (`legacy_hash`) — for backward compatibility with EXISTING artifacts:
- `json.dumps(..., sort_keys=True)` (default separators `", "` and `": "`)
- ensure_ascii=True (Python default)
- NaN pre-normalized to None

### Public API

| Function | Purpose |
|---|---|
| `canonical_json(data)` | Canonical JSON string (compact separators) |
| `canonical_bytes(data)` | UTF-8 of canonical_json |
| `canonical_hash(data)` | SHA-256 of canonical_bytes |
| `legacy_json(data, *, normalize)` | Legacy JSON string (default separators) |
| `legacy_bytes(data, *, normalize)` | UTF-8 of legacy_json |
| `legacy_hash(data, *, normalize)` | SHA-256 of legacy_bytes |
| `normalize_nan(value)` | NaN → None (recursive, any structure) |
| `restore_nan(value)` | None → NaN (inverse) |
| `sha256_hex(data: bytes)` | SHA-256 of raw bytes |

---

## Hash Compatibility Findings

### Audit of all existing artifact hash computations

| Module | Hash function | Format | Affected fields |
|---|---|---|---|
| `data.manifest` | `json.dumps(sort_keys=True)` | **Legacy** | `schema_hash`, `registry_entries_hash` |
| `data.dataset_registry` | `json.dumps(sort_keys=True)` | **Legacy** | `registry_hash`, `entries_hash` |
| `monitoring.fleet_monitoring` | `json.dumps(sort_keys=True)` | **Legacy** | `registry_hash`, `registry_entries_hash` |
| `research.baseline_report` | `json.dumps(sort_keys=True)` | **Legacy** | `report_hash` (metrics uses struct.pack) |
| `research.walkforward` | `json.dumps(sort_keys=True)` | **Legacy** | `report_hash` |
| `research.replay_certificate` | `json.dumps(sort_keys=True)` | **Legacy** | `config_hash`, `parameters_hash` |
| `research.campaign` | `json.dumps(sort_keys=True, separators=(",",":"))`| **Canonical** | `campaign_hash` |

**All existing modules use legacy format.** The campaign module uses canonical
format for its own hash (introduced as the newest module, it pre-adopted the
standard being formalized here).

### The latent bug (now fixed)

`campaign._verify_self_hash` was using **canonical** (compact) separators to
re-derive the hash of external artifacts (baseline/walkforward reports).  But
those artifacts compute their `report_hash` with **legacy** (default) separators.
Result: the campaign would always record "report_hash mismatch" for any real
baseline or walk-forward report — incorrectly flagging valid artifacts as tampered.

**Fix:** `_verify_self_hash` now uses `legacy_hash` from the canonical module,
matching the format that existing artifact modules actually use.

---

## Replay Compatibility Validation

**No existing hashes were changed.**

All artifact modules (manifest, registry, fleet_monitoring, baseline_report,
walkforward, replay_certificate) retain their exact existing hash computations.
No stored artifact will produce a different hash after this change.

The STOP condition (hash-breaking migration) was NOT triggered.

---

## Determinism Validation

- `canonical_hash` is pure, stateless, deterministic
- `legacy_hash` is pure, stateless, deterministic
- `normalize_nan` is pure and recursive
- No mutable globals, no side effects
- UTF-8 encoding is explicit and consistent
- Key ordering via `sort_keys=True` in both formats
- `ensure_ascii=False` in canonical; `True` in legacy (matching original behavior)

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/utils/test_canonicalization.py -q --no-cov
# 43 passed in 0.43s

PYTHONPATH=src .venv/bin/pytest tests/research/test_campaign.py -q --no-cov
# 53 passed in 0.43s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1539 passed in 8.04s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 121 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 44 source files
```

## Test Coverage

| Class | Tests | What is verified |
|---|---|---|
| `TestCanonicalJson` | 6 | Compact separators, key sort, NaN→null, unicode, nested sort |
| `TestCanonicalHash` | 9 | Deterministic, key-order invariant, value/key change detection, NaN≡None, differs from legacy, unicode stable, regression fixture |
| `TestNanNormalization` | 11 | NaN→None, non-NaN unchanged, nested dict/list/tuple, round-trip, int/str pass-through |
| `TestLegacyFormat` | 5 | Default separators, sorted, deterministic, regression fixture, NaN pre-normalization |
| `TestSha256Hex` | 3 | Matches stdlib, deterministic, empty bytes |
| `TestBackwardCompatibility` | 5 | baseline_report matches legacy, walkforward matches legacy, campaign matches canonical, manifest format, canonical≠legacy (divergence documented) |
| `TestCrossArtifactConsistency` | 3 | campaign._verify_self_hash uses legacy, tamper detection, rejects canonical hash of legacy artifact |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS (121 files) |
| ruff | PASS |
| mypy (44 source files) | PASS |
| pytest canonicalization (43) | PASS |
| pytest campaign (53) | PASS |
| pytest full suite (1539) | PASS |
| No existing hashes changed | CONFIRMED |
| Replay compatibility preserved | CONFIRMED |
| No forbidden files modified | CONFIRMED |
| No new dependencies | CONFIRMED |

---

## Risks

- **Existing artifact modules still use legacy format.** This is deliberate —
  changing them would break stored artifacts (STOP condition). The canonical
  module documents this clearly.
- **`ensure_ascii` difference**: `canonical_json` uses `ensure_ascii=False`;
  `legacy_json` uses `True`. For all-ASCII field values (current AQCS), the
  hashes are identical between ASCII modes. For the Unicode test fixture (BTC/USDT
  — 比特币), the canonical and legacy formats will differ — the canonical hash
  is stable across platforms.
- **Future migration**: when any existing module wants to adopt `canonical_hash`,
  it must version the stored artifacts and never silently change existing hashes.
  An ADR + explicit human approval is required.

## Unresolved Issues

None. The scope of this task is complete: canonical layer created, latent bug
fixed, replay compatibility preserved.

The three low-priority follow-ups noted in HND-VALIDATION-001 (pandas `"1D"`
deprecation, DAG pre-authorization, campaign hash format assumption) are now
clarified: the campaign hash format assumption is no longer a risk because
`_verify_self_hash` is explicitly documented to use `legacy_hash`.

## Rollback Notes

Revert `src/aqcs/utils/canonicalization.py`, `src/aqcs/research/campaign.py`,
`tests/utils/`, and `tests/research/test_campaign.py` changes.
No existing artifact hashes change; rollback is zero-risk to stored data.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Canonical serialization layer created
- [x] Latent campaign hash divergence fixed
- [x] No existing artifact hashes changed
- [x] Replay compatibility confirmed
- [x] All artifact modules audited
- [x] `aqcs.utils` imports from no other `aqcs.*` packages (DAG safe)
- [x] black / ruff / mypy pass
- [x] 43 canonicalization tests + 53 campaign tests pass
- [x] 1539 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
