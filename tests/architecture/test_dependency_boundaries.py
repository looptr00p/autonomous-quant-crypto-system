"""Enforce the dependency DAG defined in system-architecture-v1.md §5.

Each aqcs/ package may only import from the packages listed in ALLOWED.
Any import that violates the DAG is a CI failure.

This test uses stdlib ast only — no runtime imports of the modules under test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Canonical DAG — source of truth: docs/architecture/system-architecture-v1.md §5
# Key: owner package.  Value: set of aqcs.* packages it is allowed to import.
ALLOWED: dict[str, set[str]] = {
    "aqcs.utils":         set(),
    "aqcs.data":          {"aqcs.utils"},
    "aqcs.features":      {"aqcs.data", "aqcs.utils"},
    "aqcs.signals":       {"aqcs.features", "aqcs.utils"},
    "aqcs.portfolio":     {"aqcs.signals", "aqcs.utils"},
    "aqcs.risk":          {"aqcs.portfolio", "aqcs.utils"},
    "aqcs.execution":     {"aqcs.risk", "aqcs.utils"},
    "aqcs.backtesting":   {
        "aqcs.data", "aqcs.features", "aqcs.signals",
        "aqcs.portfolio", "aqcs.risk", "aqcs.execution", "aqcs.utils",
    },
    "aqcs.monitoring":    {"aqcs.data", "aqcs.utils"},
    "aqcs.llm_oversight": {"aqcs.utils"},
}

_SRC_FILES = sorted((_PROJECT_ROOT / "src" / "aqcs").rglob("*.py"))


def extract_aqcs_imports(path: Path) -> list[str]:
    """Return all aqcs.* top-level package names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    packages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("aqcs."):
                pkg = ".".join(node.module.split(".")[:2])
                packages.append(pkg)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("aqcs."):
                    pkg = ".".join(alias.name.split(".")[:2])
                    packages.append(pkg)
    return packages


def owner_package(path: Path) -> str | None:
    """Return 'aqcs.signals' for any file under src/aqcs/signals/, etc."""
    parts = list(path.parts)
    if "aqcs" not in parts:
        return None
    idx = parts.index("aqcs")
    if len(parts) <= idx + 1:
        return None
    return f"aqcs.{parts[idx + 1]}"


@pytest.mark.parametrize("src_file", _SRC_FILES)
def test_import_boundary(src_file: Path) -> None:
    owner = owner_package(src_file)
    if owner not in ALLOWED:
        return  # src/aqcs/__init__.py or other top-level file

    allowed = ALLOWED[owner]
    violations = [
        imp for imp in extract_aqcs_imports(src_file)
        if imp not in allowed and imp != owner
    ]

    assert not violations, (
        f"\n{src_file}: forbidden import(s) from '{owner}':\n"
        + "\n".join(f"  - '{v}' (not in allowed set)" for v in violations)
        + f"\nAllowed imports: {sorted(allowed) if allowed else '(none — this package is a leaf)'}."
        + "\nSee docs/architecture/system-architecture-v1.md §5."
    )
