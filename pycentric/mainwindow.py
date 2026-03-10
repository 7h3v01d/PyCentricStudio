"""
pycentric.mainwindow
====================
The application's top-level QMainWindow.
Five-panel tab interface.

2026 additions
--------------
* File menu with Recent Projects submenu + Clear Recent
* View menu (Keyboard Shortcuts dialog)
* Status bar: persistent right-side label for interpreter/venv
"""

from __future__ import annotations
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAction, QDialog, QLabel, QMainWindow, QMenu, QMenuBar,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from pycentric.core.settings import settings
from pycentric.ui.common import theme
from pycentric.ui.components.explorer.project_explorer import ProjectExplorer
from pycentric.ui.components.explorer.editor_panel import EditorPanel
from pycentric.ui.components.db_viewer.database_viewer import DatabaseViewerPanel
from pycentric.ui.components.scaffold.scaffold_panel import ScaffoldPanel
from pycentric.ui.components.cleaner.cleaner_panel import CleanerPanel
from pycentric.ui.components.venv_manager.venv_panel import VenvManagerPanel
from pycentric.ui.components.import_mapper.import_mapper_panel import ImportMapperPanel
from pycentric.ui.components.base64_encoder.base64_panel import Base64EncoderPanel
from pycentric.ui.components.ico_converter.ico_panel import IcoConverterPanel
from pycentric.ui.components.file_tree.file_tree_panel import FileTreePanel


_SHORTCUTS = """
╔══════════════════════════════════════════════════════╗
║          PyCentric Studio — Keyboard Shortcuts        ║
╠════════════════════════╦═════════════════════════════╣
║  Editor                ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Ctrl + S              ║  Save current file          ║
║  Ctrl + R              ║  Run Python file            ║
║  Ctrl + H              ║  Find & Replace             ║
║  Ctrl + W              ║  Close tab                  ║
║  Ctrl + T              ║  New blank tab              ║
║  Ctrl + Enter          ║  Run SQL query (DB tab)     ║
╠════════════════════════╬═════════════════════════════╣
║  Search                ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Type in search bar    ║  Search file contents       ║
║  Enter                 ║  Search immediately         ║
║  ✕ button             ║  Clear search               ║
║  Aa checkbox           ║  Toggle case-sensitivity    ║
╠════════════════════════╬═════════════════════════════╣
║  File Tree             ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Left-click file       ║  Open in editor             ║
║  Right-click           ║  Context menu               ║
║  Right-click .py       ║  Run / Lint                 ║
║  Right-click .md       ║  Preview                    ║
╠════════════════════════╬═════════════════════════════╣
║  Venv Manager          ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Environments tab      ║  Create / clone / delete    ║
║  Packages tab          ║  Install, dep tree          ║
║  PyPI Browser          ║  Search & install           ║
║  Outdated tab          ║  Upgrade outdated packages  ║
║  Snapshots tab         ║  Save / export snapshots    ║
╠════════════════════════╬═════════════════════════════╣
║  Import Mapper         ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  F5                    ║  Re-scan current project    ║
║  Export Arch HTML      ║  Layer view in browser      ║
║  Export Graph HTML     ║  Force-graph (needs pyvis)  ║
║  Export Markdown       ║  Full text report           ║
║  Export JSON           ║  Machine-readable dump      ║
║  Clear Cache           ║  Force full re-scan         ║
╠════════════════════════╬═════════════════════════════╣
║  Base64 Encoder        ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Drop image            ║  Encode to Data URI         ║
║  Browse…               ║  Pick file via dialog       ║
║  Copy URI              ║  Copy latest result         ║
║  Double-click history  ║  Copy that entry's URI      ║
╠════════════════════════╬═════════════════════════════╣
║  ICO Converter         ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Drop PNG              ║  Load + auto-suggest output ║
║  Size checkboxes       ║  Choose embedded resolutions║
║  Convert to ICO        ║  Save multi-size ICO file   ║
╠════════════════════════╬═════════════════════════════╣
║  Tree Generator        ║  Action                     ║
╠════════════════════════╬═════════════════════════════╣
║  Use Project           ║  Load currently open project║
║  All / None            ║  Select/deselect all items  ║
║  Generate Tree         ║  Build Unicode tree diagram ║
║  Copy                  ║  Copy tree to clipboard     ║
╚════════════════════════╩═════════════════════════════╝
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PyCentric Studio")
        self.setMinimumSize(1100, 700)

        self._build_menu()
        self._build_ui()
        self._build_statusbar()
        self._wire_signals()

        settings.restore_geometry(self)
        last = settings.last_project
        if last:
            self._explorer.set_root(last)

    # ── menu bar ──────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # ── File ──
        file_menu = mb.addMenu("&File")

        open_act = QAction("&Open Project…", self)
        open_act.setShortcut("Ctrl+Shift+O")
        open_act.triggered.connect(lambda: self._explorer.choose_folder())
        file_menu.addAction(open_act)

        self._recent_menu = QMenu("Open &Recent", self)
        file_menu.addMenu(self._recent_menu)
        self._refresh_recent_menu()

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # ── View ──
        view_menu = mb.addMenu("&View")
        keys_act = QAction("&Keyboard Shortcuts…", self)
        keys_act.setShortcut("Ctrl+?")
        keys_act.triggered.connect(self._show_shortcuts)
        view_menu.addAction(keys_act)

        # ── Help ──
        help_menu = mb.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = settings.recent_projects()
        if not recent:
            self._recent_menu.addAction("(no recent projects)").setEnabled(False)
        else:
            for path in recent:
                p = Path(path)
                act = QAction(f"{p.name}  —  {p.parent}", self)
                act.setData(path)
                act.triggered.connect(lambda checked, p=path: self._open_recent(p))
                self._recent_menu.addAction(act)
            self._recent_menu.addSeparator()
            clear_act = QAction("Clear Recent", self)
            clear_act.triggered.connect(self._clear_recent)
            self._recent_menu.addAction(clear_act)

    def _open_recent(self, path: str) -> None:
        if Path(path).is_dir():
            self._explorer.set_root(path)
            self._refresh_recent_menu()
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Not Found", f"'{path}' no longer exists.")
            settings.recent_projects()  # keep; user can clear manually

    def _clear_recent(self) -> None:
        settings.clear_recent()
        self._refresh_recent_menu()

    # ── dialogs ───────────────────────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.setMinimumSize(580, 520)
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setFont(__import__("PyQt5.QtGui", fromlist=["QFont"]).QFont("Consolas", 10))
        txt.setPlainText(_SHORTCUTS)
        txt.setStyleSheet(f"background:{theme.BG2}; color:{theme.FG}; border:none;")
        lay.addWidget(txt)
        btn = QPushButton("Close"); btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec_()

    def _show_about(self) -> None:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.about(
            self, "About PyCentric Studio",
            "<b>PyCentric Studio</b> v1.2<br><br>"
            "An all-in-one Python project tool.<br>"
            "Editor · Database · Scaffold · Cleaner · Venv Manager · Import Mapper<br>"
            "Base64 Encoder · PNG→ICO Converter · File Tree Generator<br><br>"
            "Built with PyQt5."
        )

    # ── main UI ───────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._outer_tabs = QTabWidget()
        self._outer_tabs.setTabPosition(QTabWidget.West)
        self._outer_tabs.setStyleSheet(f"""
            QTabBar::tab {{
                background:{theme.BG3}; color:{theme.FG_DIM};
                padding:12px 6px; border:1px solid {theme.BORDER};
                margin-bottom:2px; min-width:28px; font-size:12pt;
            }}
            QTabBar::tab:selected {{
                background:{theme.BG}; color:{theme.FG};
                border-left:3px solid {theme.ACCENT};
            }}
            QTabBar::tab:hover {{ background:{theme.BG2}; color:{theme.FG}; }}
        """)
        self.setCentralWidget(self._outer_tabs)

        # ① Explorer (tree | editor)
        self._explorer = ProjectExplorer()
        self._editor   = EditorPanel()
        exp_split = QSplitter(Qt.Horizontal)
        exp_split.addWidget(self._explorer)
        exp_split.addWidget(self._editor)
        exp_split.setSizes([300, 1100])
        self._outer_tabs.addTab(exp_split,                          "📁\nExplorer")

        # ② Database
        self._db = DatabaseViewerPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._db,                           "🗄\nDatabase")

        # ③ Scaffold
        self._scaffold = ScaffoldPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._scaffold,                     "🏗\nScaffold")

        # ④ Cleaner
        self._cleaner = CleanerPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._cleaner,                      "🧹\nCleaner")

        # ⑤ Venv Manager
        self._venv = VenvManagerPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._venv,                         "🐍\nVenvs")

        # ⑥ Import Mapper
        self._import_mapper = ImportMapperPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._import_mapper,                "🗺\nImports")

        # ⑦ Base64 Encoder
        self._base64 = Base64EncoderPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._base64,                       "🔡\nBase64")

        # ⑧ PNG → ICO Converter
        self._ico = IcoConverterPanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._ico,                          "🖼\nICO")

        # ⑨ File Tree Generator
        self._file_tree = FileTreePanel(status_fn=self._set_status)
        self._outer_tabs.addTab(self._file_tree,                    "🌲\nTree")

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        sb.showMessage("Welcome to PyCentric Studio")
        # Permanent right-side label for interpreter / venv info
        self._interp_label = QLabel("  🐍 default python  ")
        self._interp_label.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt;")
        sb.addPermanentWidget(self._interp_label)

    def _wire_signals(self) -> None:
        self._explorer.file_activated.connect(self._editor.open_file)
        self._explorer.run_requested.connect(self._handle_run)
        self._explorer.lint_requested.connect(self._editor.lint_external)
        self._explorer.venv_found.connect(self._on_venv_found)
        self._explorer.status_message.connect(self._set_status)
        self._editor.status_message.connect(self._set_status)
        # Keep editor aware of current project root for stats / venv creation
        self._explorer.status_message.connect(
            lambda _: self._editor.set_project_root(self._explorer.root_path() or "")
        )
        # Keep Import Mapper in sync with the open project
        self._explorer.status_message.connect(
            lambda _: self._import_mapper.set_project_root(self._explorer.root_path() or "")
        )
        # Keep File Tree in sync with the open project
        self._explorer.status_message.connect(
            lambda _: self._file_tree.set_project_root(self._explorer.root_path() or "")
        )
        # Refresh recent menu after every project open
        self._explorer.status_message.connect(
            lambda _: self._refresh_recent_menu()
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 6000)

    def _on_venv_found(self, venv_path: str) -> None:
        self._editor.set_venv(venv_path)
        name = Path(venv_path).name
        import sys
        py = sys.version.split()[0]
        self._interp_label.setText(f"  🐍 {name}  (py {py})  ")

    def _handle_run(self, path: str) -> None:
        if path.startswith("__install__:"):
            self._editor.install_requirements(path[len("__install__:"):])
        else:
            self._editor.run_file(path)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        settings.save_geometry(self)
        event.accept()
