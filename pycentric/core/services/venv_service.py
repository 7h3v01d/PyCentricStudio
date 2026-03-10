"""
pycentric.core.services.venv_service
======================================
Virtual environment discovery and creation helpers.
"""

from __future__ import annotations
import sys
import venv
from pathlib import Path

_VENV_NAMES = ("venv", ".venv", "env", ".env")


def find_venv(project_root: str | Path) -> Path | None:
    """Return the path of an existing venv directory, or None."""
    root = Path(project_root)
    for name in _VENV_NAMES:
        p = root / name
        if p.is_dir() and (p / ("Scripts" if sys.platform == "win32" else "bin")).is_dir():
            return p
    return None


def python_executable(venv_path: Path | None) -> str:
    """Return the python interpreter path for a given venv (or the current one)."""
    if venv_path:
        if sys.platform == "win32":
            candidate = venv_path / "Scripts" / "python.exe"
        else:
            candidate = venv_path / "bin" / "python"
        if candidate.exists():
            return str(candidate)
    return sys.executable


def pip_executable(venv_path: Path | None) -> str:
    """Return the pip path for a given venv."""
    if venv_path:
        if sys.platform == "win32":
            candidate = venv_path / "Scripts" / "pip.exe"
        else:
            candidate = venv_path / "bin" / "pip"
        if candidate.exists():
            return str(candidate)
    return str(Path(sys.executable).parent / "pip")


def create_venv(project_root: str | Path, name: str = "venv") -> Path:
    """Create a new venv inside *project_root*. Raises if it already exists."""
    root = Path(project_root)
    venv_dir = root / name
    if venv_dir.exists():
        raise FileExistsError(f"'{venv_dir}' already exists.")
    venv.create(str(venv_dir), with_pip=True)
    return venv_dir
