"""Dataset fingerprinting and git metadata capture.

Fingerprinting strategy:
- File identity = path_key + size + mtime_ns  →  SHA-256
- Dataset identity = sorted(file fingerprints)  →  SHA-256
- Full content hashing is NOT performed (too slow for Phase 1)

Path portability:
- If dataset_root is provided, paths are stored relative to that root.
- This allows fingerprints to be stable across machines with different base dirs.

Git hash capture uses subprocess with a list argument (no shell injection).
Fails gracefully when git is unavailable.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def get_git_commit_hash(repo_root: Path | None = None) -> str:
    """Return the current git HEAD commit hash, or empty string if unavailable.

    Args:
        repo_root: Working directory for the git command. If None, uses
                   the current process working directory.

    Safe: uses a list argument, never shell=True.
    Graceful: catches all exceptions and returns empty string.
    """
    try:
        kwargs: dict = {
            "capture_output": True,
            "text": True,
            "timeout": 5,
        }
        if repo_root is not None:
            kwargs["cwd"] = repo_root
        result = subprocess.run(["git", "rev-parse", "HEAD"], **kwargs)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def fingerprint_file(path: Path, *, dataset_root: Path | None = None) -> str:
    """Compute a cheap, deterministic fingerprint of a single file.

    Uses: path_key + file size + mtime_ns → SHA-256.
    Does NOT read file contents — this is intentionally lightweight.

    Args:
        path: Path to the file.
        dataset_root: If provided, the path used in the fingerprint is
                      relative to dataset_root. This makes fingerprints
                      portable across machines with different base directories.

    Returns empty string if the file is not accessible.
    """
    try:
        stat = path.stat()
        if dataset_root is not None:
            try:
                path_key = str(path.relative_to(dataset_root))
            except ValueError:
                path_key = str(path.resolve())
        else:
            path_key = str(path.resolve())
        data = f"{path_key}:{stat.st_size}:{stat.st_mtime_ns}".encode()
        return hashlib.sha256(data).hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def fingerprint_dataset(paths: list[Path], *, dataset_root: Path | None = None) -> str:
    """Compute a deterministic fingerprint for a collection of data files.

    Combines individual file fingerprints in sorted order to ensure the
    result is independent of the order the paths are provided.

    Args:
        paths: List of file paths to fingerprint.
        dataset_root: If provided, use relative paths for portability.

    Returns empty string when no files are accessible.
    """
    if not paths:
        return ""
    individual = sorted(
        fp
        for p in paths
        if (fp := fingerprint_file(p, dataset_root=dataset_root))
    )
    if not individual:
        return ""
    combined = "|".join(individual).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()
