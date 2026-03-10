"""Tests for filesystem service: stats and search."""
import tempfile
from pathlib import Path
from pycentric.core.services.filesystem import collect_stats, search_content


def _make_project(root: Path) -> None:
    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("# hello\nprint('hi')\n")
    (src / "utils.py").write_text("def foo():\n    pass\n")
    (root / "README.md").write_text("# Project\nSome text here.\n")
    (root / "data.json").write_text('{"key": "value"}')


def test_collect_stats_counts_files():
    with tempfile.TemporaryDirectory() as td:
        _make_project(Path(td))
        stats = collect_stats(td)
        assert stats.total_files == 4
        assert stats.python_files == 2


def test_collect_stats_counts_lines():
    with tempfile.TemporaryDirectory() as td:
        _make_project(Path(td))
        stats = collect_stats(td)
        assert stats.total_lines > 0


def test_search_content_finds_match():
    with tempfile.TemporaryDirectory() as td:
        _make_project(Path(td))
        matches = search_content(td, "print")
        assert len(matches) == 1
        assert "main.py" in matches[0]


def test_search_content_case_insensitive():
    with tempfile.TemporaryDirectory() as td:
        _make_project(Path(td))
        matches = search_content(td, "PRINT")
        assert len(matches) == 1


def test_search_content_no_match():
    with tempfile.TemporaryDirectory() as td:
        _make_project(Path(td))
        matches = search_content(td, "zzz_no_match_zzz")
        assert matches == []
