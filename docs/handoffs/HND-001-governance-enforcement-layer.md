# AI Handoff

## Handoff ID
HND-001

## Task ID
TASK-001 — Governance MVS + Governance Enforcement Layer + Operational Governance Enforcement Layer

## Objective
OBJ-001 — Foundation Layer

## Agent
Claude Code (claude-sonnet-4-6)

## Date
2026-05-17

## Status
Complete

---

## What was changed

Three governance layers were implemented in sequence across AQCS Phase 1:

**Governance Minimal Viable System (MVS)**
Established the shared context, role definitions, task protocol, handoff template, agent registry, ADR system, and objective tracking. This gave every AI agent a single entry point (`AGENTS.md`) and a consistent vocabulary for roles, tasks, and decisions.

**Governance Enforcement Layer**
Converted governance documents from "exist" to "are automatically validated." Added four test modules in `tests/governance/` that verify ADR structure, objective structure, agent registry completeness, and cross-document consistency. Found and fixed four real inconsistencies during implementation: ADR-001 missing `## Related documents`, AQCS_CONTEXT.md with unresolved forward objective references, OBJ-003 referencing a non-existent future objective, and AGENTS.md missing `docs/ai/TASK_PROTOCOL.md` from its required reading list.

**Operational Governance Enforcement Layer**
Added enforcement that goes beyond document consistency into operational boundary verification. Five test modules verify: no order submission calls exist in source code (AST-based), no leverage/margin API calls, Phase 1 feature flags remain false in config, LLM Oversight has no signal generation functions, LLM Oversight only imports from `aqcs.utils`, the public API of `OversightObserver` is constrained to `subscribe` and `generate_review`, `generate_review()` is annotated to return only `OversightReviewEvent`, and handoff/audit/task cross-references are internally consistent.

## Files changed

```
AGENTS.md                                      — new: agent entry point
docs/ai/AQCS_CONTEXT.md                        — new: canonical project context
docs/ai/AGENT_ROLES.md                         — new: 8 agent roles with allowed/forbidden actions
docs/ai/TASK_PROTOCOL.md                       — new: task format and ID system
docs/ai/HANDOFF_TEMPLATE.md                    — new: mandatory handoff format
docs/ai/agent_registry.yaml                    — new: static agent registry
docs/handoffs/README.md                        — new: handoff naming and format
docs/audits/README.md                          — new: audit naming and format
docs/decisions/ADR-000-template.md             — new: ADR format template
docs/decisions/ADR-001-stack-selection.md      — updated: added ## Related documents
docs/decisions/ADR-002-quant-core-llm-oversight.md  — new
docs/decisions/ADR-003-event-logged-architecture.md — new
docs/decisions/ADR-004-governance-minimal-viable-system.md — new
docs/objectives/OBJ-001-foundation-layer.md    — new
docs/objectives/OBJ-002-data-validation-layer.md — new
docs/objectives/OBJ-003-experiment-tracking.md — new
docs/bitacora/0006-multi-agent-governance.md   — new: governance decision record
tests/governance/__init__.py                   — new
tests/governance/test_agent_registry.py        — new: 11 tests
tests/governance/test_adr_structure.py         — new: 11 tests (parametrized)
tests/governance/test_objective_structure.py   — new: 15 tests (parametrized)
tests/governance/test_cross_references.py      — new: 5 tests
tests/governance/test_anti_live_trading.py     — new: 11 tests
tests/governance/test_anti_llm_execution.py    — new: 8 tests (parametrized)
tests/governance/test_handoff_structure.py     — new: 6 tests + conditional parametrize
tests/governance/test_audit_structure.py       — new: 6 tests + conditional parametrize
tests/governance/test_task_traceability.py     — new: 9 tests + conditional parametrize
tests/architecture/test_repo_structure.py      — updated: added governance files to EXPECTED_FILES
.github/workflows/ci.yml                       — updated: explicit steps for architecture/governance/unit
```

## Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: 395 passed, 14 skipped in 1.79s
```

Skipped tests are intentional: parametrized handoff/audit/traceability tests skip when no HND-*.md or AUD-*.md files exist. Once this handoff and AUD-001 are committed, those tests will activate.

## Verification result

- [x] pytest: 395 passing, 14 skipped (expected), 0 failing
- [x] ruff: 0 errors
- [x] black: 0 violations
- [x] mypy: 0 errors
- [x] architecture tests: passing
- [x] governance enforcement tests: passing
- [x] anti-live-trading tests: passing
- [x] anti-LLM-execution tests: passing
- [x] committed and pushed to origin/master

---

## Decisions made

1. **Governance records are documentation-only.** The enforcement system (tests) validates document structure but introduces no runtime execution, no agent orchestration, and no dynamic agent discovery. The `agent_registry.yaml` is static and never loaded by application code.

2. **Handoff/audit tests use conditional parametrize.** When no HND-*.md or AUD-*.md files exist, the parametrized tests produce zero test cases (not failures). This avoids false failure for empty-but-valid directories.

3. **Anti-live-trading uses AST scanning, not string search.** `ast.Attribute` access for order methods is more precise than grep: it catches `exchange.create_order(...)` but not legitimate string mentions in comments or docs.

4. **OversightObserver public API is explicitly constrained.** The test enumerates exactly which public methods are allowed (`subscribe`, `generate_review`). Any future addition of a public method requires updating the allowlist — making the addition explicit and reviewed.

5. **CI splits tests into three labeled steps.** Architecture, governance, and unit tests run as separate steps after lint. This makes failures immediately diagnosable in CI output without scanning through a monolithic test run.

## Risks / concerns

- The governance enforcement tests scan `src/aqcs/` at collection time using `Path.rglob()`. If test collection happens from a non-root directory, path resolution could fail. Mitigated by using `Path(__file__).resolve().parents[N]` (absolute paths) throughout.
- The `test_oversight_observer_public_methods_are_allowed` test is sensitive to method naming in `observer.py`. If a new private method is added (prefixed with `_`), it passes automatically. If a new public method is added without updating the allowlist, the test fails — which is the intended behavior.
- Governance documents must be kept current as the project evolves. Stale `AQCS_CONTEXT.md` would mislead AI agents. This is a process concern, not a technical one.

## Deferred work

- TASK-002: Implement OBJ-003 Experiment Tracking (next)
- Pre-commit hooks to run `ruff` and `black` locally before push
- Explicit layer allowlists (which modules each component is permitted to interact with)
- Stricter external API boundary tests (verify ccxt is only called with read-only permissions)
- Future HND and AUD records per major task

---

## Recommended next prompt

```
Implement OBJ-003: Experiment Tracking for AQCS Phase 1.

Context:
- Objective defined in docs/objectives/OBJ-003-experiment-tracking.md
- Architecture: src/aqcs/backtesting/ (experiment runner)
- Events available: ExperimentStartedEvent, ExperimentCompletedEvent, ExperimentFailedEvent
- Standards: docs/standards/project-standards.md §4 (experiment record format)

Required deliverables:
1. src/aqcs/backtesting/experiment.py — ExperimentRecord dataclass
2. src/aqcs/backtesting/runner.py — ExperimentRunner that captures records and emits events
3. experiments/<id>/record.md + metrics.json storage
4. tests/unit/test_experiment.py — no network calls
5. docs/architecture/experiment-tracking.md

Restrictions: no ML, no backtesting engine, no live data, no external dependencies.
Follow AGENTS.md before starting.
```

## Human approval needed

- [ ] No — the next step (OBJ-003 Experiment Tracking) is within the approved roadmap and does not require new architecture decisions, phase changes, or new runtime dependencies.
