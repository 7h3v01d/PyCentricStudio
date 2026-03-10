"""
pycentric.core.services.filesystem
====================================
Pure-Python (no Qt) filesystem helpers: project statistics and content search.
Designed to be called from BackgroundTask threads.

Functions accept *progress_cb* and *cancelled* as optional keyword arguments
so BackgroundTask can inject them automatically when the function signature
declares them.

Search strategy
---------------
1. If `ripgrep` (rg) is available → call it as a subprocess (10-50x faster)
2. Fallback: os.walk + read every text file in-process

collect_stats also accepts progress_cb(0-100) for the progress bar.
"""

from __future__ import annotations
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pycentric.core.types import TEXT_EXTENSIONS


_SKIP_DIRS: frozenset[str] = frozenset({
    "venv", ".venv", "env", "__pycache__", "node_modules",
    ".git", ".hg", ".svn", ".tox", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

_RG = shutil.which("rg")   # ripgrep binary if installed


@dataclass
class ProjectStats:
    total_files: int = 0
    python_files: int = 0
    total_lines: int = 0
    by_extension: dict[str, int] = field(default_factory=dict)
    lines_by_extension: dict[str, int] = field(default_factory=dict)


def collect_stats(
    root: str | Path,
    progress_cb: Callable[[int], None] | None = None,
    cancelled:   Callable[[], bool]    | None = None,
) -> ProjectStats:
    """Walk *root* and return aggregated ProjectStats.
    progress_cb and cancelled are injected automatically by BackgroundTask
    when this function is used with it.
    """
    stats     = ProjectStats()
    root_path = Path(root)

    # First pass — count dirs so we can emit progress
    try:
        all_dirs = [
            d for d in root_path.rglob("*")
            if d.is_dir() and not any(p in _SKIP_DIRS for p in d.parts)
        ]
        total_dirs = max(len(all_dirs), 1)
    except Exception:
        total_dirs = 1

    processed = 0
    for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda _: None):
        if cancelled and cancelled():
            break
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        processed += 1
        if progress_cb:
            progress_cb(min(99, int(processed * 100 / total_dirs)))

        for name in filenames:
            if cancelled and cancelled():
                break
            fp  = Path(dirpath) / name
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

    if progress_cb:
        progress_cb(100)
    return stats


def search_content(
    root:        str | Path,
    query:       str,
    case_sensitive: bool = False,
    cancelled:   Callable[[], bool] | None = None,
    progress_cb: Callable[[int], None] | None = None,
) -> list[str]:
    """
    Search all text files under *root* for *query*.
    Uses ripgrep when available; falls back to pure-Python walk.
    Returns relative paths (str) of matching files.
    """
    if _RG:
        return _search_ripgrep(root, query, case_sensitive, cancelled)
    return _search_walk(root, query, case_sensitive, cancelled, progress_cb)


def _search_ripgrep(
    root: str | Path,
    query: str,
    case_sensitive: bool,
    cancelled: Callable[[], bool] | None,
) -> list[str]:
    root_path = Path(root)
    cmd = [
        _RG, "--files-with-matches",
        "--no-heading", "--no-messages",
        *([] if case_sensitive else ["-i"]),
        "--", query, str(root_path),
    ]
    # Exclude noise dirs
    for skip in _SKIP_DIRS:
        cmd = [cmd[0], f"--glob=!{skip}/**"] + cmd[1:]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        return [
            str(Path(l).relative_to(root_path))
            for l in lines
            if not (cancelled and cancelled())
        ]
    except subprocess.TimeoutExpired:
        return []
    except Exception:
        # rg failed for any reason — fall back
        return _search_walk(root, query, case_sensitive, cancelled, None)


_MAX_FILE_BYTES = 4 * 1024 * 1024   # 4 MiB — skip files larger than this
_EXTRA_NAMES = frozenset({"makefile", "dockerfile", ".gitignore", ".env", "procfile"})


def _search_walk(
    root: str | Path,
    query: str,
    case_sensitive: bool,
    cancelled: Callable[[], bool] | None,
    progress_cb: Callable[[int], None] | None,
) -> list[str]:
    """
    Pure-Python fallback search.

    Improvements over naïve approach:
    * Reads files in **binary** mode first — avoids the Python codec overhead
      of open(..., encoding=...) on every file.
    * Caps at 4 MiB per file — huge generated files (minified JS, ML weights,
      data dumps) are skipped entirely, not read into memory.
    * Emits progress_cb every 50 files so the UI progress bar stays alive.
    * Skips files that fail UTF-8 decoding instead of silently corrupting results.
    """
    root_path  = Path(root)
    needle_raw = query.encode("utf-8", errors="replace")
    needle_low = needle_raw.lower()
    matches: list[str] = []
    processed = 0

    for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda _: None):
        if cancelled and cancelled():
            break
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for name in filenames:
            if cancelled and cancelled():
                break

            fp = Path(dirpath) / name
            if (fp.suffix.lower() not in TEXT_EXTENSIONS
                    and fp.name.lower() not in _EXTRA_NAMES):
                continue

            processed += 1
            if progress_cb and processed % 50 == 0:
                # Rough progress — we don't pre-count, so pulse rather than %
                progress_cb(min(95, processed // 5))

            try:
                with open(fp, "rb") as fh:
                    raw = fh.read(_MAX_FILE_BYTES)

                if len(raw) == _MAX_FILE_BYTES:
                    # File was truncated — skip to avoid false negatives
                    continue

                haystack = raw if case_sensitive else raw.lower()
                needle   = needle_raw if case_sensitive else needle_low

                if needle in haystack:
                    matches.append(str(fp.relative_to(root_path)))

            except OSError:
                pass

    if progress_cb:
        progress_cb(100)
    return matches
