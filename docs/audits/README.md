# AQCS Audit Records

This directory stores formal audit records produced by the Strategic Auditor or Ultraplan.

---

## Purpose

Audit records document critical reviews of the implementation, architecture, or governance system. They:
- Classify findings as Critical / Must Fix / Should Fix / Nice to Have
- Provide a Go / No-Go verdict as input to human decision-making
- Create a permanent record of what was reviewed and when

Audits are recommendations. The Human Founder decides which findings to act on.

---

## Naming convention

```
YYYY-MM-DD-AUD-NNN-<slug>.md
```

Examples:
- `2026-05-17-AUD-001-phase1-foundation-audit.md`
- `2026-05-17-AUD-002-event-schema-audit.md`

Where:
- `YYYY-MM-DD` is the audit date
- `AUD-NNN` is the sequential audit ID
- `<slug>` is a brief hyphenated description of what was audited

---

## Required format

Each audit record must include:

```markdown
# AUD-NNN: [Audit title]

**Date:** YYYY-MM-DD
**Auditor:** [Strategic Auditor | Ultraplan]
**Scope:** [what was audited]
**Objective:** [OBJ-NNN if applicable]

## Critical blockers
## Must fix before continuing
## Should fix soon
## Nice to have
## Go / No-Go verdict
## Final technical verdict
```

---

## Relationship to implementation

Audit findings drive Tasks (TASK-NNN). A Critical blocker finding typically results in a new Task assigned to Claude Code or OpenCode. The Human Founder decides priority and sequencing.
