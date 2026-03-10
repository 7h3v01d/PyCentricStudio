"""Tests for pycentric.core.types"""
import pytest
from pathlib import Path
from pycentric.core.types import detect_language, is_text_file, Language


@pytest.mark.parametrize("filename,expected", [
    ("script.py",       Language.PYTHON),
    ("app.js",          Language.JAVASCRIPT),
    ("types.ts",        Language.TYPESCRIPT),
    ("data.json",       Language.JSON),
    ("index.html",      Language.HTML),
    ("style.css",       Language.CSS),
    ("deploy.sh",       Language.BASH),
    ("query.sql",       Language.SQL),
    ("README.md",       Language.MARKDOWN),
    ("config.yml",      Language.YAML),
    ("settings.toml",   Language.TOML),
    ("settings.ini",    Language.INI),
    ("notes.txt",       Language.TEXT),
    ("Makefile",        Language.TEXT),
])
def test_detect_language(filename, expected):
    assert detect_language(filename) == expected


def test_is_text_file_python():
    assert is_text_file("main.py") is True

def test_is_text_file_binary():
    assert is_text_file("image.png") is False

def test_is_text_file_makefile():
    assert is_text_file("Makefile") is True
