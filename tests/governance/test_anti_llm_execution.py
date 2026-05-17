"""Anti-LLM execution enforcement — verify that LLM Oversight cannot generate
signals, mutate strategy parameters, or influence the Quant Core.

The import boundary is already tested by test_dependency_boundaries.py.
These tests add operational checks:
1. LLM Oversight has no signal/weight/config generation functions.
2. LLM Oversight makes no order submission calls.
3. LLM Oversight does not bypass the Phase Guard.
4. The only public API of OversightObserver is observe/subscribe/generate_review.
5. generate_review() is the sole output path and returns only OversightReviewEvent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LLM_DIR = _PROJECT_ROOT / "src" / "aqcs" / "llm_oversight"
_LLM_FILES = sorted(_LLM_DIR.rglob("*.py"))

# Function names that would indicate the LLM is generating executable decisions
_FORBIDDEN_FUNCTION_NAMES: frozenset[str] = frozenset(
    {
        "generate_signal",
        "compute_signal",
        "compute_weight",
        "set_position",
        "place_order",
        "create_order",
        "submit_order",
        "modify_config",
        "set_config",
        "update_config",
        "update_risk",
        "set_risk",
        "update_strategy",
        "set_strategy",
        "execute",
        "run_strategy",
        "override_phase_guard",
        "bypass_phase_guard",
    }
)

# Method calls that indicate order submission
_FORBIDDEN_METHOD_CALLS: frozenset[str] = frozenset(
    {
        "create_order",
        "place_order",
        "submit_order",
        "set_leverage",
        "set_margin_mode",
    }
)

# aqcs.* sub-packages the LLM layer must not import
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "aqcs.signals",
        "aqcs.portfolio",
        "aqcs.risk",
        "aqcs.execution",
        "aqcs.backtesting",
        "aqcs.data",
        "aqcs.features",
        "aqcs.monitoring",
    }
)


# ── 1. No forbidden function definitions ──────────────────────────────────────


@pytest.mark.parametrize("llm_file", _LLM_FILES, ids=[f.name for f in _LLM_FILES])
def test_llm_oversight_has_no_signal_generation_functions(llm_file: Path) -> None:
    tree = ast.parse(llm_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in _FORBIDDEN_FUNCTION_NAMES
        ):
            violations.append(f"  forbidden function: '{node.name}'")
    assert not violations, (
        f"{llm_file.name}: LLM Oversight must not define signal/config/execution functions.\n"
        + "\n".join(violations)
        + "\nSee docs/architecture/system-architecture-v1.md §6 — LLM Oversight boundary."
    )


# ── 2. No order submission method calls ───────────────────────────────────────


@pytest.mark.parametrize("llm_file", _LLM_FILES, ids=[f.name for f in _LLM_FILES])
def test_llm_oversight_makes_no_order_calls(llm_file: Path) -> None:
    tree = ast.parse(llm_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_METHOD_CALLS:
            violations.append(f"  call/access to '{node.attr}'")
    assert (
        not violations
    ), f"{llm_file.name}: LLM Oversight must not call order submission methods.\n" + "\n".join(
        violations
    )


# ── 3. No forbidden aqcs.* imports ────────────────────────────────────────────


@pytest.mark.parametrize("llm_file", _LLM_FILES, ids=[f.name for f in _LLM_FILES])
def test_llm_oversight_has_no_forbidden_aqcs_imports(llm_file: Path) -> None:
    tree = ast.parse(llm_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            pkg = ".".join(node.module.split(".")[:2])
            if pkg in _FORBIDDEN_IMPORTS:
                violations.append(f"  'from {node.module} import ...'")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pkg = ".".join(alias.name.split(".")[:2])
                if pkg in _FORBIDDEN_IMPORTS:
                    violations.append(f"  'import {alias.name}'")
    assert not violations, (
        f"{llm_file.name}: LLM Oversight may only import from aqcs.utils.\n"
        + "\n".join(violations)
        + "\nSee docs/architecture/system-architecture-v1.md §5 (dependency rules)."
    )


# ── 4. OversightObserver public API is constrained ───────────────────────────


def test_oversight_observer_public_methods_are_allowed() -> None:
    """OversightObserver's public methods must only be: subscribe, generate_review,
    and _handle_core_event (private). No trading or config methods allowed."""
    observer_file = _LLM_DIR / "observer.py"
    tree = ast.parse(observer_file.read_text(encoding="utf-8"))

    allowed_public_methods = {"subscribe", "generate_review"}

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "OversightObserver":
            for item in ast.walk(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = item.name
                    if name.startswith("_"):
                        continue  # private methods are fine
                    if name not in allowed_public_methods:
                        violations.append(f"  unexpected public method: '{name}'")

    assert not violations, (
        "OversightObserver has unexpected public methods.\n"
        "Only 'subscribe' and 'generate_review' are permitted as public API.\n"
        + "\n".join(violations)
    )


# ── 5. generate_review returns OversightReviewEvent only ─────────────────────


def test_generate_review_returns_oversight_event_type() -> None:
    """Verify that generate_review() is annotated to return OversightReviewEvent,
    not a signal, weight, or generic type that could carry trading instructions."""
    observer_file = _LLM_DIR / "observer.py"
    tree = ast.parse(observer_file.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "generate_review":
            if node.returns is not None:
                return_annotation = ast.unparse(node.returns)
                assert "OversightReviewEvent" in return_annotation, (
                    f"generate_review() return annotation is '{return_annotation}'. "
                    f"It must return OversightReviewEvent, not a trading signal or generic type."
                )
            return  # found and checked

    pytest.fail("generate_review() not found in observer.py")


# ── 6. Phase Guard is not bypassed in LLM layer ───────────────────────────────


def test_llm_oversight_does_not_bypass_phase_guard() -> None:
    """LLM Oversight must not call assert_allowed() to check if features are
    permitted — that is a Quant Core concern, not an oversight concern."""
    for llm_file in _LLM_FILES:
        content = llm_file.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "assert_allowed":
                    pytest.fail(
                        f"{llm_file.name}: LLM Oversight calls assert_allowed().\n"
                        "The Phase Guard is a Quant Core concern. LLM Oversight must not "
                        "interact with it — neither to check nor to bypass constraints."
                    )
                if isinstance(func, ast.Attribute) and func.attr == "assert_allowed":
                    pytest.fail(
                        f"{llm_file.name}: LLM Oversight calls assert_allowed() via attribute."
                    )
