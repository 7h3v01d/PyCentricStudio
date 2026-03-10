"""Tests for scaffold tree parser and builder."""
import os
import pytest
from pycentric.ui.components.scaffold.scaffold_panel import parse_tree


SAMPLE_TREE = """\
my_project/
├── README.md
├── src/
│   └── my_project/
│       ├── __init__.py
│       └── core.py
└── tests/
    └── test_core.py"""


def test_parse_tree_finds_dirs():
    items = parse_tree(SAMPLE_TREE)
    dirs = [p for p, is_dir in items if is_dir]
    assert any("src" in d for d in dirs)
    assert any("tests" in d for d in dirs)


def test_parse_tree_finds_files():
    items = parse_tree(SAMPLE_TREE)
    files = [p for p, is_dir in items if not is_dir]
    assert any("README.md" in f for f in files)
    assert any("__init__.py" in f for f in files)
    assert any("test_core.py" in f for f in files)


def test_parse_tree_empty():
    assert parse_tree("") == []


def test_parse_tree_flat():
    tree = "project/\n├── a.py\n└── b.txt"
    items = parse_tree(tree)
    names = [os.path.basename(p) for p, _ in items]
    assert "a.py" in names
    assert "b.txt" in names
