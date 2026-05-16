"""Centralised configuration loader."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_config(env: str | None = None) -> dict[str, Any]:
    """Merge base.yaml with an optional environment-specific override."""
    env = env or os.getenv("AQCS_ENV", "development")
    base = _load_yaml(_PROJECT_ROOT / "configs" / "base.yaml")
    override = _load_yaml(_PROJECT_ROOT / "configs" / f"{env}.yaml")

    def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        result = dict(a)
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    return deep_merge(base, override)


class Settings(BaseSettings):
    """Typed settings sourced from environment variables."""

    binance_api_key: str = ""
    binance_api_secret: str = ""
    data_root: str = "./data"
    logs_root: str = "./logs"
    aqcs_env: str = "development"
    log_level: str = "INFO"
    enable_live_data: bool = False

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
