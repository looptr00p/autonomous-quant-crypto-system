"""Tests for the configuration loader."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from aqcs.utils.config import Settings, load_config


class TestLoadConfig:
    def test_returns_dict(self) -> None:
        cfg = load_config("development")
        assert isinstance(cfg, dict)

    def test_base_keys_present(self) -> None:
        cfg = load_config("development")
        assert "data" in cfg
        assert "ohlcv" in cfg
        assert "exchange" in cfg

    def test_features_safe_defaults(self) -> None:
        cfg = load_config("development")
        assert cfg["features"]["order_execution"] is False
        assert cfg["features"]["autonomous_trading"] is False
        assert cfg["features"]["live_data"] is False

    def test_missing_env_file_does_not_crash(self) -> None:
        cfg = load_config("nonexistent_env")
        assert "data" in cfg


class TestSettings:
    def test_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.aqcs_env == "development"
        assert s.enable_live_data is False

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            Settings(log_level="VERBOSE")

    def test_env_override(self) -> None:
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG", "AQCS_ENV": "production"}):
            s = Settings()
        assert s.log_level == "DEBUG"
        assert s.aqcs_env == "production"
