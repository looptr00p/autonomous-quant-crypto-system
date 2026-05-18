# HND-011: Agent Workflow Standard

## Handoff ID

`HND-011`

## Task ID

`TASK-GOVERNANCE-AGENT-WORKFLOW-001`

## Objective

`OBJ-001 — Foundation Layer`

## Agent

Codex

## Date

2026-05-17

## Status

complete

## What was changed

Added a canonical AQCS agent workflow standard because the existing Gitflow
rules were split across project standards and task protocol docs, lacked a
standard prompt footer, and had no focused governance test protecting the
required branch, PR, merge, handoff, and clean-tree wording.

Branch: `feat/task-governance-agent-workflow-001`

Commits:

- `ac4b808` — `docs(governance): add agent workflow standard`
- `d3457fc` — `test(governance): validate workflow governance docs`

## Files changed

```text
docs/governance/agent_workflow_standard.md  — canonical coding-agent workflow standard
AGENTS.md                                  — required-reading and workflow reference update
tests/governance/test_agent_workflow_docs.py — governance regression tests for the standard
docs/handoffs/HND-011-agent-workflow-standard.md — this handoff
```

## Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: failed before implementation due to unrelated monitoring CLI JSON-output tests.

PYTHONPATH=src .venv/bin/python -m pytest tests/governance/test_agent_workflow_docs.py -q
# Result: 5 passed

.venv/bin/pytest
# Result: 920 passed, 6 failed in tests/monitoring/test_data_quality.py

.venv/bin/ruff check .
# Result: all checks passed

.venv/bin/black --check src tests scripts docs
# Result: 81 files would be left unchanged

.venv/bin/mypy .
# Result: success, no issues found in 41 source files
```

## Verification result

- [x] governance test: 5 passing
- [ ] pytest: full suite blocked by unrelated monitoring CLI failures present before this task
- [x] ruff: 0 errors
- [x] black: 0 violations
- [x] mypy: 0 errors
- [x] architecture tests: not directly changed; full run reached architecture tests successfully
- [x] committed to task branch
- [ ] pushed to origin and PR opened

## Decisions made

1. Decision: Add `docs/governance/agent_workflow_standard.md` instead of replacing `docs/standards/project-standards.md`.  
   Rationale: The task asked for a canonical governance document while preserving existing standards where appropriate.  
   Alternative considered: Move all Gitflow rules into the new document, but that would create unnecessary churn and risk conflicts.

2. Decision: Reference the new standard from `AGENTS.md` required reading and workflow sections only.  
   Rationale: This keeps the entry-point update minimal and avoids duplicating the full standard in multiple places.  
   Alternative considered: Updating `CLAUDE.md`, but `AGENTS.md` is sufficient as the universal entry point.

## Risks / concerns

- Risk: The repository had unrelated uncommitted monitoring files before this task.  
  Mitigation: They were not edited or staged as part of this governance task.
- Risk: Full pytest baseline failed before implementation in monitoring CLI tests.  
  Mitigation: Treat those failures as pre-existing and validate the new governance test independently.

## Deferred work

- None for this task.

## Recommended next prompt

```text
Review PR for TASK-GOVERNANCE-AGENT-WORKFLOW-001. Confirm that docs/governance/agent_workflow_standard.md is the canonical agent workflow standard, that AGENTS.md references it, and that tests/governance/test_agent_workflow_docs.py provides sufficient wording and section regression coverage. Do not merge until human approval is explicit.
```

## Human approval needed

- [ ] No — the next step is an implementation task within the current approved Objective
- [x] Yes — human review required before merge
