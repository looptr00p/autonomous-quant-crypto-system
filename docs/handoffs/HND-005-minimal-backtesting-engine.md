# AI Handoff

## Handoff ID
HND-005

## Task ID
TASK-005 — Implement OBJ-006 Minimal Backtesting Engine

## Objective
OBJ-006 — Minimal Backtesting Engine

## Agent
Claude Code (claude-sonnet-4-6)

## Date
2026-05-17

## Status
Complete

---

## What was changed

Implemented the Minimal Deterministic Backtesting Engine for AQCS Phase 1. The engine enforces next-bar execution structurally (not by convention), making lookahead bias architecturally impossible.

**Design:** Signal Series is shifted by 1 before the simulation loop. `shifted[T] = signals[T-1]`. At bar T, the engine reads `shifted[T]` — the signal from bar T-1. Signal at bar T can never influence bar T's execution.

**Note:** The task specified ADR-006, but that number is already taken by the minimal research core (ADR-006-minimal-research-core.md). Used **ADR-007** instead.

## Files changed

```
src/aqcs/backtesting/__init__.py      — updated (was empty stub)
src/aqcs/backtesting/models.py        — new: BacktestConfig, Trade, EquityCurvePoint, BacktestResult
src/aqcs/backtesting/validation.py    — new: validate_backtest_inputs()
src/aqcs/backtesting/execution.py     — new: buy/sell fill, fee, quantity computation
src/aqcs/backtesting/metrics.py       — new: 8 required metrics
src/aqcs/backtesting/engine.py        — new: run_backtest() with ExperimentTracker integration
tests/unit/test_backtesting_engine.py — new: 39 tests
docs/architecture/minimal-backtesting-engine.md — new
docs/decisions/ADR-007-minimal-backtesting-engine.md — new
docs/objectives/OBJ-006-minimal-backtesting-engine.md — new
tests/architecture/test_repo_structure.py — updated (5 new files)
```

## Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: 751 passed in ~4s
```

## Verification result

- [x] pytest: 751 passing, 0 failing
- [x] architecture tests: passing (backtesting boundaries enforced)
- [x] governance tests: passing
- [x] anti-live-trading tests: passing
- [x] Next-bar execution: verified
- [x] No same-bar execution: verified
- [x] Determinism: verified
- [x] committed and pushed to origin/master

---

## Decisions made

1. **ADR-007 not ADR-006.** ADR-006 is already taken by minimal-research-core.
2. **`signals.shift(1)` enforces timing structurally.** Cannot be disabled. The engineer cannot "accidentally" remove the shift.
3. **BacktestConfig uses Pydantic with frozen=True.** User-facing input benefits from validation and clear error messages. Result models use frozen dataclasses (internal, no user validation needed).
4. **Fees and slippage on gross transaction value.** Industry standard: `fee = fill_price × quantity × fee_factor`. No netting.
5. **Win rate defined as fill_price comparison.** `sell.fill_price > buy.fill_price` → win. Fees are not deducted from the win/loss calculation (gross basis). Net-of-fees P&L is captured in the equity curve, not in win_rate.
6. **CAGR uses 365.25 calendar days.** Not 252 trading days. This is more accurate for crypto (24/7 markets) and avoids the "which days count?" ambiguity.
7. **Sharpe uses zero risk-free rate.** Standard for crypto research. Documented in the metrics docstring.

## Risks / concerns

- Win rate is based on gross fill prices, not net-of-fees P&L. A trade with positive gross P&L but fees > gross P&L would show as a win but is actually a loss. For low-fee crypto, this edge case is rare. Consider adding net P&L win rate in Phase 2.
- The engine does not validate that OHLCV data passed the data validator. Callers are responsible for this. The `validate_backtest_inputs` function only checks structure, not data quality (e.g., OHLCV consistency, gap detection). Document this clearly in usage examples.
- `run_backtest` accepts `tracker: object | None` to avoid circular import issues. Type checking is deferred to runtime. Consider typing it as `ExperimentTracker | None` with a TYPE_CHECKING guard in Phase 2.

## Deferred work

- TASK-006: Multi-asset portfolio backtesting (Phase 3)
- TASK-007: Walk-forward validation framework (Phase 3)
- TASK-008: Market impact slippage model (Phase 3)

---

## Recommended next prompt

```
Conduct a formal Phase 1 closure audit for AQCS.

AQCS Phase 1 is now complete across 6 objectives:
- OBJ-001: Foundation Layer ✓
- OBJ-002: Data Validation Layer ✓
- OBJ-003: Experiment Tracking Layer ✓
- OBJ-004: Backtesting Standards Layer ✓
- OBJ-005: Minimal Research Core ✓
- OBJ-006: Minimal Backtesting Engine ✓

The repository now has 751+ tests passing.

Conduct a full Phase 1 audit:
1. Verify all OBJ-001 acceptance criteria are still met.
2. Verify no architectural boundary violations.
3. Verify governance records are complete and consistent.
4. Verify backtesting standards (ADR-005) are fully implemented by the engine.
5. Confirm Phase Guard still blocks all Phase 1 prohibited features.
6. Issue a formal Go / No-Go for Phase 2 (Feature Engineering + Backtesting expansion).

Read AGENTS.md before starting.
```

## Human approval needed

- [ ] No — all work is within the approved Phase 1 roadmap. Phase 2 advancement requires a formal closure audit, which is a human strategic decision.
