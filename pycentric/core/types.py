"""
pycentric.core.types
====================
Central definitions for file types, language detection, and related constants.
All extension ↔ language mappings live here — update in one place only.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Language(str, Enum):
    PYTHON     = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JSON       = "json"
    HTML       = "html"
    CSS        = "css"
    BASH       = "bash"
    SQL        = "sql"
    MARKDOWN   = "markdown"
    YAML       = "yaml"
    TOML       = "toml"
    INI        = "ini"
    TEXT       = "text"


# Maps file extension (lowercase, with dot) → Language
EXT_LANGUAGE: dict[str, Language] = {
    ".py":       Language.PYTHON,
    ".pyw":      Language.PYTHON,
    ".js":       Language.JAVASCRIPT,
    ".mjs":      Language.JAVASCRIPT,
    ".ts":       Language.TYPESCRIPT,
    ".json":     Language.JSON,
    ".html":     Language.HTML,
    ".htm":      Language.HTML,
    ".css":      Language.CSS,
    ".sh":       Language.BASH,
    ".bash":     Language.BASH,
    ".sql":      Language.SQL,
    ".md":       Language.MARKDOWN,
    ".markdown": Language.MARKDOWN,
    ".yaml":     Language.YAML,
    ".yml":      Language.YAML,
    ".toml":     Language.TOML,
    ".ini":      Language.INI,
    ".cfg":      Language.INI,
}

# All extensions we consider "text" (editable in the code editor)
TEXT_EXTENSIONS: frozenset[str] = frozenset(EXT_LANGUAGE.keys()) | frozenset({
    ".txt", ".log", ".rst", ".xml", ".csv", ".env",
    ".gitignore", ".gitattributes", ".editorconfig",
    "",   # no extension (Makefile, Dockerfile, etc.)
})

# Named files without extensions we treat as text
TEXT_FILENAMES: frozenset[str] = frozenset({
    "makefile", "dockerfile", ".gitignore", ".gitattributes",
    ".env", ".env.example", "procfile", "requirements.txt",
})

# File tree filters for QFileSystemModel
TREE_NAME_FILTERS: list[str] = [
    "*.py", "*.pyw", "*.js", "*.ts", "*.mjs",
    "*.json", "*.html", "*.htm", "*.css",
    "*.sh", "*.bash", "*.md", "*.markdown",
    "*.txt", "*.ini", "*.cfg", "*.toml", "*.yaml", "*.yml",
    "*.zip", "*.env", "*.gitignore", "*.log", "*.sql",
    "*.rst", "*.xml", "*.csv",
    "requirements.txt", "Makefile", "Dockerfile",
]

# File templates used when creating new files
FILE_TEMPLATES: dict[str, str] = {
    ".py":    '"""Module."""\n\n\nif __name__ == "__main__":\n    pass\n',
    ".json":  "{}\n",
    ".md":    "# New Document\n",
    ".sh":    "#!/bin/bash\n\n",
    ".yml":   "# YAML\n",
    ".yaml":  "# YAML\n",
    ".html":  "<!DOCTYPE html>\n<html>\n<head><title></title></head>\n<body>\n</body>\n</html>\n",
    ".toml":  "",
    ".txt":   "",
    ".rst":   "",
}


def detect_language(path: str | Path) -> Language:
    """Return the Language for a given file path."""
    p = Path(path)
    name = p.name.lower()
    if name in TEXT_FILENAMES:
        return Language.TEXT
    return EXT_LANGUAGE.get(p.suffix.lower(), Language.TEXT)


def is_text_file(path: str | Path) -> bool:
    """Return True if the file can be opened in the text editor."""
    p = Path(path)
    name = p.name.lower()
    ext = p.suffix.lower()
    return name in TEXT_FILENAMES or ext in TEXT_EXTENSIONS


@dataclass
class FileInfo:
    """Lightweight metadata snapshot for a single file."""
    path: Path
    size_bytes: int
    modified: float  # epoch timestamp
    language: Language = field(init=False)

    def __post_init__(self) -> None:
        self.language = detect_language(self.path)

    @classmethod
    def from_path(cls, path: str | Path) -> "FileInfo":
        p = Path(path)
        stat = p.stat()
        return cls(path=p, size_bytes=stat.st_size, modified=stat.st_mtime)

    @property
    def size_kb(self) -> float:
        return self.size_bytes / 1024
