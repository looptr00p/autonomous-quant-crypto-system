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
    "aqcs.utils": set(),
    "aqcs.data": {"aqcs.utils"},
    "aqcs.features": {"aqcs.data", "aqcs.utils"},
    "aqcs.signals": {"aqcs.features", "aqcs.utils"},
    "aqcs.portfolio": {"aqcs.signals", "aqcs.utils"},
    "aqcs.risk": {"aqcs.portfolio", "aqcs.utils"},
    "aqcs.execution": {"aqcs.risk", "aqcs.utils"},
    "aqcs.experiments": {"aqcs.utils"},
    "aqcs.backtesting": {
        "aqcs.data",
        "aqcs.features",
        "aqcs.signals",
        "aqcs.portfolio",
        "aqcs.risk",
        "aqcs.execution",
        "aqcs.experiments",
        "aqcs.utils",
    },
    "aqcs.monitoring": {"aqcs.data", "aqcs.utils"},
    "aqcs.llm_oversight": {"aqcs.utils"},
    # aqcs.research is the offline research layer.  It may read from any
    # deterministic quant-core package but must NEVER import from execution,
    # risk, portfolio, or LLM oversight.
    # Governance decision: TASK-RESEARCH-DAG-GOVERNANCE-001 (2026-05-18)
    "aqcs.research": {
        "aqcs.backtesting",
        "aqcs.data",
        "aqcs.experiments",
        "aqcs.features",
        "aqcs.monitoring",
        "aqcs.signals",
        "aqcs.utils",
    },
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
        imp for imp in extract_aqcs_imports(src_file) if imp not in allowed and imp != owner
    ]

    assert not violations, (
        f"\n{src_file}: forbidden import(s) from '{owner}':\n"
        + "\n".join(f"  - '{v}' (not in allowed set)" for v in violations)
        + f"\nAllowed imports: {sorted(allowed) if allowed else '(none — this package is a leaf)'}."
        + "\nSee docs/architecture/system-architecture-v1.md §5."
    )


# ── aqcs.research governance tests ────────────────────────────────────────────
# TASK-RESEARCH-DAG-GOVERNANCE-001 (2026-05-18)
# These tests explicitly verify the research DAG entry and guard against
# regressions that would allow forbidden imports into the research layer.


def test_research_is_in_allowed_dag() -> None:
    """aqcs.research must be explicitly listed in the enforced DAG."""
    assert "aqcs.research" in ALLOWED, (
        "aqcs.research is not in the ALLOWED DAG. "
        "All source packages must be explicitly governed."
    )


def test_research_allowed_set_excludes_execution_layer() -> None:
    """Execution, risk, portfolio, and LLM oversight must be absent from research's allowed set.

    Research is an offline, read-only analysis layer.  It must never import
    from live-trading, order management, or LLM decision systems.
    """
    research_allowed = ALLOWED["aqcs.research"]
    forbidden_for_research = {
        "aqcs.execution",
        "aqcs.risk",
        "aqcs.portfolio",
        "aqcs.llm_oversight",
    }
    present = forbidden_for_research & research_allowed
    assert not present, (
        f"Forbidden packages found in aqcs.research allowed set: {sorted(present)}. "
        "Research must not depend on execution, risk, portfolio, or LLM oversight."
    )


def test_research_current_files_pass_dag() -> None:
    """All current aqcs/research/*.py files must satisfy the enforced DAG.

    This test replaces the implicit 'skip' that applied before aqcs.research
    was added to ALLOWED.  It explicitly checks every research file so that
    adding a new file with a forbidden import fails CI immediately.
    """
    research_dir = _PROJECT_ROOT / "src" / "aqcs" / "research"
    research_files = sorted(research_dir.rglob("*.py"))
    assert research_files, "No research source files found — check the path"

    allowed = ALLOWED["aqcs.research"]
    all_violations: dict[str, list[str]] = {}
    for f in research_files:
        imports = extract_aqcs_imports(f)
        violations = [i for i in imports if i not in allowed and i != "aqcs.research"]
        if violations:
            all_violations[str(f)] = violations

    assert not all_violations, "aqcs.research files contain forbidden imports:\n" + "\n".join(
        f"  {p}: {v}" for p, v in all_violations.items()
    )


def test_research_forbidden_execution_import_is_detected(tmp_path: Path) -> None:
    """Regression: importing from aqcs.execution inside research must be a violation.

    Verifies that if a research file ever acquires an execution import, the
    boundary check will catch it rather than silently passing.
    """
    fake = tmp_path / "fake_research.py"
    fake.write_text(
        "from aqcs.execution.engine import OrderEngine\n",
        encoding="utf-8",
    )
    imports = extract_aqcs_imports(fake)
    assert "aqcs.execution" in imports, "Test setup error: import not detected"

    research_allowed = ALLOWED["aqcs.research"]
    violations = [i for i in imports if i not in research_allowed and i != "aqcs.research"]
    assert "aqcs.execution" in violations, (
        "aqcs.execution was not flagged as a violation for aqcs.research. "
        "The DAG enforcement would silently allow a forbidden import."
    )


def test_research_forbidden_llm_oversight_import_is_detected(tmp_path: Path) -> None:
    """Regression: importing from aqcs.llm_oversight inside research must be a violation."""
    fake = tmp_path / "fake_research.py"
    fake.write_text(
        "from aqcs.llm_oversight.observer import OversightObserver\n",
        encoding="utf-8",
    )
    imports = extract_aqcs_imports(fake)
    assert "aqcs.llm_oversight" in imports

    research_allowed = ALLOWED["aqcs.research"]
    violations = [i for i in imports if i not in research_allowed and i != "aqcs.research"]
    assert "aqcs.llm_oversight" in violations
