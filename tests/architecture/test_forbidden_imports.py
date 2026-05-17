"""Enforce library-level import restrictions across src/.

Rules:
- ML/RL libraries are globally forbidden in all phases until ADR approval.
- ccxt may only appear in src/data/ (exchange communication is data-layer-only).
- Websocket/async streaming libraries are forbidden in Phase 1.

This test uses stdlib ast only — no runtime imports of the modules under test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Libraries that must never appear anywhere in src/ without an ADR
FORBIDDEN_GLOBAL: list[str] = [
    "torch",
    "sklearn",
    "tensorflow",
    "keras",
    "stable_baselines3",
    "gym",
    "gymnasium",
    "xgboost",
    "lightgbm",
    "catboost",
]

# Libraries forbidden in Phase 1 (websocket streaming is Phase 2+)
FORBIDDEN_PHASE1: list[str] = [
    "websockets",
    "websocket",
    "aiohttp",
    "asyncio",  # asyncio use is a signal of streaming architecture — flag it
]

_SRC_FILES = sorted(Path("src").rglob("*.py"))


def extract_all_top_imports(path: Path) -> list[str]:
    """Return all top-level library names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    libs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            libs.append(top)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                libs.append(top)
    return libs


def owner_package(path: Path) -> str | None:
    """Return 'src.data' for any file under src/data/, etc."""
    parts = list(path.parts)
    if "src" not in parts:
        return None
    idx = parts.index("src")
    if len(parts) <= idx + 1:
        return None
    return f"src.{parts[idx + 1]}"


@pytest.mark.parametrize("src_file", _SRC_FILES)
def test_no_ml_rl_imports(src_file: Path) -> None:
    libs = extract_all_top_imports(src_file)
    violations = [lib for lib in FORBIDDEN_GLOBAL if lib in libs]
    assert not violations, (
        f"\n{src_file}: globally forbidden library import(s):\n"
        + "\n".join(f"  - '{lib}'" for lib in violations)
        + "\nML and RL libraries require an approved ADR before use."
        + "\nSee docs/standards/phase-constraints.md §machine_learning and §reinforcement_learning."
    )


@pytest.mark.parametrize("src_file", _SRC_FILES)
def test_ccxt_only_in_data_layer(src_file: Path) -> None:
    libs = extract_all_top_imports(src_file)
    if "ccxt" not in libs:
        return
    owner = owner_package(src_file)
    assert owner == "src.data", (
        f"\n{src_file}: 'ccxt' imported outside src/data/ (owner: '{owner}').\n"
        "Only the Data Layer may communicate with exchanges.\n"
        "See docs/architecture/system-architecture-v1.md §4.1 and §5."
    )


@pytest.mark.parametrize("src_file", _SRC_FILES)
def test_no_streaming_libs_in_phase1(src_file: Path) -> None:
    libs = extract_all_top_imports(src_file)
    violations = [lib for lib in FORBIDDEN_PHASE1 if lib in libs]
    assert not violations, (
        f"\n{src_file}: Phase 1 forbidden library import(s):\n"
        + "\n".join(f"  - '{lib}'" for lib in violations)
        + "\nWebsocket streaming and async I/O are prohibited in Phase 1."
        + "\nSee docs/standards/phase-constraints.md §websocket_streaming."
    )
