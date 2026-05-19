## AI Handoff

### Handoff ID
`HND-016`

### Task ID
`TASK-DATA-API-SMOKE-001`

### Objective
`OBJ-001 — Foundation Layer / PRIORITY-004 Read-Only Data API Smoke Test`

### Agent
Claude Code (Sonnet 4.6)

### Date
2026-05-18

### Status
complete — PR open, pending human review

---

### What was changed

Added a read-only Binance Spot OHLCV public API smoke test CLI.
No private credentials are used. No orders are placed. No execution,
portfolio, or risk systems are touched.

### Branch
`feat/task-data-api-smoke-001`

### Commit
`20d567a` — TASK-DATA-API-SMOKE-001: add read-only Binance Spot OHLCV smoke test

---

### Files Changed

```text
scripts/data/smoke_test_public_ohlcv.py    — CLI smoke test script
tests/data/test_smoke_test_public_ohlcv.py — 38 tests
docs/bitacora/2026-05-18-HND-016-data-api-smoke-001.md — this handoff
```

### No forbidden files modified

Verified: phase_guard, execution, risk, portfolio, signals, llm_oversight,
governance tests, architecture tests, CI config, dependency files — untouched.

---

## CLI Behavior

```
PYTHONPATH=src python scripts/data/smoke_test_public_ohlcv.py \
  --exchange binance --symbol BTCUSDT --timeframe 1h \
  --limit 48 --output-dir data/smoke/
```

**Options:**

| Option | Values | Default |
|---|---|---|
| `--symbol` | BTCUSDT, ETHUSDT, SOLUSDT | required |
| `--timeframe` | 1h | required |
| `--limit` | 1–200 | 48 |
| `--output-dir` | any path | required |
| `--exchange` | binance | binance |

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | All steps passed |
| 1 | Data validation or manifest verification failed |
| 2 | Invalid CLI arguments or configuration |

**Stdout:** Deterministic JSON summary (all log output goes to stderr).

**Sample output (structure):**
```json
{
  "smoke_test": "public_ohlcv",
  "status": "passed",
  "exchange": "binance",
  "symbol": "BTC/USDT",
  "timeframe": "1h",
  "limit_requested": 48,
  "rows_fetched": 48,
  "parquet_path": "data/smoke/BTC_USDT_1h.parquet",
  "validation": {"is_valid": true, "errors": [], "warnings": []},
  "data_quality": {
    "passed": true,
    "duplicate_count": 0,
    "missing_interval_count": 0,
    "nan_count_by_column": {},
    "errors": [],
    "warnings": []
  },
  "manifest": {
    "content_hash": "...",
    "schema_hash": "...",
    "row_count": 48,
    "start_timestamp_utc": "...",
    "end_timestamp_utc": "...",
    "missing_interval_summary": {"count": 0}
  },
  "manifest_verified": true
}
```

---

## Public API Scope

- Exchange: Binance Spot (public endpoints only — no API key required)
- Endpoint used: `GET /api/v3/klines` (via ccxt `fetch_ohlcv`)
- Supported symbols: BTCUSDT, ETHUSDT, SOLUSDT
- Supported timeframe: 1h
- Max candles per run: 200 (default: 48)
- No pagination — single request via ccxt `limit` parameter
- No private endpoints, no account access, no order placement

---

## Pipeline Steps

1. **Fetch** — `exchange.fetch_ohlcv(symbol, timeframe, limit=N)` via ccxt public API
2. **Dedup** — `drop_duplicates(subset="timestamp_ms")` on raw candles
3. **Build DataFrame** — UTC-aware timestamps, OHLCV columns, symbol/timeframe/exchange metadata
4. **Validate** — `validate_ohlcv(df, symbol, timeframe)` — 13 structural checks
5. **Save Parquet** — `save_parquet(df, output_dir, symbol, timeframe)` via OHLCV_SCHEMA
6. **Data quality** — `check_ohlcv_parquet_quality(parquet_path, timeframe)` — monitoring check
7. **Manifest** — `generate_manifest(parquet_path, symbol, timeframe)` — SHA-256 hashes
8. **Verify** — `verify_manifest(parquet_path, manifest)` — re-checks content + schema hashes

---

## Test Strategy

All 38 tests use mocked API responses. No live network calls in tests.

**Mocking approach:**

- For `run_smoke_test` (core function): inject a `MagicMock` exchange via the `exchange` kwarg.  
  `mock_ex.fetch_ohlcv.return_value = synthetic_candles`

- For `main()` (CLI): patch `_build_public_exchange` to return the mock exchange.  
  `with patch("smoke_test_public_ohlcv._build_public_exchange", return_value=mock_ex)`

- For validation failure tests: patch `_fetch_ohlcv` directly to inject a DataFrame with duplicates or non-monotonic timestamps.  
  `with patch("smoke_test_public_ohlcv._fetch_ohlcv", return_value=df_with_dups)`

**CLI output note:** The CLI redirects structlog to stderr before running so that stdout carries only the JSON summary. Tests that parse CLI JSON output use `result.output[result.output.index("{"):]` to extract the JSON block if structlog output is mixed in (CliRunner captures both by default).

---

## Manual Smoke Command

Run after PR review and merge. Requires internet access (public Binance API):

```bash
PYTHONPATH=src python scripts/data/smoke_test_public_ohlcv.py \
  --exchange binance \
  --symbol BTCUSDT \
  --timeframe 1h \
  --limit 48 \
  --output-dir data/smoke/
```

Expected: exit 0, JSON with `"status": "passed"`, parquet saved to `data/smoke/BTC_USDT_1h.parquet`.

---

## Tests Run

```bash
PYTHONPATH=src .venv/bin/pytest tests/data/test_smoke_test_public_ohlcv.py -q --no-cov
# 38 passed in 1.73s

PYTHONPATH=src .venv/bin/pytest tests/ -q --no-cov
# 1159 passed in 5.87s

.venv/bin/python -m black --check src/ tests/ scripts/
# All done — 96 files unchanged

.venv/bin/python -m ruff check src/ tests/ scripts/
# All checks passed

.venv/bin/python -m mypy src/
# Success: no issues found in 38 source files
```

## Test Coverage Summary

| Class | Tests | What is verified |
|---|---|---|
| `TestCLIArgumentValidation` | 7 | Unsupported symbol, timeframe, exchange, zero limit, above-max limit, valid max limit, missing output-dir |
| `TestSuccessfulSmokeFlow` | 11 | Status passed, rows count, parquet created, filename format, validation valid, manifest fields, manifest verified, data quality, symbol format, required keys, CLI exit 0 |
| `TestEmptyAPIResponse` | 2 | Status failed, no parquet written |
| `TestValidationFailures` | 3 | Duplicate timestamps fail, non-monotonic timestamps fail, naive timestamps fail |
| `TestManifestIntegration` | 4 | content_hash format, row count matches, manifest verified on clean data, corruption raises ValueError |
| `TestDeterminism` | 6 | JSON deterministic across runs, status string, failed status string, JSON serializable, CLI valid JSON, CLI exit 1 on failure |
| `TestConstants` | 5 | SUPPORTED_SYMBOLS type, 1h in timeframes, symbol map coverage, max > default limit, default positive |

---

## Validation Results

| Check | Result |
|---|---|
| black | PASS |
| ruff | PASS |
| mypy (38 source files) | PASS |
| pytest smoke (38 tests) | PASS |
| pytest full suite (1159 tests) | PASS |
| No forbidden files modified | PASS |
| No new dependencies introduced | PASS |
| No private credentials | PASS |
| No order placement | PASS |

---

## Risks

- Structlog and stdlib logging interaction: the CLI reconfigures both at startup to direct log output to stderr. Uses `force=True` in `logging.basicConfig` and a fresh `structlog.configure` call to override any prior state. This is appropriate for a CLI entrypoint (not a library function).
- The CLI `_fetch_ohlcv` does `drop_duplicates(subset="timestamp_ms")` on raw candles before validation. If Binance returns duplicate timestamps (which should not happen), they are silently dropped before `validate_ohlcv`. This is consistent with the existing `aqcs.data.ohlcv.fetch_ohlcv` behavior.
- Data freshness: the smoke test fetches the most recent N candles. If the exchange is in a degraded state, fewer candles may be returned. The smoke test will fail cleanly with an appropriate error message.

## Unresolved Issues

None blocking merge.

## Rollback Notes

Delete `scripts/data/smoke_test_public_ohlcv.py` and `tests/data/test_smoke_test_public_ohlcv.py`. No existing files were modified. No database or config changes.

---

## Human Approval Required

Yes. Human review required before merge.

## Reviewer

AQCS Technical Trading Auditor and Project Director.

## Checklist

- [x] Branch created from current master (`f8692c0`)
- [x] PR #8 (manifest) and PR #9 (replay cert) confirmed merged before starting
- [x] No forbidden files modified
- [x] No existing files modified
- [x] No private credentials used
- [x] No order placement
- [x] No new dependencies introduced
- [x] black / ruff / mypy pass
- [x] 38 smoke tests pass (all mocked)
- [x] 1159 total tests pass
- [x] PR opened against master
- [ ] Human approval for merge
