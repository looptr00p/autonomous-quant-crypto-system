# ADR-001: Stack Selection for AQCS Foundation Layer

**Date:** 2026-05-16  
**Status:** Accepted  
**Deciders:** Nicolas Herrera

---

## Context

AQCS needs a stable, well-supported stack for quantitative crypto research. The stack must be:

- Reproducible across machines and over time
- Easy to audit (no magic frameworks)
- Compatible with future extensions (ML, streaming, live execution)
- Standard in the quant finance industry

## Decision

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Python 3.11 | Universal in quant, rich ecosystem, free-threading preview in 3.12+ |
| Package mgr | uv | 10-100× faster than pip, compatible with pyproject.toml |
| Data frames | pandas 2.x | Industry standard; copy-on-write semantics improve safety |
| Columnar storage | pyarrow / Parquet | Schema enforcement, compression, interoperability with Spark/DuckDB |
| Exchange API | ccxt | Unified interface across 100+ exchanges; battle-tested |
| Validation | pydantic v2 | Rust-backed, strict mode, excellent for event schemas |
| Config | pydantic-settings + YAML | Typed env vars + human-readable config files |
| Logging | structlog | Structured JSON output; zero overhead in production |
| Formatter | black | Non-configurable, no debates |
| Linter | ruff | Replaces flake8 + isort; written in Rust |
| Type checker | mypy --strict | Forces explicit type contracts |
| Testing | pytest | De facto standard; rich plugin ecosystem |

## Consequences

- **Positive:** Fast iteration, reproducibility guaranteed by schema + pin strategy, easy onboarding.
- **Negative:** uv is relatively new; fallback to pip required in some CI environments.
- **Neutral:** No async stack in Phase 1; streaming will require anyio or asyncio additions in Phase 3.

## Alternatives considered

| Alternative | Rejected because |
|------------|-----------------|
| poetry | Slower than uv, no clear advantage |
| polars | Less mature ecosystem, harder to find quant-specific help |
| SQLite | Less efficient than Parquet for column-oriented analytics |
| requests-based exchange client | ccxt handles rate limits, pagination, normalization |

## Related documents

- `pyproject.toml` — dependency declarations
- `requirements/base.txt` — pinned runtime dependencies
- `requirements/dev.txt` — pinned dev dependencies
- `docs/standards/project-standards.md` — tooling configuration standards
