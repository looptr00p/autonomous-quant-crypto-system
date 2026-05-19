# TASK-SENSITIVITY-AUDIT-001 Handoff

## AI Handoff

### Handoff ID
`HND-031`

### Task ID
`TASK-SENSITIVITY-AUDIT-001`

### Objective
Implement deterministic parameter sensitivity auditing for AQCS research experiments.

### Agent
Claude Code (claude-sonnet-4-6)

### Date
2026-05-19

### Status
complete

---

### What was changed

Implemented a deterministic parameter sensitivity audit layer that evaluates whether
research artifact metrics remain stable under controlled, explicit perturbations.  The
layer stress-tests each artifact metric (e.g. mean_total_return) by applying predefined
delta values, classifies instability by severity (CRITICAL/HIGH/MEDIUM/LOW), detects
governance threshold breaches, computes per-parameter stability scores, and emits a
self-certifying SensitivityAudit report.  Two CLI scripts expose the runner and
validator.

### Files changed

```
src/aqcs/research/sensitivity_audit.py        — SensitivityAudit datamodel,
                                               run_sensitivity_audit, validate,
                                               save/load, perturbation logic,
                                               stability scoring, governance checks
scripts/research/run_sensitivity_audit.py     — CLI: run audit, exit 0/1/2
scripts/research/validate_sensitivity_audit.py — CLI: validate audit hash, exit 0/1/2
tests/research/test_sensitivity_audit.py      — 52 deterministic, local tests
docs/bitacora/2026-05-19-HND-031-sensitivity-audit-001.md — this handoff
```

### Tests run

```bash
PYTHONPATH=src pytest tests/research/test_sensitivity_audit.py -q --override-ini="addopts="
# Result: 52 passed in 0.91s

PYTHONPATH=src pytest tests/ -q --override-ini="addopts="
# Result: 1698 passed in 9.26s

ruff check src/ tests/ scripts/
# Result: All checks passed!

black --check src/ tests/ scripts/
# Result: 133 files would be left unchanged.

mypy src/
# Result: Success: no issues found in 47 source files
```

### Verification result

- [x] pytest: 1698/1698 passing
- [x] ruff: 0 errors
- [x] black: 0 violations
- [x] mypy: 0 errors
- [x] architecture tests: passing (sensitivity_audit.py only imports from aqcs.utils)
- [ ] committed and pushed (pending)

---

## Summary

Deterministic parameter sensitivity auditing is now implemented.  The audit reads a
baseline artifact JSON and a perturbation config JSON, applies explicit perturbations
to numeric fields, and produces an immutable SensitivityAudit report.

## Branch
`feat/task-sensitivity-audit-001`

## Commit Hash
(pending)

## PR Link
(pending — opened against master, not merged)

## Files Changed

- `src/aqcs/research/sensitivity_audit.py` — 500+ line module
- `scripts/research/run_sensitivity_audit.py` — CLI runner
- `scripts/research/validate_sensitivity_audit.py` — CLI validator
- `tests/research/test_sensitivity_audit.py` — 52 tests

## Audit Schema

```
SensitivityAudit (frozen dataclass)
  audit_version: str
  audit_id: str                          # UUID5 of audit_hash
  generation_timestamp_utc: str          # injectable for tests
  audit_hash: str                        # SHA-256, excludes itself + timestamp
  baseline_artifact_hash: str            # SHA-256 of artifact bytes
  perturbation_definitions: tuple[PerturbationDefinition, ...]
  sensitivity_results: tuple[SensitivityResult, ...]
  benchmark_impacts: dict
  walkforward_impacts: dict
  stability_scores: dict                 # overall_stability, per_parameter, finding_counts
  instability_findings: tuple[InstabilityFinding, ...]
  warnings: tuple[str, ...]
  issues: tuple[str, ...]

PerturbationDefinition (frozen dataclass)
  parameter_name, field_path, delta_type, delta_values, description

SensitivityResult (frozen dataclass)
  parameter_name, baseline_value, perturbed_value, perturbation_magnitude,
  metric_deltas, benchmark_delta, walkforward_delta, severity,
  deterministic_diff_summary

InstabilityFinding (frozen dataclass)
  parameter_name, severity, perturbation_magnitude, baseline_value,
  perturbed_value, governance_threshold_crossed, deterministic_diff_summary
```

## Determinism Strategy

- Perturbations traversed in sorted(parameter_name) order
- Results sorted by (parameter_name, perturbation_magnitude)
- Findings sorted by (severity, parameter_name, magnitude)
- audit_hash = canonical_hash(content_dict) excluding audit_hash, audit_id, timestamp
- audit_id = uuid5(_AUDIT_NS, audit_hash)
- NaN normalized to None via normalize_nan before all serialization
- now_utc injectable for tests

## Perturbation Logic

Perturbation config is a JSON file:
- "relative" delta: perturbed = baseline * (1.0 + delta_value)
- "absolute" delta: perturbed = baseline + delta_value
- Field access via dot-notation path (e.g., "aggregate_metrics.mean_total_return")
- Missing fields → issue recorded, no crash
- Invalid config → issue recorded, audit still produced

## Stability Classification Logic

Severity thresholds (explicit constants, require ADR to change):
- INSTABILITY_LOW_THRESHOLD = 0.05  (5%)   → MEDIUM if |rel_change| >= this
- INSTABILITY_MEDIUM_THRESHOLD = 0.20 (20%) → HIGH if |rel_change| >= this
- INSTABILITY_HIGH_THRESHOLD = 0.50  (50%) → CRITICAL if |rel_change| >= this

Governance threshold breaches → always CRITICAL:
- perturbed_value < GOVERNANCE_RETURN_FLOOR (-0.10)
- perturbed_value > GOVERNANCE_DRAWDOWN_CEIL (0.30)
- perturbed_value <= GOVERNANCE_SHARPE_FLOOR (0.0)

Stability score = fraction of perturbations that are LOW severity (1.0 = fully stable).

## Validation Logic

validate_sensitivity_audit(audit) recomputes canonical_hash of content dict
(excluding audit_hash, audit_id, generation_timestamp_utc) and compares to
audit.audit_hash. Also verifies audit_id = uuid5(_AUDIT_NS, audit_hash) and
audit_version == AUDIT_VERSION.

## CLI Behavior

### run_sensitivity_audit.py
- --baseline-artifact (required): path to baseline JSON artifact
- --perturbation-config (required): path to perturbation config JSON
- --output-json (optional): write full audit to this path
- Stdout: deterministic JSON summary with has_instability, stability, advisory note
- Exit 0: all findings LOW (stable)
- Exit 1: any MEDIUM/HIGH/CRITICAL findings
- Exit 2: I/O or argument error

### validate_sensitivity_audit.py
- --audit-json (required): path to sensitivity audit JSON
- Stdout: JSON with valid, errors, stability, advisory note
- Exit 0: hash valid
- Exit 1: hash mismatch or version error
- Exit 2: file unreadable or malformed

## Tests Run

52 tests in tests/research/test_sensitivity_audit.py:
- Report generation: determinism, hash excludes timestamp, UUID5 id, immutability
- Perturbation arithmetic: relative, absolute, sorting by magnitude and name
- Severity classification: LOW/MEDIUM/HIGH/CRITICAL by magnitude + governance breach
- Instability findings: generated for MEDIUM+, not for LOW; governance threshold name
- Stability scores: fully stable, partially stable, per-parameter, finding counts
- Benchmark/walkforward deltas: return weight, drawdown weight, unknown field = 0
- Error handling: missing field, malformed config, invalid delta_type, empty deltas
- Validation: valid passes, tampered hash detected, wrong version detected
- Serialization: dict round-trip, file round-trip, invalid JSON raises ValueError
- Default config: parseable and produces results
- CLI: exit 0 (stable), exit 1 (instability), exit 2 (missing file), validate paths

## Validation Results

All four required checks pass:
- pytest: 1698/1698
- ruff: clean
- black: clean
- mypy: clean

## Risks

- **Severity classification at exact thresholds**: same IEEE 754 boundary behavior
  as in regression_guard. Tests use values clearly within each severity band (e.g.,
  0.06 for MEDIUM, not exactly 0.05). Production >= comparisons are correct.
- **Field path coverage**: the dot-notation resolver covers nested fields up to any
  depth. Non-dict intermediate nodes produce a warning and return None.
- **Benchmark delta approximation**: benchmark_delta uses static weight coefficients
  that mirror benchmark_suite.py constants. If those constants change, this module's
  private copies (_BENCH_WEIGHT_*) must be updated in tandem (ADR-required change).

## Unresolved Issues

None.

## Rollback Notes

Five new files added with no reverse dependencies. Rollback is safe: delete the five
files and revert the commit. No schema migration required.

---

## Human Approval Required

Yes. Human review required before merge to master.

## Reviewer
AQCS Technical Trading Auditor and Project Director.

## Human Approval
Required before merge.
