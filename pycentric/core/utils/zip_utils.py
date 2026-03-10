"""
pycentric.core.utils.zip_utils
===============================
Helpers for creating and extracting zip archives.
"""

from __future__ import annotations
import zipfile
from pathlib import Path


def zip_path(source: str | Path, dest_zip: str | Path) -> None:
    """Zip a file or directory to *dest_zip*."""
    src  = Path(source)
    dest = Path(dest_zip)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if src.is_file():
            zf.write(src, src.name)
        else:
            for fp in src.rglob("*"):
                zf.write(fp, fp.relative_to(src.parent))


def unzip_to(zip_file: str | Path, dest_dir: str | Path) -> None:
    """Extract *zip_file* into *dest_dir*."""
    with zipfile.ZipFile(zip_file, "r") as zf:
        zf.extractall(dest_dir)


def unique_path(path: str | Path) -> Path:
    """Return *path* unchanged if it doesn't exist, otherwise append _1, _2, …"""
    p = Path(path)
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    i = 1
    while True:
        candidate = p.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1
