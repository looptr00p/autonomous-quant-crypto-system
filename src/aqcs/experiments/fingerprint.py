"""Dataset fingerprinting and git metadata capture.

Fingerprinting strategy:
- File identity = path + size + mtime_ns  →  SHA-256
- Dataset identity = sorted(file fingerprints)  →  SHA-256
- Full content hashing is NOT performed (too slow for Phase 1)

Git hash capture uses subprocess with a list argument (no shell injection).
Fails gracefully when git is unavailable.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def get_git_commit_hash() -> str:
    """Return the current git HEAD commit hash, or empty string if unavailable.

    Safe: uses a list argument, never shell=True.
    Graceful: catches all exceptions and returns empty string.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def fingerprint_file(path: Path) -> str:
    """Compute a cheap, deterministic fingerprint of a single file.

    Uses: resolved path + file size + mtime_ns → SHA-256.
    Does NOT read file contents — this is intentionally lightweight.
    Returns empty string if the file is not accessible.
    """
    try:
        stat = path.stat()
        data = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
        return hashlib.sha256(data).hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def fingerprint_dataset(paths: list[Path]) -> str:
    """Compute a deterministic fingerprint for a collection of data files.

    Combines individual file fingerprints in sorted order to ensure the
    result is independent of the order the paths are provided.
    Returns empty string when no files are accessible.
    """
    if not paths:
        return ""
    individual = sorted(fp for p in paths if (fp := fingerprint_file(p)))
    if not individual:
        return ""
    combined = "|".join(individual).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()
