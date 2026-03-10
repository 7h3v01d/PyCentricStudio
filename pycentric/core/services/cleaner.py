"""
pycentric.core.services.cleaner
================================
Business logic for scanning and removing project build/cache artefacts.
No Qt imports — safe to call from any thread.
"""

from __future__ import annotations
import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class CleanPattern:
    label: str
    glob_pattern: str   # relative glob, e.g.  "**/__pycache__"
    is_dir: bool = False
    enabled_by_default: bool = True


CLEAN_PATTERNS: list[CleanPattern] = [
    CleanPattern("__pycache__/",     "**/__pycache__",    is_dir=True),
    CleanPattern("*.pyc",            "**/*.pyc"),
    CleanPattern("*.pyo",            "**/*.pyo"),
    CleanPattern("*.pyd",            "**/*.pyd"),
    CleanPattern("*.egg-info/",      "**/*.egg-info",     is_dir=True),
    CleanPattern(".cache/",          "**/.cache",         is_dir=True),
    CleanPattern(".mypy_cache/",     "**/.mypy_cache",    is_dir=True),
    CleanPattern(".pytest_cache/",   "**/.pytest_cache",  is_dir=True),
    CleanPattern(".ruff_cache/",     "**/.ruff_cache",    is_dir=True),
    CleanPattern(".tox/",            "**/.tox",           is_dir=True),
    CleanPattern("dist/",            "**/dist",           is_dir=True,  enabled_by_default=False),
    CleanPattern("build/",           "**/build",          is_dir=True,  enabled_by_default=False),
    CleanPattern(".DS_Store",        "**/.DS_Store"),
    CleanPattern("Thumbs.db",        "**/Thumbs.db"),
]


@dataclass
class CleanResult:
    path: str
    deleted: bool
    error: str = ""


def scan(root: str | Path, patterns: list[CleanPattern]) -> list[str]:
    """Return a list of absolute paths matched by the selected patterns."""
    root_str = str(Path(root))
    found: list[str] = []
    for pat in patterns:
        for item in glob.glob(os.path.join(root_str, pat.glob_pattern), recursive=True):
            found.append(item)
    return found


def clean(
    root: str | Path,
    patterns: list[CleanPattern],
    progress: Callable[[CleanResult], None] | None = None,
) -> list[CleanResult]:
    """
    Delete all items matched by *patterns* under *root*.
    Calls *progress(result)* for each item processed.
    Returns the full list of CleanResult.
    """
    items = scan(root, patterns)
    results: list[CleanResult] = []
    for item in items:
        try:
            if os.path.isdir(item):
                shutil.rmtree(item)
            else:
                os.remove(item)
            r = CleanResult(path=item, deleted=True)
        except Exception as e:
            r = CleanResult(path=item, deleted=False, error=str(e))
        results.append(r)
        if progress:
            progress(r)
    return results
