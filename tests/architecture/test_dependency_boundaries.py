"""Enforce the dependency DAG defined in system-architecture-v1.md §5.

Each src/ package may only import from the packages listed in ALLOWED.
Any import that violates the DAG is a CI failure.

This test uses stdlib ast only — no runtime imports of the modules under test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Canonical DAG — source of truth: docs/architecture/system-architecture-v1.md §5
# Key: owner package.  Value: set of src.* packages it is allowed to import.
ALLOWED: dict[str, set[str]] = {
    "src.utils":         set(),
    "src.data":          {"src.utils"},
    "src.features":      {"src.data", "src.utils"},
    "src.signals":       {"src.features", "src.utils"},
    "src.portfolio":     {"src.signals", "src.utils"},
    "src.risk":          {"src.portfolio", "src.utils"},
    "src.execution":     {"src.risk", "src.utils"},
    "src.backtesting":   {
        "src.data", "src.features", "src.signals",
        "src.portfolio", "src.risk", "src.execution", "src.utils",
    },
    "src.monitoring":    {"src.data", "src.utils"},
    "src.llm_oversight": {"src.utils"},
}

_SRC_FILES = sorted((_PROJECT_ROOT / "src").rglob("*.py"))


def extract_src_imports(path: Path) -> list[str]:
    """Return all src.* top-level package names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    packages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("src."):
                pkg = ".".join(node.module.split(".")[:2])
                packages.append(pkg)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    pkg = ".".join(alias.name.split(".")[:2])
                    packages.append(pkg)
    return packages


def owner_package(path: Path) -> str | None:
    """Return 'src.signals' for any file under src/signals/, etc."""
    parts = list(path.parts)
    if "src" not in parts:
        return None
    idx = parts.index("src")
    if len(parts) <= idx + 1:
        return None
    return f"src.{parts[idx + 1]}"


@pytest.mark.parametrize("src_file", _SRC_FILES)
def test_import_boundary(src_file: Path) -> None:
    owner = owner_package(src_file)
    if owner not in ALLOWED:
        return  # src/__init__.py or other top-level file — not a tracked subpackage

    allowed = ALLOWED[owner]
    violations = [
        imp for imp in extract_src_imports(src_file)
        if imp not in allowed and imp != owner
    ]

    assert not violations, (
        f"\n{src_file}: forbidden import(s) from '{owner}':\n"
        + "\n".join(f"  - '{v}' (not in allowed set)" for v in violations)
        + f"\nAllowed imports: {sorted(allowed) if allowed else '(none — this package is a leaf)'}."
        + "\nSee docs/architecture/system-architecture-v1.md §5."
    )
