"""Enforce that documentation and example files use the canonical aqcs.* namespace.

Legacy src.* import statements and CLI commands are prohibited in
documentation, scripts, and workflow files. All references must use
the canonical aqcs.* import namespace.

Scanned:
  - README.md
  - docs/**/*.md
  - scripts/**/* (all file types)
  - .github/**/*.yml

Detected patterns:
  - from src.
  - import src.
  - python -m src.

Exceptions (silently skipped):
  1. Files with an explicit "DEPRECATED" marker in the first 10 lines.
  2. Files explicitly listed in WHITELISTED (with justification).
"""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── Collect files to scan ──────────────────────────────────────────────────────

_SCAN_FILES: list[Path] = []

_README = _PROJECT_ROOT / "README.md"
if _README.is_file():
    _SCAN_FILES.append(_README)

for mdfile in sorted((_PROJECT_ROOT / "docs").rglob("*.md")):
    _SCAN_FILES.append(mdfile)

for script in sorted((_PROJECT_ROOT / "scripts").rglob("*")):
    if script.is_file():
        _SCAN_FILES.append(script)

for ymlfile in sorted((_PROJECT_ROOT / ".github").rglob("*.yml")):
    _SCAN_FILES.append(ymlfile)

# ── Patterns to detect ─────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (
        "from src.",
        "legacy 'from src.*' import",
        re.compile(r"from src\."),
    ),
    (
        "import src.",
        "legacy 'import src.*' import",
        re.compile(r"import src\."),
    ),
    (
        "python -m src.",
        "legacy 'python -m src.*' command",
        re.compile(r"python -m src\."),
    ),
]

# ── Explicit whitelist ─────────────────────────────────────────────────────────
# Entries must include a justification comment.
# Format: "path/relative/to/project/root" -> "Justification"
_WHITELISTED: dict[str, str] = {}


def _is_deprecated(path: Path) -> bool:
    """Return True if the file has an explicit deprecation notice in the first 10 lines."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    head = "\n".join(text.splitlines()[:10])
    return "DEPRECATED" in head or "deprecated" in head


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_no_legacy_src_in_documentation() -> None:
    violations: list[str] = []

    for path in _SCAN_FILES:
        rel = path.relative_to(_PROJECT_ROOT)
        rel_str = str(rel)

        if rel_str in _WHITELISTED:
            continue

        if _is_deprecated(path):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (UnicodeDecodeError, IsADirectoryError, PermissionError):
            continue

        for label, _description, pattern in _PATTERNS:
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    violations.append(
                        f"  {rel_str}:{lineno}:  {label}\n" f"    → {line.strip()[:120]}"
                    )

    assert not violations, (
        "Legacy src.* patterns found in documentation — use aqcs.* instead:\n\n"
        + "\n".join(violations)
        + "\n\nUse 'aqcs.*' instead of 'src.*' in all documentation, scripts, and examples."
        + "\nSee docs/ai/AQCS_CONTEXT.md for the canonical namespace convention."
    )
