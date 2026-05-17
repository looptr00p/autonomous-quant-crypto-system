## AI Handoff

### Handoff ID
`HND-009`

### Task ID
`TASK-DOC-STANDARDS-003`

### Objective
`OBJ-001 — Foundation Layer`

### Agent
Codex

### Date
2026-05-17

### Status
complete

---

### What was changed

Documented the AQCS Gitflow branch model and commit message structure so all agents use the same
branch, commit, push, merge, and remote cleanup workflow after completing requested changes.

### Files changed

```text
docs/standards/project-standards.md                 — canonical Git workflow and commit rules
docs/ai/TASK_PROTOCOL.md                            — task workflow now points to the Git rules
README.md                                           — concise Git rule summary
docs/standards/standards.md                         — deprecated reference aligned with canonical rules
docs/bitacora/2026-05-17-HND-009-gitflow-commit-standards.md — this handoff
```

### Tests run

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# Result: 830 passed in 3.55s

.venv/bin/ruff check src/ tests/
# Result: All checks passed

.venv/bin/black --check src/ tests/
# Result: 63 files would be left unchanged

.venv/bin/mypy src/
# Result: Success: no issues found in 32 source files
```

### Verification result

- [x] pytest
- [x] ruff
- [x] black
- [x] mypy
- [ ] committed and pushed to remote

---

### Decisions made

1. Decision: Use `master` as the integration branch name in the standard.  
   Rationale: The GitHub repository default branch is currently `master`.

2. Decision: Prefer task-ID commit subjects when a task exists.  
   Rationale: AQCS already uses task traceability, and task IDs make commit history auditable.

3. Decision: Keep conventional prefixes available for non-task maintenance commits.  
   Rationale: Small repository hygiene commits may not have a formal task ID.

### Risks / concerns

- Risk: Existing historical commits use a mix of `TASK-*`, `feat:`, `fix:`, and `docs:` formats.  
  Mitigation: The new rule applies prospectively and documents task-ID commits as preferred.

### Deferred work

- Consider adding a lightweight commit-message check if inconsistent agent commits reappear.

---

### Recommended next prompt

```text
Commit and push TASK-DOC-STANDARDS-003 after verification passes.
```

### Human approval needed

- [x] No — this is documentation and process standardization within the current governance scope
