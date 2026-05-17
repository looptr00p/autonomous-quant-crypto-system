# AI Handoff

## Handoff ID
HND-004

## Task ID
TASK-004 — Implement OBJ-005 Minimal Research Core

## Objective
OBJ-005 — Minimal Research Core

## Agent
Claude Code (claude-sonnet-4-6)

## Date
2026-05-17

## Status
Complete

---

## What was changed

Implemented the Minimal Research Core for AQCS Phase 1: pure feature functions and deterministic signal functions, with comprehensive lookahead safety tests.

**Feature layer (`src/aqcs/features/`):** 3 modules with 7 functions — simple_return, log_return, rolling_return, rolling_volatility, simple_moving_average, exponential_moving_average, distance_from_moving_average. All pure functions with input validation and no lookahead.

**Signal layer (`src/aqcs/signals/`):** 4 modules — types.py (re-exports SignalDirection from aqcs.utils.events), momentum.py (momentum_rank_signal via expanding percentile rank), trend.py (trend_filter_signal via MA crossover), combined.py (combined_momentum_trend_signal requiring both to agree).

The `SignalDirection` enum is reused from `aqcs.utils.events` rather than duplicated — imports are architecturally allowed since `aqcs.signals → aqcs.utils`.

Note: The task specified ADR-005 but that number is already taken by the backtesting standards ADR. Used **ADR-006** instead.

## Files changed

```
src/aqcs/features/__init__.py           — updated (was empty stub)
src/aqcs/features/returns.py            — new
src/aqcs/features/volatility.py         — new
src/aqcs/features/trend.py              — new
src/aqcs/signals/__init__.py            — updated (was empty stub)
src/aqcs/signals/types.py               — new
src/aqcs/signals/momentum.py            — new
src/aqcs/signals/trend.py               — new
src/aqcs/signals/combined.py            — new
tests/unit/test_features.py             — new (42 tests)
tests/unit/test_signals.py              — new (32 tests)
docs/architecture/research-core.md      — new
docs/decisions/ADR-006-minimal-research-core.md — new
docs/objectives/OBJ-005-minimal-research-core.md — new
docs/handoffs/HND-004-minimal-research-core.md  — this file
docs/audits/AUD-004-minimal-research-core.md    — new
tests/architecture/test_repo_structure.py — updated (7 new files)
```

## Tests run

```bash
PYTHONPATH=src pytest tests/ -q --no-cov
# Result: 637 passed in ~3s
```

## Verification result

- [x] pytest: 637 passing, 0 failing
- [x] ruff: 0 errors
- [x] architecture tests: passing (features/signals boundaries enforced)
- [x] governance tests: passing
- [x] lookahead safety: all feature and signal functions verified via partial-application tests
- [x] committed and pushed to origin/master

---

## Decisions made

1. **ADR-006, not ADR-005.** ADR-005 is already taken by the backtesting standards decision.

2. **EMA uses `adjust=False`.** This is the causal/recursive form of the EMA, guaranteed to have no lookahead. The `adjust=True` form re-weights older observations differently and could be misused. `adjust=False` produces `EMA[t] = alpha * price[t] + (1-alpha) * EMA[t-1]`.

3. **Momentum signal uses expanding percentile rank.** `expanding().rank(pct=True)` computes the current rolling return's percentile within the observed history 0..T. This is causal and avoids lookahead in the ranking step.

4. **Combined signal uses AND logic.** LONG only when both momentum AND trend are LONG. This is conservative — agrees with the AQCS philosophy of conservative defaults.

5. **Cross-sectional signals deferred.** The current signal API operates on a single asset's Series. Cross-sectional ranking (comparing multiple assets at each timestamp) requires a DataFrame input and is deferred to Phase 2.

6. **No EventBus in features or signals.** Feature and signal functions must be usable in notebooks and scripts without any infrastructure. EventBus dependency would prevent this.

## Risks / concerns

- EMA warm-up uses `min_periods=span`. This means `span` bars of NaN at the start. For long spans (e.g., 200-day EMA), this is a large warm-up period. Callers must ensure sufficient data history before applying signals.
- The `distance_from_moving_average` function protects against zero SMA by setting it to NaN. This is technically correct but may mask bugs in the input data (e.g., prices that should not be zero).

## Deferred work

- TASK-005: Cross-sectional signal ranking across multiple assets (Phase 2)
- TASK-006: Additional technical features (RSI, Bollinger Bands, ATR) (Phase 2)
- TASK-007: Backtesting engine that consumes these features and signals (Phase 2)

---

## Recommended next prompt

```
Conduct a Phase 1 closure audit for AQCS.

Phase 1 is now complete across all five objectives:
- OBJ-001: Foundation Layer ✓
- OBJ-002: Data Validation Layer ✓
- OBJ-003: Experiment Tracking Layer ✓
- OBJ-004: Backtesting Standards Layer ✓
- OBJ-005: Minimal Research Core ✓

The repository now has 637+ tests passing.
Governance enforcement, architecture enforcement, and anti-live-trading
enforcement are all active.

Before beginning Phase 2 (Backtesting Engine), conduct a formal audit:
1. Verify all OBJ-001 acceptance criteria are still met.
2. Verify no architectural boundary violations.
3. Verify governance records are complete.
4. Confirm the backtesting standards (ADR-005) are still consistent
   with the research core implementation.
5. Issue a formal Go / No-Go for Phase 2.

Read AGENTS.md before starting.
```

## Human approval needed

- [ ] No — all work is within the approved Phase 1 roadmap. Phase 2 advancement requires a Phase 1 closure audit, which is a human strategic decision.
