"""
pycentric.core.services.filesystem
====================================
Pure-Python (no Qt) filesystem helpers: project statistics and content search.
These are designed to be called from background threads.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pycentric.core.types import TEXT_EXTENSIONS


_SKIP_DIRS: frozenset[str] = frozenset({
    "venv", ".venv", "env", "__pycache__", "node_modules",
    ".git", ".hg", ".svn", ".tox", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})


@dataclass
class ProjectStats:
    total_files: int = 0
    python_files: int = 0
    total_lines: int = 0
    by_extension: dict[str, int] = field(default_factory=dict)
    lines_by_extension: dict[str, int] = field(default_factory=dict)


def collect_stats(root: str | Path, cancelled: Callable[[], bool] | None = None) -> ProjectStats:
    """
    Walk *root* and return aggregated ProjectStats.
    Pass a callable *cancelled* that returns True to abort early.
    """
    stats = ProjectStats()
    root_path = Path(root)

    for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda _: None):
        if cancelled and cancelled():
            break
        # prune in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for name in filenames:
            if cancelled and cancelled():
                break
            fp = Path(dirpath) / name
            ext = fp.suffix.lower() or "(none)"
            stats.total_files += 1
            stats.by_extension[ext] = stats.by_extension.get(ext, 0) + 1

            if fp.suffix.lower() == ".py":
                stats.python_files += 1

            if fp.suffix.lower() in TEXT_EXTENSIONS:
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as fh:
                        n = sum(1 for _ in fh)
                    stats.total_lines += n
                    stats.lines_by_extension[ext] = stats.lines_by_extension.get(ext, 0) + n
                except OSError:
                    pass

    return stats


def search_content(
    root: str | Path,
    query: str,
    cancelled: Callable[[], bool] | None = None,
) -> list[str]:
    """
    Search all text files under *root* for *query* (case-insensitive).
    Returns a list of relative paths (str) that contain the query.
    """
    root_path = Path(root)
    needle = query.lower()
    matches: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda _: None):
        if cancelled and cancelled():
            break
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for name in filenames:
            if cancelled and cancelled():
                break
            fp = Path(dirpath) / name
            if fp.suffix.lower() not in TEXT_EXTENSIONS and fp.name.lower() not in {
                "makefile", "dockerfile", ".gitignore", ".env"
            }:
                continue
            try:
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    if needle in fh.read().lower():
                        matches.append(str(fp.relative_to(root_path)))
            except OSError:
                pass

    return matches
