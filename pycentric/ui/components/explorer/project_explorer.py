"""
pycentric.ui.components.explorer.project_explorer
==================================================
The left-hand project tree panel.

Improvements (2026 edition)
----------------------------
* TaskSlot used for search + stats → at-most-one-running, proper cancel
* progress bar shown during stats collection
* search: case-sensitive toggle + "✕ Clear" button
* ripgrep used automatically when available (see filesystem.py)
* search bar debounced at 400ms (was 500)
* "Open Recent" signal emitted so mainwindow can populate File menu
"""

from __future__ import annotations
import os
import shutil
from pathlib import Path

from PyQt5.QtCore import QDir, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QFileDialog, QFileSystemModel, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar,
    QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from pycentric.core.settings import settings
from pycentric.core.types import TREE_NAME_FILTERS, is_text_file
from pycentric.core.utils.threading import TaskSlot
from pycentric.core.utils.zip_utils import unique_path, zip_path, unzip_to
from pycentric.core.services.filesystem import search_content, collect_stats
from pycentric.core.services.venv_service import find_venv
from pycentric.ui.common import theme
from pycentric.ui.components.explorer.git_panel import GitPanel


class ProjectExplorer(QWidget):
    """Emits signals for the parent to act on — no subprocess/editor coupling."""

    file_activated  = pyqtSignal(str)
    run_requested   = pyqtSignal(str)
    lint_requested  = pyqtSignal(str)
    venv_found      = pyqtSignal(str)
    status_message  = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMaximumWidth(380)

        self._search_slot = TaskSlot("search")
        self._stats_slot  = TaskSlot("stats")

        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)
        self._search_timer.timeout.connect(self._do_search)

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        btn_open = QPushButton("📂  Open Project Folder")
        btn_open.clicked.connect(self.choose_folder)
        layout.addWidget(btn_open)

        # ── search row ──
        search_row = QHBoxLayout()
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("🔍 Search file contents…")
        self._search_bar.textChanged.connect(lambda: self._search_timer.start())
        self._search_bar.returnPressed.connect(self._do_search)  # immediate on Enter

        self._clear_btn = QPushButton("✕")
        self._clear_btn.setFixedSize(24, 24)
        self._clear_btn.setToolTip("Clear search")
        self._clear_btn.setStyleSheet(f"background:{theme.BG3}; color:{theme.FG_DIM}; border:none; font-size:10pt;")
        self._clear_btn.clicked.connect(self._clear_search)
        self._clear_btn.setVisible(False)

        self._case_cb = QCheckBox("Aa")
        self._case_cb.setToolTip("Case sensitive")
        self._case_cb.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt;")
        self._case_cb.stateChanged.connect(lambda: self._do_search() if self._search_bar.text() else None)

        search_row.addWidget(self._search_bar, 1)
        search_row.addWidget(self._clear_btn)
        search_row.addWidget(self._case_cb)
        layout.addLayout(search_row)

        # make clear button appear/disappear
        self._search_bar.textChanged.connect(
            lambda t: self._clear_btn.setVisible(bool(t))
        )

        # ── progress bar (hidden until stats run) ──
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar {{ background:{theme.BG3}; border:none; border-radius:2px; }}
            QProgressBar::chunk {{ background:{theme.ACCENT}; border-radius:2px; }}
        """)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── file tree ──
        self._model = QFileSystemModel()
        self._model.setFilter(QDir.NoDotAndDotDot | QDir.AllDirs | QDir.Files)
        self._model.setNameFilters(TREE_NAME_FILTERS)
        self._model.setNameFilterDisables(False)

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setColumnWidth(0, 230)
        self._tree.hideColumn(1); self._tree.hideColumn(2); self._tree.hideColumn(3)
        self._tree.setAlternatingRowColors(True)
        self._tree.clicked.connect(self._on_click)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._ctx_menu)
        layout.addWidget(self._tree, 1)

        # ── stats label ──
        self._stats = QLabel("")
        self._stats.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt; padding:2px;")
        self._stats.setWordWrap(True)
        layout.addWidget(self._stats)

        self._git = GitPanel(self.root_path)
        layout.addWidget(self._git)

    # ── public API ────────────────────────────────────────────────────────────

    def root_path(self) -> str | None:
        p = self._model.rootPath()
        return p if p else None

    def set_root(self, path: str) -> None:
        p = str(Path(path).resolve())
        self._model.setRootPath(p)
        self._tree.setRootIndex(self._model.index(p))
        self._git.refresh_root()
        settings.add_recent_project(p)
        settings.last_project = p
        venv = find_venv(p)
        if venv:
            self.venv_found.emit(str(venv))
        self._refresh_stats(p)
        self.status_message.emit(f"Project: {Path(p).name}")

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Project Folder",
            settings.last_project or os.getcwd(),
        )
        if folder:
            self.set_root(folder)

    # ── tree events ───────────────────────────────────────────────────────────

    def _on_click(self, index) -> None:
        path = self._model.filePath(index)
        if os.path.isfile(path) and is_text_file(path):
            self.file_activated.emit(path)

    def _ctx_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        path = self._model.filePath(index)
        menu = QMenu(self)

        if os.path.isdir(path):
            menu.addAction("📄 New File…",   lambda: self._new_file(path))
            menu.addAction("📁 New Folder…", lambda: self._new_folder(path))
            menu.addSeparator()
            menu.addAction("🗜 Zip Folder",  lambda: self._zip(path))
        else:
            if path.endswith(".py"):
                menu.addAction("▶ Run",   lambda: self.run_requested.emit(path))
                menu.addAction("🧪 Lint", lambda: self.lint_requested.emit(path))
            if path.endswith((".md", ".markdown")):
                menu.addAction("👁 Preview", lambda: self.file_activated.emit(path))
            if path.endswith(".zip"):
                menu.addAction("📦 Unzip", lambda: self._unzip(path))
            else:
                menu.addAction("🗜 Zip",   lambda: self._zip(path))
            if Path(path).name == "requirements.txt":
                menu.addAction("📦 Install Deps",
                               lambda: self.run_requested.emit("__install__:" + path))

        menu.addSeparator()
        menu.addAction("✏️ Rename…",   lambda: self._rename(path))
        menu.addAction("📋 Copy Path",
                       lambda: __import__("PyQt5.QtWidgets", fromlist=["QApplication"])
                       .QApplication.clipboard().setText(path))
        menu.addAction("🗑 Delete",    lambda: self._delete(path))
        menu.exec_(self._tree.viewport().mapToGlobal(pos))

    # ── file operations ───────────────────────────────────────────────────────

    def _new_file(self, folder: str) -> None:
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            try:
                p = Path(folder) / name; p.touch()
                self.file_activated.emit(str(p))
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _new_folder(self, folder: str) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            try: (Path(folder) / name).mkdir(parents=True, exist_ok=True)
            except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def _rename(self, path: str) -> None:
        p = Path(path)
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=p.name)
        if ok and new_name and new_name != p.name:
            try: p.rename(p.parent / new_name)
            except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def _delete(self, path: str) -> None:
        p = Path(path)
        if QMessageBox.question(
            self, "Delete", f"Permanently delete '{p.name}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            try:
                p.unlink() if p.is_file() else shutil.rmtree(p)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _zip(self, path: str) -> None:
        src  = Path(path)
        dest = unique_path(src.parent / (src.stem + ".zip")) if src.is_file() \
               else unique_path(src.with_suffix(".zip"))
        try:
            zip_path(src, dest)
            self.status_message.emit(f"Created {dest.name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _unzip(self, path: str) -> None:
        src = Path(path)
        try:
            unzip_to(src, unique_path(src.parent / src.stem))
            self.status_message.emit(f"Extracted to {src.stem}/")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ── search ────────────────────────────────────────────────────────────────

    def _clear_search(self) -> None:
        self._search_bar.clear()
        self._model.setNameFilters(TREE_NAME_FILTERS)
        self._model.setNameFilterDisables(False)
        self.status_message.emit("Search cleared.")

    def _do_search(self) -> None:
        text = self._search_bar.text().strip()
        if not text:
            self._model.setNameFilters(TREE_NAME_FILTERS)
            self._model.setNameFilterDisables(False)
            return

        root = self.root_path()
        if not root:
            return

        self.status_message.emit("Searching…")
        case = self._case_cb.isChecked()

        self._search_slot.run(
            search_content, root, text, case,
            on_done=self._on_search_done,
            on_error=lambda s: self.status_message.emit(f"Search error: {s}"),
        )

    def _on_search_done(self, matches: list) -> None:
        filenames = [Path(m).name for m in matches]
        self._model.setNameFilters(filenames if filenames else ["*.nomatch"])
        self._model.setNameFilterDisables(False)
        n = len(matches)
        self.status_message.emit(f"Found {n} file{'s' if n != 1 else ''}.")

    # ── stats ─────────────────────────────────────────────────────────────────

    def _refresh_stats(self, root: str) -> None:
        self._stats.setText("Scanning…")
        self._progress.setValue(0)
        self._progress.setVisible(True)

        self._stats_slot.run(
            collect_stats, root,
            on_done=self._on_stats,
            on_error=lambda s: (
                self._stats.setText(f"Stats error: {s}"),
                self._progress.setVisible(False),
            ),
            on_progress=self._progress.setValue,
        )

    def _on_stats(self, stats) -> None:
        self._progress.setVisible(False)
        self._stats.setText(
            f"{stats.total_files} files  •  {stats.python_files} .py  •  "
            f"{stats.total_lines:,} lines"
        )
