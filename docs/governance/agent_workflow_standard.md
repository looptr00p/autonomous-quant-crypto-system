# AQCS Agent Workflow Standard

**Version:** 1.0.0  
**Date:** 2026-05-17  
**Status:** Mandatory  
**Scope:** All coding agents making repository changes in AQCS.

This document is the canonical repository workflow and agent-delivery governance
standard for AQCS. It extends the project Git rules in
`docs/standards/project-standards.md#6-git-workflow` and the task protocol in
`docs/ai/TASK_PROTOCOL.md`.

This standard is documentation and governance enforcement only. It does not add
CI enforcement, git hooks, pre-commit automation, workflow scripts, or runtime
logic.

## AQCS Standard Prompt Footer

Attach this footer to every future coding-agent implementation prompt for AQCS:

```text
AQCS Standard Prompt Footer:
- Follow AGENTS.md and docs/governance/agent_workflow_standard.md.
- Never work directly on master.
- Create a fresh task-scoped branch before changes.
- Commit atomically with the required task or conventional commit format.
- Push the branch to origin and open a PR against master.
- Do not merge. Human review required before merge.
- Provide a handoff summary before stopping.
- Leave the repository in a clean final delivery state, or explicitly report unrelated pre-existing changes.
```

## Mandatory Git Workflow

Agents must begin every repository-modifying task from the protected integration
branch and then move work onto a task-scoped branch.

Required rules:

- Never work directly on master.
- Never commit directly to `master`.
- Start from an updated `master` unless the human explicitly instructs otherwise.
- Create a fresh branch for the task before modifying files.
- Do not reuse old task branches for new work.
- Keep branch names lowercase kebab-case with an approved prefix from
  `docs/standards/project-standards.md#6-git-workflow`.
- Stage explicit task files only.
- Do not stage unrelated local changes.

For a prompt that provides an exact branch name, use that exact branch name.
Otherwise, derive a task-scoped name from the task ID and scope.

## Mandatory Commit Discipline

Commits must be atomic, reviewable, and tied to a single task purpose.

Required rules:

- Use one commit for one coherent change.
- Split unrelated documentation, tests, and implementation only when doing so
  makes review clearer.
- Use the commit format required by the active task prompt when provided.
- If the task prompt does not provide a format, use the AQCS task format from
  `docs/ai/TASK_PROTOCOL.md` or the conventional prefixes in
  `docs/standards/project-standards.md`.
- Do not include generated caches, temporary files, secrets, local environment
  files, or unrelated working-tree changes.
- Before committing, verify the diff contains only the approved scope.

## Mandatory Push and PR Workflow

Every completed task branch must be pushed for human review.

Required rules:

- Push the task branch to `origin`.
- Open a pull request against `master`.
- Include the task ID and concise scope in the PR title.
- Include the handoff summary or a link to the handoff record in the PR body.
- Include commands run and validation results in the PR body.
- Do not merge the PR as the implementation agent.
- Report the branch name, commit hash, and PR link before stopping.

## Mandatory Merge Discipline

The implementation agent does not merge its own work.

Required rules:

- Human review required before merge.
- CI and required verification must pass before merge.
- No direct pushes to `master`.
- No merge may bypass the Human Founder approval rules in `AGENTS.md`.
- After human-approved merge, delete the merged remote branch.
- Return the local checkout to updated `master` only after the merge is complete
  and approved.

## Required Handoff Content

Every repository-modifying session must produce a handoff using
`docs/ai/HANDOFF_TEMPLATE.md`.

The handoff must include:

- Task ID and objective.
- Branch name.
- Commit hash or hashes.
- PR link, if opened.
- Files changed.
- Tests added or updated.
- Commands run and validation results.
- Known limitations and pre-existing unrelated working-tree changes.
- Rollback notes.
- Human approval still required.

## Required Final Delivery State

Before stopping, the implementation agent must leave the repository in a
reviewable state.

Required rules:

- Task files are committed atomically.
- Task branch is pushed to `origin`.
- PR is opened against `master`.
- Handoff record is completed.
- Working tree is clean for all task-owned files.
- Any unrelated pre-existing dirty files remain unstaged and are reported.
- No direct merge to `master` has been performed.

If the agent cannot satisfy the final delivery state because of permissions,
remote access, failing unrelated tests, or pre-existing dirty files, the agent
must report the blocker explicitly and stop without weakening the standard.
