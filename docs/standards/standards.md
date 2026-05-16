# AQCS Engineering Standards

**Version:** 0.1.0  
**Date:** 2026-05-16

---

## 1. Language and runtime

- Python **3.11** minimum.
- Use type hints everywhere. `mypy --strict` must pass with zero errors.
- No `Any` unless unavoidable and annotated with a comment explaining why.

## 2. Code style

| Tool | Config |
|------|--------|
| Formatter | `black` (line length 100) |
| Linter | `ruff` (target py311, strict ruleset) |
| Type checker | `mypy --strict` |

Run before every commit:

```bash
black src/ tests/
ruff check src/ tests/ --fix
mypy src/
```

## 3. Naming conventions

| Entity | Convention | Example |
|--------|-----------|---------|
| Modules | `snake_case` | `ohlcv.py` |
| Classes | `PascalCase` | `OHLCVDownloader` |
| Functions | `snake_case` | `fetch_ohlcv` |
| Constants | `UPPER_SNAKE` | `OHLCV_SCHEMA` |
| Private | leading `_` | `_build_exchange` |

## 4. Functions

- Pure functions preferred. Side effects must be explicit in the signature or name (`save_`, `fetch_`, `write_`).
- Maximum function length: 50 lines. If longer, extract.
- Single responsibility: a function does one thing.
- No positional-only boolean arguments. Use keyword arguments or enums.

## 5. Configuration

- **Never hardcode** exchange names, symbols, timeframes, limits, or thresholds in business logic.
- All tunable parameters live in `configs/base.yaml`.
- All secrets live in `.env` and are accessed via `Settings`.
- No `os.environ` calls outside of `src/utils/config.py`.

## 6. Logging

- Use `structlog` exclusively. Never `print()`.
- Every log call must include a named event as the first positional argument.
- Use keyword arguments for all context: `logger.info("event_name", key=value)`.
- Log at `DEBUG` for internal state, `INFO` for significant milestones, `WARNING` for degraded behaviour, `ERROR` for failures that require attention.

## 7. Events

- All inter-component signals are expressed as `BaseEvent` subclasses from `src/utils/events.py`.
- Events are immutable (Pydantic `frozen=True`).
- Never pass raw dicts between modules where an event type exists.

## 8. Data integrity

- Raw data is never modified. Transformations create new files in `data/processed/`.
- All Parquet writes use the declared PyArrow schema. Schema drift fails loudly.
- Timestamps are always UTC. No naive datetimes.

## 9. Testing

- All business logic must have unit tests.
- Test file names mirror source: `src/data/ohlcv.py` → `tests/unit/test_ohlcv.py`.
- No network calls in unit tests. Use `unittest.mock` or `pytest-mock`.
- Integration tests (in `tests/integration/`) may hit real APIs but require `AQCS_ENV=integration` to run.
- Minimum coverage target: **80%** on `src/`.

## 10. Safety invariants

These must never be violated, in any phase:

1. The `llm_oversight` module never modifies system state.
2. No order is submitted without an explicit human-readable dry-run log entry first.
3. `features.order_execution: false` in `configs/base.yaml` means no order pathway is active.
4. API keys are read-only keys only (no withdrawal, no trading permissions on exchange side).
5. All downloaded data passes a schema validation step before being written to disk.

## 11. Git workflow

- Branch naming: `feat/<topic>`, `fix/<topic>`, `exp/<topic>`, `docs/<topic>`.
- Commit messages: imperative mood, present tense. "Add OHLCV downloader", not "Added" or "Adding".
- Every merge to `main` requires passing tests and linting.
- Architecture Decision Records (ADRs) in `docs/decisions/` for non-trivial design choices.

## 12. Dependency management

- Use `uv` for local development. `pip` for Docker.
- Pin all dependencies in `requirements/base.txt` and `requirements/dev.txt`.
- Update dependencies deliberately, not automatically. Review changelogs.
- No dependency with a known CVE may ship to `main`.
