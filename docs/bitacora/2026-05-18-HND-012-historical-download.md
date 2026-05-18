# AI Handoff

### Handoff ID
`HND-012`

### Task ID
`TASK-DATA-HIST-001`

### Objective
`OBJ-001 — Foundation Layer / Research Data Infrastructure`

### Agent
Claude Sonnet 4.6 (Claude Code)

### Date
2026-05-18

### Status
complete

---

### What was changed

Implemented deterministic, resumable historical OHLCV ingestion for AQCS local
Parquet datasets.  The downloader reads any existing Parquet file for a
(symbol, timeframe) pair, advances the fetch cursor to one period past the last
saved timestamp, retrieves only the missing candles from Binance Spot public
data, merges and deduplicates on timestamp, validates the full dataset with the
existing 13-step validator, and persists atomically via tmp-then-rename.
Repeated runs are idempotent — the dataset expands safely without ever producing
duplicates or timestamp inversions.

### Files changed

```
src/aqcs/data/historical_download.py     — core module: download_historical_ohlcv(), DownloadResult
scripts/data/download_historical_data.py — thin CLI: --symbol, --timeframe, --start, --end, --output-dir
tests/data/__init__.py                   — package marker
tests/data/conftest.py                   — sys.path injection for scripts/data
tests/data/test_historical_download.py   — 47 tests across all required coverage areas
```

### Tests run

```bash
PYTHONPATH=src pytest tests/data/test_historical_download.py -q --no-cov
# Result: 47 passed in 2.63s

PYTHONPATH=src pytest tests/ -q --no-cov
# Result: 926 passed in 4.48s

ruff check src/ tests/ scripts/
# Result: All checks passed!

black --check src/ tests/ scripts/
# Result: 79 files would be left unchanged.

PYTHONPATH=src mypy src/
# Result: Success: no issues found in 35 source files
```

### Verification result

- [x] pytest: 926 passing, 0 failing
- [x] ruff: 0 errors
- [x] black: 0 violations
- [x] mypy: 0 errors (35 source files)
- [x] architecture tests: passing (included in 926)
- [ ] committed and pushed to origin/master — PR open, pending human review

---

### Decisions made

1. Decision: Branch from `feat/task-governance-agent-workflow-001` working tree state (master equivalent),
   not from `feat/task-monitoring-001`.
   Rationale: `feat/task-monitoring-001` (which includes `aqcs.monitoring.data_quality`) was not yet
   merged to master. The monitoring compatibility tests were written to check the same structural
   properties directly (UTC timestamps, monotonic order, required columns, no duplicates) without
   importing from the unmerged monitoring module.
   Alternative considered: Cherry-picking or merging `feat/task-monitoring-001` first — rejected
   because it would conflate two separate PRs and violate task scope.

2. Decision: `_normalize()` is applied on fresh downloads as well as append merges.
   Rationale: Exchange data is already sorted by `fetch_ohlcv`, but mocked test inputs might not be.
   Applying normalize unconditionally makes the output deterministic regardless of input order and
   ensures validation (which checks monotonic order) always passes.

3. Decision: `SUPPORTED_TIMEFRAMES = frozenset({"1h"})` — only 1h is in scope per task spec.
   Rationale: Task explicitly scopes to 1h. Extending to 4h, 1d etc. requires a separate task.

### Risks / concerns

- Risk: `feat/task-monitoring-001` not merged — Mitigation: monitoring compatibility verified
  via direct structural checks equivalent to what `check_ohlcv_parquet_quality` performs.
  When that branch merges, the monitoring tests can be enhanced to use the actual module.

- Risk: The main git worktree HEAD kept reverting between Bash calls (harness branch management).
  Mitigation: All git operations were run with explicit `git checkout feat/task-data-hist-001`
  at the start of each Bash call. All five files are committed to the correct branch.

- Risk: Binance Spot 1h rate limits for 2+ year downloads (>17,520 candles).
  Mitigation: Pagination is handled by `fetch_ohlcv` with configurable `max_candles` and
  `pagination_sleep_ms`. The resumable cursor means partial downloads recover cleanly.

### Deferred work

- TASK-DATA-HIST-002: Add 4h timeframe support to `SUPPORTED_TIMEFRAMES`.
- TASK-DATA-HIST-003: Backfill the existing `data/raw/` 1h files to 2-year depth using
  the new downloader (actual live run against Binance).
- TASK-MONITORING-MERGE: Merge `feat/task-monitoring-001` to master so `aqcs.monitoring.data_quality`
  is available; then update monitoring compatibility tests in this module to use it directly.

---

### Recommended next prompt

```
Review PR TASK-DATA-HIST-001 on feat/task-data-hist-001.

Files to inspect:
- src/aqcs/data/historical_download.py
- scripts/data/download_historical_data.py
- tests/data/test_historical_download.py

Verification already run: 926 pytest passed, ruff/black/mypy clean.

After approving, merge to master, then run a live backfill:
  python scripts/data/download_historical_data.py \
    --symbol BTC/USDT --timeframe 1h \
    --start 2023-01-01 --end 2025-12-31 \
    --output-dir data/raw

Repeat for ETH/USDT and SOL/USDT.
```

### Human approval needed

- [x] Yes — PR merge to master requires human review.
