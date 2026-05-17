# ADR-002: Quant Core is deterministic; LLM Oversight is passive

**Status:** Accepted  
**Date:** 2026-05-16  
**Deciders:** Human Founder  
**Related to Objective:** OBJ-001

---

## Context

AQCS needs to integrate AI capabilities (specifically large language models) while maintaining the reproducibility and auditability required for a quantitative research platform.

Two design approaches were considered:
1. LLMs generate signals, weights, or risk overrides alongside or instead of deterministic quant logic.
2. LLMs observe system activity and produce human-readable documentation, while all quant logic remains deterministic and human-designed.

The second approach was chosen. The question requiring a formal decision is: how is this boundary enforced, and what exactly is the LLM permitted and prohibited from doing?

## Decision

**The Quant Core is fully deterministic.** No LLM, neural network, or probabilistic model may generate signals, portfolio weights, risk limits, or any value that flows into the execution path. All such values are produced by explicit, rule-based, human-readable Python functions.

**The LLM Oversight layer is passive.** It receives typed event records from the Quant Core, produces human-readable narrative summaries, and may generate `OversightReviewEvent` records for auditability. It never modifies system state, never calls external APIs, and never produces data that influences the Quant Core.

The boundary is enforced architecturally:
- `aqcs.llm_oversight` may only import from `aqcs.utils` — enforced by `test_dependency_boundaries.py`
- `OversightObserver` subscribes to core events but not to `OVERSIGHT` events (no feedback loops)
- `observe()` and `generate_review()` return `None` or `OversightReviewEvent` only

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| LLM generates trading signals | Non-deterministic, non-auditable, legally and operationally risky for a capital-deployment system |
| LLM modifies risk parameters at runtime | Removes human control of risk; violates the institutional requirement that risk is explicitly set by humans |
| No LLM layer at all | Loses the documentation and observability value; makes it harder to maintain institutional memory |
| LLM as a supervisor that can reject quant decisions | Creates ambiguity about authority; slows down backtesting; adds non-determinism |

## Consequences

**Positive:**
- Backtesting is fully reproducible (no LLM stochasticity in the loop)
- Risk management remains under explicit human control
- Audit trail is deterministic and legally defensible
- LLM can be improved or replaced without affecting Quant Core behavior
- Architecture boundary can be tested automatically

**Negative:**
- LLM capabilities are limited to documentation and observation in Phase 1
- Insights from LLM review cannot automatically feed back into the system — human must interpret and act

**Neutral:**
- Phase 2+ may introduce LLM-assisted research tools (e.g., literature search, hypothesis generation) without violating this decision, as long as they do not influence the execution path

## Related documents

- `docs/architecture/system-architecture-v1.md §6` — LLM Oversight boundary enforcement
- `src/aqcs/llm_oversight/observer.py`
- `tests/architecture/test_dependency_boundaries.py`
- ADR-001: Stack selection
