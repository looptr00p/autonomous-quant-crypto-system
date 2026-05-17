# AQCS Handoff Records

This directory stores completed AI agent session handoff records.

---

## Purpose

Every AI agent session that modifies the repository must produce a handoff record. Handoffs ensure that:
- No context is lost between agent sessions
- Decisions made during implementation are documented
- The next agent (human or AI) knows exactly where to continue
- Deferred work is explicitly tracked

---

## Naming convention

```
YYYY-MM-DD-HND-NNN-<slug>.md
```

Examples:
- `2026-05-17-HND-001-foundation-layer-init.md`
- `2026-05-17-HND-002-event-schema-audit-fixes.md`

Where:
- `YYYY-MM-DD` is the session date
- `HND-NNN` is the sequential handoff ID (assigned by the agent)
- `<slug>` is a brief hyphenated description

---

## Required format

Use the template at `docs/ai/HANDOFF_TEMPLATE.md`.

Every handoff must include:
- Handoff ID
- Task ID
- Objective (OBJ-NNN)
- What was changed
- Files changed
- Tests run and result
- Decisions made
- Risks / concerns
- Deferred work
- Recommended next prompt
- Human approval needed (yes/no)

---

## Archiving policy

Handoff records are permanent. They are never deleted. They form part of the institutional memory of the project.
