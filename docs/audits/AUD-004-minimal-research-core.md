# AUD-004: Minimal Research Core — Acceptance Audit

**Audit ID:** AUD-004  
**Date:** 2026-05-17  
**Auditor:** Claude Code (acting as Strategic Auditor)  
**Scope:** OBJ-005 — Minimal Research Core  
**Objective:** OBJ-005  
**Related handoff:** HND-004

---

## Scope

- `src/aqcs/features/` — 3 modules, 7 pure feature functions
- `src/aqcs/signals/` — 4 modules, 3 deterministic signal functions + SignalDirection type
- `tests/unit/test_features.py` — 42 tests
- `tests/unit/test_signals.py` — 32 tests
- `docs/architecture/research-core.md`
- `docs/decisions/ADR-006-minimal-research-core.md`

---

## Critical blockers

None.

---

## Must fix before continuing

None identified.

---

## Should fix soon

1. **Cross-sectional signals for multi-asset research.** `momentum_rank_signal` currently computes time-series momentum for a single asset. Research on multiple assets simultaneously requires ranking across assets at each timestamp. This should be the first signal addition in Phase 2.

2. **EMA produces NaN for `min_periods=span` bars.** With a 200-day EMA, the first 200 bars are NaN. Callers who use long spans without sufficient history will silently get all-NaN output. Add a check that logs a warning when the percentage of NaN output exceeds a threshold (e.g., 50%).

3. **`distance_from_moving_average` normalises by SMA, not by price.** This is the standard formula `(price - SMA) / SMA`, but some researchers prefer `(price - SMA) / price`. Document this choice explicitly in `research-core.md`.

---

## Nice to have

- `rolling_return` and `simple_return` share similar validation code. A shared `_validate_*` utility would reduce duplication.
- A `features.pipeline()` function that applies a sequence of feature functions to a DataFrame would simplify multi-feature research.
- RSI, Bollinger Bands, ATR — common technical indicators for Phase 2.

---

## Findings summary

| Area | Status | Notes |
|------|--------|-------|
| Feature purity | ✓ Accepted | No IO, no network, no event bus |
| Feature lookahead | ✓ Accepted | Verified via partial-application tests for all 7 functions |
| Signal lookahead | ✓ Accepted | Verified for all 3 signal functions |
| SignalDirection reuse | ✓ Accepted | Imported from aqcs.utils.events — no duplication |
| Input validation | ✓ Accepted | Empty, non-numeric, invalid window all tested |
| Architecture boundary | ✓ Accepted | features → utils; signals → features + utils; no higher imports |
| No portfolio/risk/execution | ✓ Confirmed | Functions output directions only |
| No EventBus dependency | ✓ Confirmed | Neither features nor signals import event_bus |
| No ML/RL | ✓ Confirmed | All functions are rule-based |
| EMA causal form | ✓ Accepted | adjust=False ensures no lookahead |
| Momentum expanding rank | ✓ Accepted | Causal by construction (expanding() uses 0..T) |

---

## Risks / concerns

**Low risk:**
- Warm-up periods can be long (200+ bars for EMA(200)). Downstream consumers must account for this when selecting backtest start dates.
- `combined_momentum_trend_signal` requires both signals to agree. In choppy markets, this will produce mostly NEUTRAL, which is correct conservative behavior but reduces the number of signals available for backtesting.

---

## Recommendations

1. **Mark OBJ-005 as complete.**
2. **File HND-004 as the authoritative handoff** for this implementation.
3. **Conduct a formal Phase 1 closure audit** before beginning Phase 2. All five objectives (OBJ-001 through OBJ-005) are now complete.
4. **In Phase 2,** the first signal addition should be cross-sectional momentum ranking across a universe of assets.
5. **Verify that backtesting-standards.md §D** (lookahead prevention) is fully satisfied by these implementations before using them in the backtesting engine.

---

## Go / No-Go verdict

**GO** — OBJ-005 Minimal Research Core is accepted as complete.

74 tests pass (42 feature + 32 signal). All functions are pure, deterministic, and causally correct. Architecture boundaries are enforced. No portfolio, risk, execution, or ML logic was introduced.

---

## Final technical verdict

The Minimal Research Core is accepted.

**AQCS Phase 1 is now complete across all five objectives:**

| Objective | Status | Tests |
|-----------|--------|-------|
| OBJ-001: Foundation Layer | ✓ Complete | included |
| OBJ-002: Data Validation Layer | ✓ Complete | 53 tests |
| OBJ-003: Experiment Tracking Layer | ✓ Complete | 59 tests |
| OBJ-004: Backtesting Standards Layer | ✓ Complete | documentation |
| OBJ-005: Minimal Research Core | ✓ Complete | 74 tests |

**637+ tests passing. No architectural boundary violations. No live trading. No ML/RL. Phase 1 closure audit recommended before Phase 2.**

---

## Related documents

- OBJ-005: `docs/objectives/OBJ-005-minimal-research-core.md`
- HND-004: `docs/handoffs/HND-004-minimal-research-core.md`
- ADR-006: `docs/decisions/ADR-006-minimal-research-core.md`
- `docs/architecture/research-core.md`
- `docs/architecture/backtesting-standards.md`
