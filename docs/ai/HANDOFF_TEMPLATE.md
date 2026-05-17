# AQCS Agent Handoff Template

Copy this template and complete all sections before ending an agent session that modified the repository.

File the completed handoff as:
- A `docs/bitacora/YYYY-MM-DD-HND-NNN-[slug].md` entry, or
- Paste into the conversation for the next agent to read.

---

## AI Handoff

### Handoff ID
`HND-NNN`

### Task ID
`TASK-NNN`

### Objective
`OBJ-NNN — [title]`

### Agent
[Claude Code | OpenCode | Claude Opus | ...]

### Date
YYYY-MM-DD

### Status
[complete | partial | blocked]

---

### What was changed

[2-5 sentences describing what was implemented, added, or modified. Focus on the why, not just the what.]

### Files changed

```
src/aqcs/.../file.py              — [description]
tests/unit/test_file.py           — [description]
docs/architecture/something.md   — [description]
```

### Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: NNN passed in X.XXs
```

### Verification result

- [ ] pytest: NNN passing, 0 failing
- [ ] ruff: 0 errors
- [ ] black: 0 violations
- [ ] mypy: 0 errors (if applicable)
- [ ] architecture tests: passing
- [ ] committed and pushed to origin/master

---

### Decisions made

[List any design decisions taken during implementation that were not pre-specified. If an ADR should be filed, note it here.]

1. Decision: [description]  
   Rationale: [why]  
   Alternative considered: [what else was possible]

### Risks / concerns

[Any issues, edge cases, or potential regressions discovered during implementation.]

- Risk: [description] — Mitigation: [what was done or what should be done]

### Deferred work

[Work that was identified but not done in this session. Include a recommended Task ID.]

- TASK-NNN: [description of deferred work]

---

### Recommended next prompt

[The exact prompt or instruction the next agent or human should use to continue from here. Be precise — assume the next agent has no memory of this session.]

```
[paste suggested next prompt here]
```

### Human approval needed

- [ ] No — the next step is an implementation task within the current approved Objective
- [ ] Yes — [describe what requires human approval before proceeding]
