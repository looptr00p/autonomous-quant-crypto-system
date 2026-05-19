"""Integration: dataset manifest reproducibility.

Validates that the manifest generation pipeline produces bit-identical
content_hash and schema_hash values across independent runs on the same
synthetic OHLCV data, and that the campaign correctly references
manifest artifact hashes.

All tests are deterministic and local — no network, no random state.

Coverage:
- same OHLCV → same content_hash across two independent calls
- same OHLCV → same schema_hash across two independent calls
- shuffled rows → same content_hash (order-invariant)
- modified close price → different content_hash
- added column → different schema_hash
- manifest saves and reloads with same hashes
- campaign built from dir references correct manifest content_hash
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from aqcs.data.manifest import generate_manifest, manifest_to_dict, save_manifest
from aqcs.research.campaign import build_campaign

from .conftest import FIXED_NOW

_SYMBOL = "BTC/USDT"
_TIMEFRAME = "1d"
_EXCHANGE = "binance"
_N = 90


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = _N) -> pd.DataFrame:
    """Return a deterministic, schema-valid OHLCV DataFrame.

    Uses np.linspace for bit-identical results on any platform/numpy version.
    All OHLCV relationships are valid: low <= open <= close <= high.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    close = np.linspace(45_000.0, 50_000.0, n)
    high = close * 1.001
    low = close * 0.999
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,  # open == close: always within [low, high]
            "high": high,
            "low": low,
            "close": close,
            "volume": np.linspace(100.0, 200.0, n),
            "symbol": _SYMBOL,
            "timeframe": _TIMEFRAME,
            "exchange": _EXCHANGE,
        }
    )


def _write_parquet(df: pd.DataFrame, path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    p = path / "data.parquet"
    df.to_parquet(p, index=False)
    return p


# ── Content hash determinism ──────────────────────────────────────────────────


class TestContentHashDeterminism:
    def test_same_ohlcv_same_content_hash(self, tmp_path: Path) -> None:
        p1 = _write_parquet(_make_ohlcv(), tmp_path / "a")
        p2 = _write_parquet(_make_ohlcv(), tmp_path / "b")
        m1 = generate_manifest(p1, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        m2 = generate_manifest(p2, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        assert m1.content_hash == m2.content_hash

    def test_same_ohlcv_same_schema_hash(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)
        p1 = _write_parquet(_make_ohlcv(), tmp_path / "a")
        p2 = _write_parquet(_make_ohlcv(), tmp_path / "b")
        m1 = generate_manifest(p1, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        m2 = generate_manifest(p2, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        assert m1.schema_hash == m2.schema_hash

    def test_shuffled_rows_same_content_hash(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df_shuffled = df.sample(frac=1, random_state=42).reset_index(drop=True)
        (tmp_path / "orig").mkdir()
        (tmp_path / "shuf").mkdir()
        p_orig = _write_parquet(df, tmp_path / "orig")
        p_shuf = _write_parquet(df_shuffled, tmp_path / "shuf")
        m_orig = generate_manifest(p_orig, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        m_shuf = generate_manifest(p_shuf, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        assert m_orig.content_hash == m_shuf.content_hash

    def test_modified_price_different_content_hash(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df_modified = df.copy()
        df_modified.loc[0, "close"] = df_modified.loc[0, "close"] + 1.0
        (tmp_path / "orig").mkdir()
        (tmp_path / "mod").mkdir()
        p_orig = _write_parquet(df, tmp_path / "orig")
        p_mod = _write_parquet(df_modified, tmp_path / "mod")
        m_orig = generate_manifest(p_orig, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        m_mod = generate_manifest(p_mod, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        assert m_orig.content_hash != m_mod.content_hash

    def test_added_column_different_schema_hash(self, tmp_path: Path) -> None:
        df = _make_ohlcv()
        df_extra = df.copy()
        df_extra["extra_col"] = 0.0
        (tmp_path / "orig").mkdir()
        (tmp_path / "extra").mkdir()
        p_orig = _write_parquet(df, tmp_path / "orig")
        p_extra = _write_parquet(df_extra, tmp_path / "extra")
        m_orig = generate_manifest(p_orig, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        m_extra = generate_manifest(p_extra, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        assert m_orig.schema_hash != m_extra.schema_hash

    def test_timestamp_excluded_from_content_hash(self, tmp_path: Path) -> None:
        """generation_timestamp_utc must not affect content_hash."""
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        p = _write_parquet(_make_ohlcv(), tmp_path / "a")
        _ = _write_parquet(_make_ohlcv(), tmp_path / "b")
        t1 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 6, 1, tzinfo=UTC)
        m1 = generate_manifest(p, _SYMBOL, _TIMEFRAME, now_utc=t1)
        m2 = generate_manifest(p, _SYMBOL, _TIMEFRAME, now_utc=t2)
        assert m1.content_hash == m2.content_hash
        assert m1.schema_hash == m2.schema_hash


# ── Save/load round-trip ──────────────────────────────────────────────────────


class TestManifestSaveLoad:
    def test_save_load_preserves_hashes(self, tmp_path: Path) -> None:
        (tmp_path / "data").mkdir()
        p = _write_parquet(_make_ohlcv(), tmp_path / "data")
        m = generate_manifest(p, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)
        out = tmp_path / "manifest.json"
        save_manifest(m, out)
        d = json.loads(out.read_text())
        assert d["content_hash"] == m.content_hash
        assert d["schema_hash"] == m.schema_hash
        assert d["row_count"] == m.row_count


# ── Campaign references manifest hashes ──────────────────────────────────────


class TestCampaignManifestReference:
    def test_campaign_references_manifest_content_hash(self, tmp_path: Path) -> None:
        """Campaign must store the manifest's content_hash in its lineage."""
        (tmp_path / "data").mkdir()
        p = _write_parquet(_make_ohlcv(), tmp_path / "data")
        m = generate_manifest(p, _SYMBOL, _TIMEFRAME, now_utc=FIXED_NOW)

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        d = manifest_to_dict(m)
        (artifacts_dir / "manifest.json").write_text(json.dumps(d), encoding="utf-8")

        campaign = build_campaign(artifacts_dir, "lineage_test", now_utc=FIXED_NOW)
        assert m.content_hash in campaign.dataset_manifest_hashes
