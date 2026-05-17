# ADR-005: Define backtesting standards before implementing any simulation engine

**Status:** Accepted  
**Date:** 2026-05-17  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-004

---

## Context

AQCS is building a quantitative research infrastructure. The natural next step after data acquisition, validation, and experiment tracking is a backtesting engine. However, most backtesting libraries and research platforms allow researchers to run simulations without first committing to a set of assumptions about realism, lookahead, fees, and slippage.

This creates a known failure mode: the research cycle produces results that look good in simulation but fail in practice because the simulation was too optimistic. By the time this is discovered, significant effort has been invested in strategies built on invalid foundations.

The question requiring a formal decision is: should AQCS define backtesting standards before or after implementing a backtesting engine?

## Decision

**AQCS defines backtesting standards in a canonical policy document before writing any simulation engine code.**

The document `docs/architecture/backtesting-standards.md` becomes the mandatory specification that all future backtesting implementations must satisfy. No simulation engine may be merged to `main` unless every section of that document marked "Must" is satisfied.

This means:
- The standards are written when the team has maximum freedom to define them correctly
- The standards are not constrained by what an existing engine already does
- Future code reviewers have a concrete checklist to verify compliance
- The governance enforcement layer can verify that the standards document exists (§5 of the standards task)

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Build the engine first, define standards later | Standards written after-the-fact tend to describe what the engine does, not what it should do. Assumptions become entrenched. |
| Use an existing library (backtrader, vectorbt, zipline) | Existing libraries make their own assumption choices. AQCS requires institutional-grade assumptions documented and enforced by the project's own governance system. |
| No formal standards — rely on code review | Code review cannot catch conceptual mistakes like lookahead bias reliably. A standards document provides a formal checklist that any reviewer can apply. |
| Define standards as part of engine implementation | Parallel development means standards are written under time pressure and influenced by implementation constraints. |

## Consequences

**Positive:**
- All future backtests are evaluated against a consistent, pre-declared standard
- Lookahead bias prevention rules exist before any code is written that could violate them
- Fee and slippage standards are set conservatively before any temptation to optimise metrics
- The governance enforcement layer can automatically verify that the standards document exists
- Research results produced by a compliant engine have a credible institutional foundation

**Negative:**
- Delaying engine implementation means the backtesting capability is not yet available
- The standards may need to be revised as implementation reveals unforeseen constraints — any revision requires an ADR update

**Neutral:**
- The standards define the *intent* for Phase 2+ backtesting; they do not commit to a specific implementation approach within the standards

## Related documents

- `docs/architecture/backtesting-standards.md` — the canonical policy document
- `docs/objectives/OBJ-004-backtesting-standards.md`
- ADR-002: Quant Core determinism (backtesting is part of the Quant Core)
- ADR-003: Event-logged architecture (backtests emit ExperimentStartedEvent etc.)
- `src/aqcs/utils/phase_guard.py` — enforces Phase 1 prohibitions cited in §K
