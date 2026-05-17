# AQCS Task Protocol

**Version:** 1.0.0  
**Date:** 2026-05-17

Every implementation task in AQCS must be described using this protocol before work begins. The protocol ensures traceability, scope control, and auditability across multiple AI agents.

---

## ID formats

| Type | Format | Example | Purpose |
|------|--------|---------|---------|
| Objective | `OBJ-NNN` | `OBJ-001` | High-level deliverable spanning multiple tasks |
| Task | `TASK-NNN` | `TASK-007` | Single implementation session or change set |
| Architecture Decision | `ADR-NNN` | `ADR-003` | Formal design decision record |
| Audit | `AUD-NNN` | `AUD-002` | Audit report from Strategic Auditor or Ultraplan |
| Handoff | `HND-NNN` | `HND-005` | Agent session handoff record |

IDs are sequential and never reused. The Human Founder assigns IDs for Objectives and ADRs. Agents may self-assign TASK, AUD, and HND IDs incrementally.

---

## Task document structure

Every task must be described with the following fields before implementation begins. The description may live in the conversation, in a `docs/bitacora/` entry, or in a Handoff document.

```markdown
## Task: TASK-NNN — [short title]

**Objective:** [parent OBJ-NNN]  
**Phase:** 1  
**Date:** YYYY-MM-DD  
**Agent:** [Claude Code | OpenCode | ...]  
**Status:** [planned | in_progress | complete | deferred]

### Scope
[1-3 sentences describing exactly what will be implemented.]

### Explicitly forbidden scope
[What must NOT be done in this task, even if it seems related.]

### Files expected to change
- `src/aqcs/.../file.py`
- `tests/unit/test_file.py`
- `docs/...`

### Acceptance criteria
- [ ] criterion 1
- [ ] criterion 2
- [ ] pytest passes
- [ ] ruff passes

### Verification commands
```bash
PYTHONPATH=src pytest tests/ -q --no-cov
ruff check src/ tests/
```

### Handoff requirement
[HND-NNN must be completed before the session ends.]

### Rollback notes
[If this task fails or needs to be reverted, what must be undone?]
```

---

## Required workflow

Every agent must follow this workflow for every task:

1. **Read** `AGENTS.md` and confirm the task is within the current Objective.
2. **Identify** the parent Objective ID (`OBJ-NNN`).
3. **Check** `docs/decisions/` for an existing ADR covering this change.
4. **Verify** the test suite passes before starting: `PYTHONPATH=src pytest tests/ -q --no-cov`.
5. **Implement** the change. Write tests first or alongside.
6. **Verify** the test suite passes after implementing.
7. **Run** lint: `ruff check src/ tests/`.
8. **Commit** with a descriptive message following the project convention.
9. **Push** to remote.
10. **Complete** the Handoff record before stopping.

---

## Scope control rules

- **One Objective per task.** A task may not span two Objectives.
- **No silent scope expansion.** If the task requires work beyond its stated scope, stop and ask the Human Founder before continuing.
- **No speculative implementation.** Do not implement features "while you're in there" unless explicitly authorized.
- **No architecture changes without ADR.** A change that alters the DAG, dependency rules, event schema, or phase constraints requires an ADR first.

---

## Escalation rules

Stop and escalate to the Human Founder when:
- The task requires enabling a blocked feature in `phase_guard.py`
- The task requires modifying `CURRENT_PHASE`
- The task requires a new external dependency
- The task requires merging to `main`
- The scope is unclear or extends beyond the current Objective
- An audit finding suggests the current implementation approach is wrong
- A security or data integrity issue is discovered

---

## Audit protocol

An audit (AUD-NNN) is produced by the Strategic Auditor or Ultraplan.

Every audit must classify findings as:
- **Critical blockers** — must be fixed before any further progress
- **Must fix before continuing** — fix before the next task begins
- **Should fix soon** — address within the current Objective
- **Nice to have** — deferred to backlog
- **Go / No-Go** — human makes the final decision

Audit findings are recommendations, not orders. The Human Founder decides which findings to act on.
