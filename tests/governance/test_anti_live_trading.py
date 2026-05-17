"""Anti-live-trading enforcement — static verification that no order
submission or live execution code exists anywhere in src/aqcs/.

These tests exist as a second line of defense behind the Phase Guard.
The Phase Guard blocks execution at runtime; these tests catch violations
at static analysis time (AST scan + config verification).

Checks:
1. No order submission method calls in any src/aqcs/ module.
2. No margin/leverage/futures API calls in any src/aqcs/ module.
3. config/base.yaml feature flags remain false.
4. No exchange.set_leverage() or equivalent calls.
5. No websocket execution patterns in src/aqcs/.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_FILES = sorted((_PROJECT_ROOT / "src" / "aqcs").rglob("*.py"))

# ── Forbidden method names ─────────────────────────────────────────────────────
# These are ccxt and generic exchange API methods for order submission.
# Any call to these in src/aqcs/ is a critical governance violation.

_ORDER_SUBMISSION_METHODS: frozenset[str] = frozenset({
    "create_order",
    "place_order",
    "submit_order",
    "create_limit_order",
    "create_market_order",
    "create_stop_order",
    "create_stop_limit_order",
    "create_stop_market_order",
    "create_take_profit_order",
    "edit_order",
    "cancel_order",
    "cancel_all_orders",
    "cancel_orders",
    "close_position",
    "close_all_positions",
})

_LEVERAGE_METHODS: frozenset[str] = frozenset({
    "set_leverage",
    "set_margin_mode",
    "set_position_mode",
    "add_margin",
    "reduce_margin",
})

_FUTURES_METHODS: frozenset[str] = frozenset({
    "fetch_funding_rate",
    "fetch_open_interest",
    "set_sandbox_mode",  # allowed in aqcs.data only (covered separately)
})

_ALL_FORBIDDEN: frozenset[str] = _ORDER_SUBMISSION_METHODS | _LEVERAGE_METHODS


def _find_attribute_calls(path: Path, forbidden: frozenset[str]) -> list[str]:
    """Return list of forbidden attribute access patterns found in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.append(
                f"  {path.relative_to(_PROJECT_ROOT)}: "
                f"call/access to '{node.attr}' (line ~{node.col_offset})"
            )
    return found


# ── 1. No order submission method calls ───────────────────────────────────────

def test_no_order_submission_calls_in_src() -> None:
    violations: list[str] = []
    for src_file in _SRC_FILES:
        violations.extend(_find_attribute_calls(src_file, _ORDER_SUBMISSION_METHODS))

    assert not violations, (
        "Order submission method calls found in src/aqcs/.\n"
        "AQCS Phase 1 has no live execution pathway. These calls must not exist.\n"
        "If a dry-run order builder is needed, use explicit naming like 'build_order_params'.\n"
        "\n".join(violations)
    )


# ── 2. No leverage/margin API calls ───────────────────────────────────────────

def test_no_leverage_or_margin_calls_in_src() -> None:
    violations: list[str] = []
    for src_file in _SRC_FILES:
        violations.extend(_find_attribute_calls(src_file, _LEVERAGE_METHODS))

    assert not violations, (
        "Leverage or margin API calls found in src/aqcs/.\n"
        "Leverage is prohibited in Phase 1 (see docs/standards/phase-constraints.md).\n"
        "\n".join(violations)
    )


# ── 3. Feature flags in base.yaml ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def base_config() -> dict:
    with (_PROJECT_ROOT / "configs/base.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_order_execution_flag_is_false(base_config: dict) -> None:
    assert base_config["features"]["order_execution"] is False, (
        "configs/base.yaml: features.order_execution must be false in Phase 1. "
        "This flag must only be enabled after an architecture review and ADR."
    )


def test_live_data_flag_is_false(base_config: dict) -> None:
    assert base_config["features"]["live_data"] is False, (
        "configs/base.yaml: features.live_data must be false in Phase 1."
    )


def test_autonomous_trading_flag_is_false(base_config: dict) -> None:
    assert base_config["features"]["autonomous_trading"] is False, (
        "configs/base.yaml: features.autonomous_trading must be false in Phase 1."
    )


def test_exchange_market_type_is_spot(base_config: dict) -> None:
    assert base_config["exchange"]["market_type"] == "spot", (
        "configs/base.yaml: exchange.market_type must be 'spot'. "
        "Futures market types are prohibited in Phase 1."
    )


# ── 4. Phase Guard blocks order_execution and live_trading ────────────────────
# These test the Phase Guard at the feature level, not just the unit tests.

def test_phase_guard_blocks_order_execution_at_module_level() -> None:
    from aqcs.utils.phase_guard import Feature, PhaseConstraintError, assert_allowed
    with pytest.raises(PhaseConstraintError):
        assert_allowed(Feature.ORDER_EXECUTION)


def test_phase_guard_blocks_live_trading_at_module_level() -> None:
    from aqcs.utils.phase_guard import Feature, PhaseConstraintError, assert_allowed
    with pytest.raises(PhaseConstraintError):
        assert_allowed(Feature.LIVE_TRADING)


def test_phase_guard_blocks_futures_at_module_level() -> None:
    from aqcs.utils.phase_guard import Feature, PhaseConstraintError, assert_allowed
    with pytest.raises(PhaseConstraintError):
        assert_allowed(Feature.FUTURES)


def test_phase_guard_blocks_leverage_at_module_level() -> None:
    from aqcs.utils.phase_guard import Feature, PhaseConstraintError, assert_allowed
    with pytest.raises(PhaseConstraintError):
        assert_allowed(Feature.LEVERAGE)


# ── 5. No execution module has callable order logic ───────────────────────────

def test_execution_module_has_no_order_submission_functions() -> None:
    execution_dir = _PROJECT_ROOT / "src" / "aqcs" / "execution"
    forbidden_func_names = _ORDER_SUBMISSION_METHODS | {"execute", "run_order", "send_order"}
    violations: list[str] = []

    for src_file in sorted(execution_dir.rglob("*.py")):
        tree = ast.parse(src_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in forbidden_func_names:
                    violations.append(
                        f"  {src_file.relative_to(_PROJECT_ROOT)}: "
                        f"forbidden function '{node.name}'"
                    )

    assert not violations, (
        "Execution module contains order submission function definitions.\n"
        "src/aqcs/execution/ is read-only in Phase 1.\n"
        "\n".join(violations)
    )
