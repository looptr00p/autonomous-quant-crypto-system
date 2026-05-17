"""Verify that no Python file in the repository imports from the legacy src.* namespace.

All internal imports must use aqcs.* after the package migration.
This test fails if any src.X import is found anywhere in src/, tests/, or scripts/.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_ALL_PY_FILES = sorted(
    list((_PROJECT_ROOT / "src").rglob("*.py"))
    + list((_PROJECT_ROOT / "tests").rglob("*.py"))
    + list((_PROJECT_ROOT / "scripts").rglob("*.py"))
)


def extract_src_imports(path: Path) -> list[str]:
    """Return any 'src.*' import statements found in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("src."):
                violations.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    violations.append(f"import {alias.name}")
    return violations


@pytest.mark.parametrize("py_file", _ALL_PY_FILES)
def test_no_legacy_src_imports(py_file: Path) -> None:
    violations = extract_src_imports(py_file)
    assert (
        not violations
    ), f"\n{py_file}: found legacy src.* import(s) — use aqcs.* instead:\n" + "\n".join(
        f"  - {v}" for v in violations
    )
