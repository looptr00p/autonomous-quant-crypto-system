# ADR-009: Canonicalization & Artifact Migration Policy

**Status:** Accepted  
**Date:** 2026-05-19  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-005 (Research Core), Phase-1B

---

## Context

AQCS introduced `aqcs.utils.canonicalization` on 2026-05-19 (PR #20) to provide a
single, explicitly governed serialization format for deterministic artifact hashing.
This module defines two formats:

**Canonical format** (new, post-2026-05-19):
- `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`
- UTF-8 encoded
- NaN must be normalized to `None` before serialization
- Used by: `campaign.py`, `benchmark_suite.py`, `regression_guard.py`, `sensitivity_audit.py`

**Legacy format** (pre-2026-05-19):
- `json.dumps(..., sort_keys=True)` — default separators `(", ", ": ")`, `ensure_ascii=True`
- UTF-8 encoded
- Used by: `baseline_report.py`, `walkforward.py`, `manifest.py`, `dataset_registry.py`,
  `fleet_monitoring.py`, `replay_certificate.py` (config/params hash)

The existence of two formats was a necessary consequence of the canonical module being
introduced after several artifact schemas were already implemented and their hashes stored
in the field. Migrating an existing schema to canonical format would silently invalidate
all stored artifacts — a hash-breaking change that breaks replay auditability.

This split is documented in `canonicalization.py`'s module docstring and in the operational
runbook (§13), but no ADR previously formalized the migration policy or defined when a
migration is permissible.

The absence of this ADR is a Phase-1B readiness blocker identified in AUD-007 (R-002).

---

## Decision

**AQCS adopts a formal canonicalization and artifact migration policy. Artifact hash
formats are treated as stable public interfaces. Any hash-format change is a
breaking change requiring an explicit version bump, documentation, and human approval.**

The following rules apply immediately and to all future artifact schemas:

### Rule 1 — New artifact schemas use canonical format

Any artifact schema introduced after 2026-05-19 MUST use `canonical_hash` for its
self-certifying hash. There is no exception for convenience or consistency with
legacy schemas.

### Rule 2 — Existing legacy schemas are frozen

The following schemas are permanently on the legacy format until an approved migration
is executed:

| Module | Schema | Hash field(s) | Format |
|---|---|---|---|
| `aqcs.data.manifest` | DatasetManifest | `content_hash`, `schema_hash` | legacy |
| `aqcs.data.dataset_registry` | DatasetRegistry | registry hashes | legacy |
| `aqcs.monitoring.fleet_monitoring` | FleetSnapshot | `registry_hash`, `registry_entries_hash` | legacy |
| `aqcs.research.baseline_report` | BaselineReport | `report_hash` | legacy |
| `aqcs.research.walkforward` | WalkForwardReport | `report_hash` | legacy |
| `aqcs.research.replay_certificate` | ReplayCertificate | `config_hash`, binary fields | legacy + binary |

These schemas MUST NOT be silently migrated to canonical format. A migration changes
every stored artifact's hash, breaking all replay certificates and campaign validation
that reference those artifacts.

### Rule 3 — Migration requires a version bump and explicit approval

A schema may be migrated from legacy to canonical format only when ALL of the following
are true:

1. A new ADR (or amendment to this ADR) is filed specifying:
   - which schema is being migrated
   - the new hash field value format
   - how existing stored artifacts are handled (invalidated, migrated, or archived)
   - why the migration is necessary
2. The schema's version field is incremented (e.g., `manifest_version: "1"` → `"2"`)
3. The migration is deterministic and reproducible: same input data → same new hash
4. The `load_*` function for that schema supports both the old and new version
   (backward-read compatibility) for at least one release cycle
5. Explicit human approval is granted
6. Existing stored artifacts are documented as invalidated or migrated

### Rule 4 — campaign.py's use of legacy_hash for external artifact verification

`campaign.py`'s `_verify_self_hash` function uses `legacy_hash` to verify hashes in
`BaselineReport` and `WalkForwardReport` artifacts, because those artifacts were
produced with the legacy format. This cross-format verification is intentional and
must be preserved until those schemas are migrated per Rule 3.

If a legacy schema is migrated, the corresponding verification path in `campaign.py`
must be updated in the same PR.

### Rule 5 — No hidden runtime migration

Artifact loading functions must not silently rewrite or re-hash stored artifacts.
`load_*` functions are read-only. If a stored artifact uses a legacy hash and a new
schema version expects canonical, the `load_*` function must either:
- Reject the artifact with a clear version error
- Accept it with an explicit version-compatibility flag (never silently rewrite)

### Rule 6 — Deterministic migration behavior

Any migration tool, script, or helper that re-hashes stored artifacts must:
- be deterministic (same input → same output on any conforming machine)
- produce a migration report listing every artifact affected
- require explicit human invocation (no automatic migration at import time)
- be tested with `PYTHONPATH=src pytest` before use

### Rule 7 — Self-certifying artifacts remain self-verifiable

Every artifact's `validate_*` function must remain able to verify the artifact's
own stored hash using the correct format for that schema's version. An artifact
that cannot be self-verified after migration is a migration error.

### Rule 8 — NaN normalization is mandatory before any hash computation

All artifact hashing (both legacy and canonical) must apply `normalize_nan` before
serialization. A float `NaN` in an artifact field that bypasses normalization produces
a hash that cannot be reproduced from JSON (JSON does not represent NaN natively without
`allow_nan=True`). This rule is enforced by the `canonical_bytes`/`legacy_bytes`
helpers, which accept raw data and apply normalization internally.

---

## Artifact Lifecycle

The full lifecycle of an AQCS research artifact is:

```
Generation → Self-certification → Storage → Verification → (optional) Migration
```

**Generation:** A `build_*` function computes all fields and derives the self-certifying
hash in one atomic operation. The artifact is frozen (immutable) immediately after
generation.

**Self-certification:** The hash is computed from the content dict excluding the hash
field itself and the `generation_timestamp_utc`. The hash is wall-clock-independent.

**Storage:** Artifacts are written as JSON files. The JSON representation is
deterministic (sort_keys, fixed separators). Two artifacts with identical content
produce identical JSON.

**Verification:** The `validate_*` function re-derives the hash and compares. Any
content modification invalidates the hash, making tampering detectable.

**Migration:** Permitted only under Rule 3. Migration produces a new artifact with a
new version, a new hash, and an explicit record of the old version.

---

## Replay Compatibility

Replay certificates (`ReplayCertificate`) link a specific backtest configuration to its
outputs via five independent hash fields. For replay to succeed, the following must all
match the stored certificate:

- `config_hash`: the BacktestConfig parameters
- `metrics_hash`: the 8 standard metrics
- `trades_hash`: the full trade list
- `equity_hash`: the equity curve
- `signals_hash`: the signal series

A migration that changes any hash format in any artifact referenced by a campaign
invalidates all replay certificates that reference that artifact. This is why
migrations require a version bump, explicit documentation of stored-artifact
invalidation, and human approval.

---

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Migrate all schemas to canonical now | Would invalidate all stored artifacts, breaking every existing campaign and replay certificate |
| Never migrate (freeze legacy format forever) | Increases long-term maintenance burden; legacy format has known drawbacks (whitespace, ASCII encoding) |
| Auto-migrate on load without version bump | Silent migration breaks reproducibility — the same file produces different hashes depending on when it was loaded |
| Config flag to select hash format at runtime | Creates nondeterministic behavior: two machines with different config produce different hashes for the same artifact |

---

## Consequences

**Positive:**
- Existing stored artifacts are guaranteed stable; no surprise hash invalidation
- New artifacts get the superior canonical format with its stronger determinism properties
- Migration path is defined, auditable, and explicit
- Replay auditability is preserved across all schema versions

**Negative:**
- Two coexisting formats increase cognitive overhead for new contributors
- The runbook's §13 table must be kept in sync with Rule 2's frozen-schema list as new modules are added

**Neutral:**
- No immediate code changes required; this ADR formalizes the policy already implicit in the canonicalization module's docstring
- `campaign.py`'s `legacy_hash` usage for external artifact verification (PR #20 fix) is now explicitly sanctioned

---

## Related documents

- `src/aqcs/utils/canonicalization.py` — implements both formats and the `legacy_hash` helper
- `docs/runbooks/research_workflow_runbook_v1.md` §13 — operational hashing reference
- `docs/audits/2026-05-19-AUD-007-phase-1b-readiness-audit-001.md` — identified this gap (R-002)
- `docs/bitacora/2026-05-19-HND-025-research-artifact-canonicalization-001.md` — PR #20 delivery (the fix)
- ADR-008: Statistical Governance Threshold Policy (companion ADR)
- ADR-007: Minimal backtesting engine (replay certificate origin)
