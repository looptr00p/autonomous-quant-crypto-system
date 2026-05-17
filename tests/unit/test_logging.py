"""Tests for structured logging configuration."""

from __future__ import annotations

from aqcs.utils.logging import configure_logging, get_logger


def test_configured_logger_emits_with_logger_name() -> None:
    configure_logging(level="INFO", fmt="json")
    logger = get_logger("aqcs.test")

    logger.info("logging_smoke_test")
