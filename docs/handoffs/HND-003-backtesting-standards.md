# AI Handoff

## Handoff ID
HND-003

## Task ID
TASK-003 — Backtesting Standards Layer (OBJ-004)

## Objective
OBJ-004 — Backtesting Standards Layer

## Agent
Claude Code (claude-sonnet-4-6)

## Date
2026-05-17

## Status
Complete

---

## What was changed

Implemented the Backtesting Standards Layer for AQCS Phase 1. This is intentionally documentation-only — no simulation engine code was introduced.

The central deliverable is `docs/architecture/backtesting-standards.md`, a 12-section policy document that defines what constitutes a valid AQCS backtest. It must be satisfied by any future backtesting engine before that engine can be merged to `main`. Key sections:

- **§C — Forbidden assumptions:** 9 prohibited assumptions (zero slippage, zero fees, lookahead, etc.)
- **§D — Lookahead bias prevention:** Signal timestamping rule, feature availability rule, rolling window cold-start, target leakage prevention, delayed feature availability
- **§E — Execution timing:** Signal at T-close, execution at T+1-open, fill price formula, intrabar limitations
- **§F — Fee and slippage:** Default 10 bps taker fee, 5 bps half-spread, both mandatory, configurable via YAML
- **§G — Data standards:** Validated OHLCV only, UTC, dataset fingerprinting, gap handling policy (default: halt)
- **§H — Experiment tracking:** Every backtest creates ExperimentRecord with git hash, fingerprint, full parameters, metrics, artifacts
- **§I — Minimum metrics:** 11 required metrics (total_return, CAGR, max_drawdown, Sharpe, Sortino, volatility, turnover, win_rate, profit_factor, exposure, n_trades)
- **§J — Future validation:** Walk-forward, OOS, regime, Monte Carlo, stress testing — defined but not implemented
- **§K — Phase 1 prohibitions:** Live trading, RL, autonomous execution, HFT, distributed clusters
- **§L — Future architecture:** aqcs.backtesting.engine, execution, metrics, validation — specified but not built

ADR-005 documents the rationale for standards-before-engine. OBJ-004 tracks the deliverables.

## Files changed

```
docs/architecture/backtesting-standards.md         — new (canonical policy, 12 sections)
docs/decisions/ADR-005-backtesting-standards-before-engine.md — new
docs/objectives/OBJ-004-backtesting-standards.md   — new (status: Complete)
docs/handoffs/HND-003-backtesting-standards.md     — this file
docs/audits/AUD-003-backtesting-standards.md       — new
tests/architecture/test_repo_structure.py          — updated (new files in EXPECTED_FILES)
```

## Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: 540 passed (after updates)
```

## Verification result

- [x] pytest: passing, 0 failing
- [x] ruff: 0 errors
- [x] black: 0 violations
- [x] governance tests: passing
- [x] architecture tests: passing
- [x] No backtesting engine code introduced
- [x] committed and pushed to origin/master

---

## Decisions made

1. **Used ADR-005, not ADR-004.** ADR-004 is already taken by the governance MVS decision. Sequential numbering preserved.
2. **Standards document is non-negotiable and mandatory.** The document uses "Must" language intentionally. Future PRs that introduce a backtesting engine can be checked against this document as a compliance checklist.
3. **Default gap policy is "halt".** More conservative than carry-forward. Researchers who need carry-forward must explicitly declare it in their experiment parameters.
4. **Default execution timing is T+1 open.** This is the most common and most conservative daily-bar assumption. It avoids any bar-close omniscience.
5. **Fee model defaults are Binance spot tier 0.** These are the worst-case fees for the default exchange. Researchers who expect lower fees (e.g., from a higher-volume tier) must justify this in their experiment notes.

## Risks / concerns

- The standards document is only as valuable as the enforcement around it. Currently, enforcement is limited to existence checks (does the file exist?). Future enforcement should include structural checks that the backtesting engine satisfies each section — this requires the engine to exist first.
- Section §J (validation standards) describes walk-forward, OOS, and Monte Carlo analysis. These are complex to implement correctly. They should not be rushed into Phase 2. Phase 3 is the appropriate target.

## Deferred work

- TASK-004: Implement backtesting engine (`aqcs.backtesting.engine`) — Phase 2
- TASK-005: Implement metrics library (`aqcs.backtesting.metrics`) — Phase 2
- TASK-006: Implement execution model (`aqcs.backtesting.execution`) — Phase 2
- TASK-007: Implement validation framework (`aqcs.backtesting.validation`) — Phase 3

---

## Recommended next prompt

```
Conduct a Phase 1 closure audit for AQCS.

Context:
Phase 1 Foundation Layer objectives are now complete:
- OBJ-001: Foundation Layer (complete)
- OBJ-002: Data Validation Layer (complete)
- OBJ-003: Experiment Tracking Layer (complete)
- OBJ-004: Backtesting Standards Layer (complete — documentation only)

The project now has:
- 540+ tests passing
- Architecture enforcement active
- Governance enforcement active
- Anti-live-trading enforcement active
- Anti-LLM-execution enforcement active
- Backtesting standards defined (no engine yet)
- Experiment tracking live
- Data validation live

Before advancing to Phase 2 (Feature Engineering, Backtesting Engine):

1. Run a complete Phase 1 audit covering all OBJ-001 acceptance criteria.
2. Verify all governance records are complete.
3. Verify no architectural boundary violations.
4. Issue a formal Go / No-Go for Phase 2.

Read AGENTS.md and docs/ai/AQCS_CONTEXT.md before starting.
```

## Human approval needed

- [x] No — OBJ-004 is documentation-only and within the approved Phase 1 roadmap. Advancing to Phase 2 requires a Phase 1 closure audit (recommended next step above) which is a human strategic decision.
