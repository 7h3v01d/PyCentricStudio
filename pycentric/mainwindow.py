"""
pycentric.mainwindow
====================
The application's top-level QMainWindow.
Hosts the five-panel tab interface and wires all inter-panel signals.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow, QSplitter, QTabWidget, QWidget, QVBoxLayout

from pycentric.core.settings import settings
from pycentric.ui.common import theme
from pycentric.ui.components.explorer.project_explorer import ProjectExplorer
from pycentric.ui.components.explorer.editor_panel import EditorPanel
from pycentric.ui.components.db_viewer.database_viewer import DatabaseViewerPanel
from pycentric.ui.components.scaffold.scaffold_panel import ScaffoldPanel
from pycentric.ui.components.cleaner.cleaner_panel import CleanerPanel
from pycentric.ui.components.venv_manager.venv_panel import VenvManagerPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PyCentric Studio")
        self.setMinimumSize(1100, 700)

        self._status_bar = self.statusBar()
        self._status_bar.showMessage("Welcome to PyCentric Studio")

        self._build_ui()
        self._wire_signals()

        # Restore last session
        settings.restore_geometry(self)
        last = settings.last_project
        if last:
            self._explorer.set_root(last)

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Main tab bar on the left (VS Code style)
        self._outer_tabs = QTabWidget()
        self._outer_tabs.setTabPosition(QTabWidget.West)
        self._outer_tabs.setStyleSheet(f"""
            QTabBar::tab {{
                background: {theme.BG3}; color: {theme.FG_DIM};
                padding: 12px 6px; border: 1px solid {theme.BORDER};
                margin-bottom: 2px; min-width: 28px; font-size: 12pt;
            }}
            QTabBar::tab:selected {{
                background: {theme.BG}; color: {theme.FG};
                border-left: 3px solid {theme.ACCENT};
            }}
            QTabBar::tab:hover {{ background: {theme.BG2}; color: {theme.FG}; }}
        """)
        self.setCentralWidget(self._outer_tabs)

        # ① Explorer tab  (splitter: tree | editor)
        self._explorer = ProjectExplorer()
        self._editor   = EditorPanel()
        explorer_splitter = QSplitter(Qt.Horizontal)
        explorer_splitter.addWidget(self._explorer)
        explorer_splitter.addWidget(self._editor)
        explorer_splitter.setSizes([300, 1100])
        self._outer_tabs.addTab(explorer_splitter, "📁\nExplorer")

        # ② Database tab
        self._db = DatabaseViewerPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._db, "🗄\nDatabase")

        # ③ Scaffold tab
        self._scaffold = ScaffoldPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._scaffold, "🏗\nScaffold")

        # ④ Cleaner tab
        self._cleaner = CleanerPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._cleaner, "🧹\nCleaner")

        # ⑤ Venv Manager tab
        self._venv = VenvManagerPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._venv, "🐍\nVenvs")

    def _wire_signals(self) -> None:
        self._explorer.file_activated.connect(self._editor.open_file)
        self._explorer.run_requested.connect(self._handle_run)
        self._explorer.lint_requested.connect(self._editor.lint_external)
        self._explorer.venv_found.connect(self._editor.set_venv)
        self._explorer.status_message.connect(self._set_status)
        self._editor.status_message.connect(self._set_status)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_bar.showMessage(msg, 5000)

    def _handle_run(self, path: str) -> None:
        if path.startswith("__install__:"):
            # requirements.txt install request from tree context menu
            req_path = path[len("__install__:"):]
            self._editor.install_requirements(req_path)
        else:
            self._editor.run_file(path)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        settings.save_geometry(self)
        event.accept()
