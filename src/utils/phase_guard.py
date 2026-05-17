"""Phase enforcement — blocks capabilities prohibited in the current development phase.

Call `assert_allowed(Feature.X)` at the entry point of any code that touches
a gated capability. A PhaseConstraintError is raised immediately with an
explicit message if the feature is prohibited.

No external dependencies. No side effects on import. No decorators.
"""

from __future__ import annotations

from enum import Enum


CURRENT_PHASE: int = 1


class Feature(str, Enum):
    """Enumeration of all capabilities that can be gated by phase."""

    FUTURES = "futures"
    LEVERAGE = "leverage"
    LIVE_TRADING = "live_trading"
    WEBSOCKET_STREAMING = "websocket_streaming"
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    MACHINE_LEARNING = "machine_learning"
    AUTONOMOUS_AGENTS = "autonomous_agents"
    SHORT_SELLING = "short_selling"
    ORDER_EXECUTION = "order_execution"
    PAPER_TRADING = "paper_trading"


class PhaseConstraintError(RuntimeError):
    """Raised when code attempts to use a capability prohibited in the current phase."""


_PROHIBITED: dict[int, frozenset[Feature]] = {
    1: frozenset({
        Feature.FUTURES,
        Feature.LEVERAGE,
        Feature.LIVE_TRADING,
        Feature.WEBSOCKET_STREAMING,
        Feature.REINFORCEMENT_LEARNING,
        Feature.MACHINE_LEARNING,
        Feature.AUTONOMOUS_AGENTS,
        Feature.SHORT_SELLING,
        Feature.ORDER_EXECUTION,
        Feature.PAPER_TRADING,
    }),
    2: frozenset({
        Feature.FUTURES,
        Feature.LEVERAGE,
        Feature.LIVE_TRADING,
        Feature.REINFORCEMENT_LEARNING,
        Feature.AUTONOMOUS_AGENTS,
        Feature.SHORT_SELLING,
        Feature.ORDER_EXECUTION,
    }),
    3: frozenset({
        Feature.FUTURES,
        Feature.LEVERAGE,
        Feature.LIVE_TRADING,
        Feature.REINFORCEMENT_LEARNING,
        Feature.AUTONOMOUS_AGENTS,
    }),
    4: frozenset({
        Feature.REINFORCEMENT_LEARNING,
        Feature.AUTONOMOUS_AGENTS,
    }),
}


def _check_phase_known() -> None:
    if CURRENT_PHASE not in _PROHIBITED:
        raise PhaseConstraintError(
            f"Unknown phase '{CURRENT_PHASE}'. Valid phases are {sorted(_PROHIBITED.keys())}. "
            f"See docs/standards/phase-constraints.md."
        )


def assert_allowed(feature: Feature) -> None:
    """Raise PhaseConstraintError if feature is prohibited in CURRENT_PHASE.

    Also raises if CURRENT_PHASE is not a recognised phase number — unknown
    phases fail closed rather than silently allowing all features.

    Usage:
        from src.utils.phase_guard import Feature, assert_allowed
        assert_allowed(Feature.MACHINE_LEARNING)  # raises in Phase 1
    """
    _check_phase_known()
    if feature in _PROHIBITED[CURRENT_PHASE]:
        raise PhaseConstraintError(
            f"'{feature.value}' is prohibited in Phase {CURRENT_PHASE}. "
            f"See docs/standards/phase-constraints.md for the full constraint list "
            f"and the ADR required to advance this capability to a later phase."
        )


def prohibited_in_current_phase() -> frozenset[Feature]:
    """Return the complete set of features prohibited in the current phase.

    Raises PhaseConstraintError if CURRENT_PHASE is not a recognised phase number.
    """
    _check_phase_known()
    return _PROHIBITED[CURRENT_PHASE]


def current_phase() -> int:
    """Return the active phase number. Single source of truth."""
    return CURRENT_PHASE
