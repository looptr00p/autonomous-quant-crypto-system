"""Tests for the phase guard enforcement layer."""

from __future__ import annotations

import pytest

import src.utils.phase_guard as guard
from src.utils.phase_guard import Feature, PhaseConstraintError, assert_allowed


class TestPhase1Prohibitions:
    """Every feature prohibited in Phase 1 must raise PhaseConstraintError."""

    def test_futures_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="futures"):
            assert_allowed(Feature.FUTURES)

    def test_leverage_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="leverage"):
            assert_allowed(Feature.LEVERAGE)

    def test_live_trading_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="live_trading"):
            assert_allowed(Feature.LIVE_TRADING)

    def test_websocket_streaming_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="websocket_streaming"):
            assert_allowed(Feature.WEBSOCKET_STREAMING)

    def test_reinforcement_learning_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="reinforcement_learning"):
            assert_allowed(Feature.REINFORCEMENT_LEARNING)

    def test_machine_learning_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="machine_learning"):
            assert_allowed(Feature.MACHINE_LEARNING)

    def test_autonomous_agents_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="autonomous_agents"):
            assert_allowed(Feature.AUTONOMOUS_AGENTS)

    def test_short_selling_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="short_selling"):
            assert_allowed(Feature.SHORT_SELLING)

    def test_order_execution_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="order_execution"):
            assert_allowed(Feature.ORDER_EXECUTION)

    def test_paper_trading_prohibited(self) -> None:
        with pytest.raises(PhaseConstraintError, match="paper_trading"):
            assert_allowed(Feature.PAPER_TRADING)


class TestErrorContract:
    """PhaseConstraintError messages must be actionable."""

    def test_message_includes_feature_name(self) -> None:
        with pytest.raises(PhaseConstraintError) as exc_info:
            assert_allowed(Feature.MACHINE_LEARNING)
        assert "machine_learning" in str(exc_info.value)

    def test_message_includes_phase_number(self) -> None:
        with pytest.raises(PhaseConstraintError) as exc_info:
            assert_allowed(Feature.FUTURES)
        assert "Phase 1" in str(exc_info.value)

    def test_message_references_docs(self) -> None:
        with pytest.raises(PhaseConstraintError) as exc_info:
            assert_allowed(Feature.LEVERAGE)
        assert "phase-constraints.md" in str(exc_info.value)

    def test_is_subclass_of_runtime_error(self) -> None:
        with pytest.raises(RuntimeError):
            assert_allowed(Feature.LIVE_TRADING)


class TestProhibitedSet:
    """prohibited_in_current_phase() must return the exact Phase 1 set."""

    def test_returns_frozenset(self) -> None:
        assert isinstance(guard.prohibited_in_current_phase(), frozenset)

    def test_is_immutable(self) -> None:
        result = guard.prohibited_in_current_phase()
        with pytest.raises(AttributeError):
            result.add(Feature.FUTURES)  # type: ignore[attr-defined]

    def test_contains_all_phase1_features(self) -> None:
        expected = {
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
        }
        assert guard.prohibited_in_current_phase() == expected

    def test_current_phase_returns_1(self) -> None:
        assert guard.current_phase() == 1


class TestPhaseProgression:
    """Verify constraint relaxation as phase advances (using monkeypatch)."""

    def test_phase_2_allows_websocket_streaming(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 2)
        assert_allowed(Feature.WEBSOCKET_STREAMING)  # must not raise

    def test_phase_2_allows_machine_learning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 2)
        assert_allowed(Feature.MACHINE_LEARNING)  # must not raise

    def test_phase_2_still_prohibits_live_trading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 2)
        with pytest.raises(PhaseConstraintError):
            assert_allowed(Feature.LIVE_TRADING)

    def test_phase_2_still_prohibits_futures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 2)
        with pytest.raises(PhaseConstraintError):
            assert_allowed(Feature.FUTURES)

    def test_phase_3_allows_paper_trading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 3)
        assert_allowed(Feature.PAPER_TRADING)  # must not raise

    def test_phase_3_still_prohibits_live_trading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 3)
        with pytest.raises(PhaseConstraintError):
            assert_allowed(Feature.LIVE_TRADING)

    def test_phase_3_still_prohibits_autonomous_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 3)
        with pytest.raises(PhaseConstraintError):
            assert_allowed(Feature.AUTONOMOUS_AGENTS)

    def test_phase_4_allows_live_trading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 4)
        assert_allowed(Feature.LIVE_TRADING)  # must not raise

    def test_phase_4_still_prohibits_autonomous_agents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 4)
        with pytest.raises(PhaseConstraintError):
            assert_allowed(Feature.AUTONOMOUS_AGENTS)

    def test_unknown_phase_allows_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(guard, "CURRENT_PHASE", 99)
        assert_allowed(Feature.MACHINE_LEARNING)  # unknown phase → no prohibition
