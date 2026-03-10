"""Tests for the cleaner service."""
import os
import tempfile
from pathlib import Path

from pycentric.core.services.cleaner import CLEAN_PATTERNS, scan, clean


def _make_cache_tree(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("# code")
    pycache = root / "src" / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-311.pyc").write_text("")
    (root / "src" / "stale.pyc").write_text("")


def test_scan_finds_pycache():
    with tempfile.TemporaryDirectory() as td:
        _make_cache_tree(Path(td))
        patterns = [p for p in CLEAN_PATTERNS if "__pycache__" in p.glob_pattern]
        items = scan(td, patterns)
        assert any("__pycache__" in i for i in items)


def test_clean_removes_pyc():
    with tempfile.TemporaryDirectory() as td:
        _make_cache_tree(Path(td))
        pyc_patterns = [p for p in CLEAN_PATTERNS if "*.pyc" in p.glob_pattern]
        results = clean(td, pyc_patterns)
        deleted = [r for r in results if r.deleted]
        assert len(deleted) >= 1
        # The .pyc inside __pycache__ might not be matched directly, but stale.pyc should be
        leftover_pyc = list(Path(td).rglob("stale.pyc"))
        assert len(leftover_pyc) == 0


def test_clean_preserves_py():
    with tempfile.TemporaryDirectory() as td:
        _make_cache_tree(Path(td))
        pyc_patterns = [p for p in CLEAN_PATTERNS if "*.pyc" in p.glob_pattern]
        clean(td, pyc_patterns)
        assert (Path(td) / "src" / "main.py").exists()
