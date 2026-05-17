# OBJ-001: Foundation Layer

**Objective ID:** OBJ-001  
**Status:** Complete  
**Phase:** 1  
**Date completed:** 2026-05-17

---

## Purpose

Establish the institutional infrastructure for AQCS: package structure, configuration, logging, event schema, architecture enforcement, phase enforcement, data acquisition, data validation, and governance.

This objective creates the foundation on which all future quantitative research layers will be built.

---

## Scope

Everything required to:
- Install and run AQCS from a clean machine
- Download and validate OHLCV data from Binance Spot
- Enforce architectural boundaries automatically in CI
- Prevent prohibited capabilities from being activated
- Provide a shared context and protocol for human + AI collaboration

Not in scope: trading logic, backtesting, signals, ML, live data, dashboards.

---

## Completed deliverables

| Deliverable | Files | Tests |
|-------------|-------|-------|
| Package structure (`src/aqcs/`) | `src/aqcs/**` | `test_repo_structure.py` |
| Configuration system | `src/aqcs/utils/config.py` | `test_config.py` |
| Structured logging | `src/aqcs/utils/logging.py` | — |
| Phase Guard | `src/aqcs/utils/phase_guard.py` | `test_phase_guard.py` |
| Event Schema | `src/aqcs/utils/events.py`, `event_bus.py` | `test_events.py`, `test_event_bus.py` |
| LLM Oversight Observer | `src/aqcs/llm_oversight/observer.py` | `test_oversight_observer.py` |
| OHLCV downloader | `src/aqcs/data/ohlcv.py` | `test_ohlcv.py` |
| Data Validation Layer | `src/aqcs/data/validator.py` | `test_validator.py` |
| Architecture enforcement tests | `tests/architecture/` | 4 test modules |
| CI workflow | `.github/workflows/ci.yml` | — |
| Governance MVS | `AGENTS.md`, `docs/ai/`, `docs/objectives/` | `test_repo_structure.py` |
| ADR system | `docs/decisions/` | — |
| Canonical documentation | `docs/architecture/`, `docs/standards/` | — |

---

## Acceptance criteria

- [x] `pytest tests/` passes with ≥ 297 tests
- [x] `ruff check src/ tests/` passes
- [x] `mypy src/` passes
- [x] `pip install -e ".[dev]"` installs successfully
- [x] `python -m aqcs.data.ohlcv --help` works
- [x] Architecture enforcement tests catch DAG violations
- [x] Phase Guard blocks all Phase 1 prohibited features
- [x] Data validator rejects invalid OHLCV before Parquet write
- [x] No secrets in committed files
- [x] No live order submission pathway
- [x] AGENTS.md exists and is the entry point for all agents

---

## Related ADRs

- ADR-001: Stack selection
- ADR-002: Quant Core determinism and LLM Oversight boundary
- ADR-003: Event-logged architecture
- ADR-004: Governance minimal viable system
