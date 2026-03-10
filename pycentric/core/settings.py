"""
pycentric.core.settings
=======================
Typed wrapper around QSettings.  All persistent app state lives here.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QSettings


_ORG  = "PyCentric"
_APP  = "Studio"
_MAX_RECENT = 10


class Settings:
    """Singleton-style settings accessor."""

    def __init__(self) -> None:
        self._qs = QSettings(_ORG, _APP)

    # ── recent projects ───────────────────────────────────────────────────────

    def recent_projects(self) -> list[str]:
        v = self._qs.value("recent_projects", [])
        return v if isinstance(v, list) else []

    def add_recent_project(self, path: str | Path) -> None:
        recent = self.recent_projects()
        s = str(Path(path).resolve())
        if s in recent:
            recent.remove(s)
        recent.insert(0, s)
        self._qs.setValue("recent_projects", recent[:_MAX_RECENT])

    def clear_recent(self) -> None:
        self._qs.setValue("recent_projects", [])

    # ── window geometry ───────────────────────────────────────────────────────

    def save_geometry(self, widget) -> None:
        self._qs.setValue("mainwindow/geometry", widget.saveGeometry())
        self._qs.setValue("mainwindow/state",    widget.saveState())

    def restore_geometry(self, widget) -> bool:
        geo   = self._qs.value("mainwindow/geometry")
        state = self._qs.value("mainwindow/state")
        if geo:   widget.restoreGeometry(geo)
        if state: widget.restoreState(state)
        return bool(geo)

    # ── editor preferences ────────────────────────────────────────────────────

    @property
    def font_size(self) -> int:
        return int(self._qs.value("editor/font_size", 11))

    @font_size.setter
    def font_size(self, v: int) -> None:
        self._qs.setValue("editor/font_size", v)

    @property
    def tab_size(self) -> int:
        return int(self._qs.value("editor/tab_size", 4))

    @tab_size.setter
    def tab_size(self, v: int) -> None:
        self._qs.setValue("editor/tab_size", v)

    @property
    def last_project(self) -> str:
        return str(self._qs.value("project/last", ""))

    @last_project.setter
    def last_project(self, v: str) -> None:
        self._qs.setValue("project/last", v)

    # ── generic get/set ───────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._qs.value(key, default)

    def set(self, key: str, value: Any) -> None:
        self._qs.setValue(key, value)


# Module-level singleton
settings = Settings()
