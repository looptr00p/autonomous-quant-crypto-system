# AQCS — Agent Entry Point

**Read this file before making any change to the repository.**  
**Every AI agent operating on AQCS must comply with this document unconditionally.**

---

## Project identity

**AQCS** (Autonomous Quant Crypto System) is an institutional-grade quantitative research laboratory for crypto spot markets. It is not a trading bot, autonomous agent runtime, or AI-operated system.

- Python package: `src/aqcs/`
- Current phase: **Phase 1 — Foundation Layer**
- Repository: `github.com/looptr00p/autonomous-quant-crypto-system`

---

## Current phase: Phase 1 — Foundation Layer

Phase 1 scope is **infrastructure only**: data acquisition, validation, event schema, configuration, logging, architecture enforcement, and governance. No trading logic, no backtesting, no strategy, no ML, no live execution.

**Do not advance the phase without explicit human approval.**

---

## Official architecture

AQCS has exactly two logical layers:

**Quant Core** — deterministic, auditable, human-designed:
`data → features → signals → portfolio → risk → execution → backtesting`

**LLM Oversight** — passive observer only:
reads events, writes narrative logs, generates `OversightReviewEvent`, never modifies Quant Core state.

The boundary between these layers is enforced by `tests/architecture/test_dependency_boundaries.py`. Any change that crosses this boundary will fail CI.

---

## Non-negotiable constraints

These apply to all agents, all phases, all contexts:

1. **The Quant Core is deterministic.** No randomness without explicit seeding. No external calls from signal/feature/portfolio/risk modules.
2. **LLM Oversight is passive.** It reads events. It never modifies state. It never trades.
3. **Humans have final approval.** No agent may merge to `master`, deploy, or modify critical config without human sign-off.
4. **Phase Guard is always active.** Do not bypass `phase_guard.assert_allowed()`. Do not modify `CURRENT_PHASE` without an approved ADR.
5. **Architecture boundary tests must pass.** Do not disable or weaken `tests/architecture/`.
6. **No secrets in code.** All credentials go in `.env` only.
7. **UTC timestamps everywhere.** No naive datetimes.
8. **Parquet before CSV.** All market data persists as Parquet with declared PyArrow schema.

---

## Forbidden actions

The following are explicitly prohibited for all AI agents in all phases:

| Forbidden | Reason |
|-----------|--------|
| Live order submission | No execution pathway exists in Phase 1 |
| Futures / leverage | Phase Guard blocks these; ADR required to advance |
| ML/RL without ADR | Requires baseline + approved design |
| Autonomous agent orchestration | AQCS is human + AI collaboration, not agent swarms |
| Kafka / Redis / Celery | No distributed infrastructure in Phase 1 |
| Microservices | Single-process research system |
| Vector memory systems | Not part of Phase 1 scope |
| Self-modifying logic | Agents do not modify their own config or role definitions |
| Scope expansion without approval | New modules require an approved Objective document |
| Merging to `master` without tests | CI must pass; human must approve |
| Modifying `configs/base.yaml` feature flags to `true` | Requires explicit human instruction |
| Bypassing `phase_guard` or disabling architecture tests | Never |

---

## Required reading before making changes

Before implementing any change, an agent must have read or verified the following documents are current:

1. **`AGENTS.md`** — this file
2. **`docs/ai/AQCS_CONTEXT.md`** — canonical project context
3. **`docs/ai/AGENT_ROLES.md`** — role boundaries and permissions
4. **`docs/ai/TASK_PROTOCOL.md`** — task format, ID system, required workflow
5. **`docs/architecture/system-architecture-v1.md`** — component specifications and DAG
6. **`docs/standards/project-standards.md`** — coding and documentation standards
7. **`docs/standards/phase-constraints.md`** — what is prohibited in the current phase
8. **`docs/architecture/event-schema.md`** — event types and bus behavior
9. **`docs/architecture/data-validation.md`** — validation rules and invariants

---

## Required workflow before implementation

For any non-trivial change (new file, new module, schema change, config change):

1. **Identify scope.** Confirm the change falls within the current Objective (`docs/objectives/`).
2. **Check for an existing ADR.** If the change requires a design decision, check `docs/decisions/`.
3. **Run the test suite.** `PYTHONPATH=src pytest tests/ -q --no-cov` must pass before and after.
4. **Run lint and type checks.** `ruff check src/ tests/` and `mypy src/` must pass.
5. **Write tests first or alongside implementation.** No code without tests.
6. **Document the handoff.** Complete `docs/ai/HANDOFF_TEMPLATE.md` before stopping.

---

## Verification commands

```bash
# From project root
PYTHONPATH=src pytest tests/ -q --no-cov     # all 297+ tests must pass
ruff check src/ tests/                        # zero lint errors
black --check src/ tests/                     # zero formatting violations
mypy src/                                     # zero type errors
```

---

## Handoff requirement

Every AI agent session that modifies the repository must produce a handoff record before stopping. Use `docs/ai/HANDOFF_TEMPLATE.md`. Submit as a Markdown file in `docs/bitacora/` or paste into the conversation for the next agent.

---

## Human approval requirement

The following actions require **explicit human approval** before execution:

- Advancing `CURRENT_PHASE` in `src/aqcs/utils/phase_guard.py`
- Enabling any feature flag in `configs/base.yaml`
- Adding new third-party dependencies
- Creating or modifying Architecture Decision Records (ADRs)
- Merging to `master`
- Introducing any execution pathway (even dry-run)
- Any scope not covered by an existing approved Objective document

When in doubt: **stop, document, and ask the human before proceeding.**
