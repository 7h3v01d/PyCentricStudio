"""
pycentric.ui.components.explorer.editor_panel
=============================================
The right-hand side of the Explorer tab:
  • Multi-file tab editor
  • Toolbar (save / run / stop / find / preview / lint / venv / stats)
  • Output console
  • Keyboard shortcuts
"""

from __future__ import annotations
import os
import subprocess
from pathlib import Path

from PyQt5.QtCore import QProcess, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QShortcut, QSplitter, QTabWidget, QTextEdit, QToolBar,
    QVBoxLayout, QWidget,
)

from pycentric.core.services.filesystem import collect_stats
from pycentric.core.services.venv_service import find_venv, python_executable, create_venv
from pycentric.core.types import detect_language, Language
from pycentric.core.utils.threading import BackgroundTask
from pycentric.ui.common import theme
from pycentric.ui.components.editor.editor_tab import EditorTab
from pycentric.ui.components.editor.find_replace_dlg import FindReplaceDialog


class EditorPanel(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._venv_path: Path | None = None
        self._process = QProcess(self)
        self._process.readyReadStandardOutput.connect(self._stdout)
        self._process.readyReadStandardError.connect(self._stderr)
        self._process.finished.connect(self._proc_done)
        self._build_ui()
        self._shortcuts()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_toolbar())

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._tab_changed)
        self._tabs.setStyleSheet(f"""
            QTabBar::tab {{
                background:{theme.BG3}; color:{theme.FG_DIM};
                padding:5px 14px; border:1px solid {theme.BORDER};
                border-bottom:none; margin-right:2px;
            }}
            QTabBar::tab:selected {{
                background:{theme.BG}; color:{theme.FG};
                border-bottom:2px solid {theme.ACCENT};
            }}
            QTabBar::tab:hover {{ background:{theme.BG2}; color:{theme.FG}; }}
        """)

        # Welcome placeholder
        _welcome = QPlainTextEdit()
        _welcome.setReadOnly(True)
        _welcome.setFont(theme.editor_font())
        _welcome.setStyleSheet(f"background:{theme.BG2}; color:{theme.FG_DIM}; border:none;")
        _welcome.setPlainText(
            "Project Explorer\n\n"
            "  • Open a project folder in the sidebar\n"
            "  • Click a file to open it in a tab\n"
            "  • Right-click for context options\n"
            "  • Use the search bar to find files by content\n\n"
            "Shortcuts:\n"
            "  Ctrl+S   Save      Ctrl+R   Run\n"
            "  Ctrl+H   Find      Ctrl+W   Close tab\n"
            "  Ctrl+T   New tab"
        )
        self._tabs.addTab(_welcome, "Welcome")

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(theme.mono_font())
        self._output.setStyleSheet(f"background:#111; border-top:1px solid {theme.BORDER};")
        self._output.setMaximumHeight(210)

        hdr = QHBoxLayout()
        lbl = QLabel("  OUTPUT")
        lbl.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt; font-weight:bold;")
        btn_clr = QPushButton("Clear"); btn_clr.setFixedSize(50, 20)
        btn_clr.clicked.connect(self._output.clear)
        hdr.addWidget(lbl); hdr.addStretch(); hdr.addWidget(btn_clr)

        out_w = QWidget(); ow = QVBoxLayout(out_w)
        ow.setContentsMargins(0, 0, 0, 0); ow.setSpacing(0)
        ow.addLayout(hdr); ow.addWidget(self._output)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(self._tabs); vsplit.addWidget(out_w)
        vsplit.setSizes([640, 200])
        root.addWidget(vsplit, 1)

    def _make_toolbar(self) -> QToolBar:
        tb = QToolBar(); tb.setMovable(False)
        tb.setStyleSheet(f"background:{theme.BG3}; border-bottom:1px solid {theme.BORDER}; padding:2px;")
        for lbl, tip, fn in [
            ("💾 Save",     "Ctrl+S",  self.save_current),
            ("▶ Run",       "Ctrl+R",  self.run_py),
            ("⬛ Stop",     "Kill",    self.stop_proc),
            ("🔍 Find/Rep", "Ctrl+H",  self.open_find_replace),
            ("👁 Preview",  "MD only", self.toggle_preview),
            ("🧪 Lint",     "flake8",  self.lint),
            ("📦 Venv",     "Create",  self.create_venv),
            ("📊 Stats",    "Project", self.show_stats),
        ]:
            b = QPushButton(lbl); b.setToolTip(tip)
            b.setFixedHeight(26); b.clicked.connect(fn); tb.addWidget(b)
        return tb

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save_current)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.run_py)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self.open_find_replace)
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(
            lambda: self._close_tab(self._tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(self._new_blank_tab)

    # ── public API ────────────────────────────────────────────────────────────

    def open_file(self, path: str) -> None:
        p = str(Path(path).resolve())
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, EditorTab) and str(w.path) == p:
                self._tabs.setCurrentIndex(i); return
        t = EditorTab(p)
        t.modified_changed.connect(lambda m, tab=t: self._mark_mod(m, tab))
        t.cursor_moved.connect(lambda ln, col, tab=t: self._on_cursor(ln, col, tab))
        name = Path(p).name
        idx = self._tabs.addTab(t, name)
        self._tabs.setCurrentIndex(idx)

    def set_venv(self, venv_path: str) -> None:
        self._venv_path = Path(venv_path)
        self.status_message.emit(f"venv: {self._venv_path.name}")

    def run_file(self, path: str) -> None:
        """Called externally (e.g. from tree context menu)."""
        self.open_file(path)
        self._run_path(path)

    # ── tab management ────────────────────────────────────────────────────────

    def _new_blank_tab(self) -> None:
        t = EditorTab()
        t.editor.setFont(theme.editor_font())
        self._tabs.addTab(t, "Untitled")
        self._tabs.setCurrentIndex(self._tabs.count() - 1)

    def _close_tab(self, i: int) -> None:
        w = self._tabs.widget(i)
        if isinstance(w, EditorTab) and w.is_modified:
            name = self._tabs.tabText(i).rstrip(" *")
            r = QMessageBox.question(
                self, "Unsaved Changes", f"Save '{name}'?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if r == QMessageBox.Save:   w.save()
            elif r == QMessageBox.Cancel: return
        self._tabs.removeTab(i)

    def _tab_changed(self, i: int) -> None:
        w = self._tabs.widget(i)
        if isinstance(w, EditorTab) and w.path:
            lang = detect_language(w.path).value
            self.status_message.emit(f"{w.path}  |  {lang}")

    def _mark_mod(self, modified: bool, tab: EditorTab) -> None:
        i = self._tabs.indexOf(tab)
        if i < 0: return
        txt = self._tabs.tabText(i)
        if modified and not txt.endswith("*"):
            self._tabs.setTabText(i, txt + " *")
        elif not modified and txt.endswith(" *"):
            self._tabs.setTabText(i, txt[:-2])

    def _on_cursor(self, ln: int, col: int, tab: EditorTab) -> None:
        if self._tabs.currentWidget() is tab:
            self.status_message.emit(f"Ln {ln}, Col {col}  |  {tab.path or ''}")

    def _cur_tab(self) -> EditorTab | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, EditorTab) else None

    # ── actions ───────────────────────────────────────────────────────────────

    def save_current(self) -> None:
        t = self._cur_tab()
        if not t: return
        if t.path:
            t.save()
            self.status_message.emit(f"Saved {t.display_name()}")
        else:
            p, _ = QFileDialog.getSaveFileName(self, "Save As", os.getcwd())
            if p:
                t.path = Path(p)
                t.save()
                self._tabs.setTabText(self._tabs.currentIndex(), Path(p).name)

    def toggle_preview(self) -> None:
        t = self._cur_tab()
        if t: t.toggle_preview()

    def open_find_replace(self) -> None:
        t = self._cur_tab()
        if not t: return
        sel = t.editor.textCursor().selectedText()
        dlg = FindReplaceDialog(t.editor, self)
        if sel: dlg.set_search_term(sel)
        dlg.show()

    def run_py(self) -> None:
        t = self._cur_tab()
        if not t or not t.path or not str(t.path).endswith(".py"):
            self.status_message.emit("Select a .py file to run."); return
        self.save_current()
        self._run_path(str(t.path))

    def _run_path(self, path: str) -> None:
        if self._process.state() == QProcess.Running:
            self.status_message.emit("A process is already running."); return
        self._output.clear()
        self._output.append(f"<span style='color:{theme.CYAN}'>▶ {Path(path).name}</span><br>")
        py = python_executable(self._venv_path)
        self._process.start(py, [path])

    def stop_proc(self) -> None:
        if self._process.state() == QProcess.Running:
            self._process.kill()
            self._output.append(f"<span style='color:{theme.RED}'>⬛ Killed.</span>")

    def _stdout(self) -> None:
        d = self._process.readAllStandardOutput().data().decode(errors="ignore")
        self._output.insertPlainText(d); self._output.ensureCursorVisible()

    def _stderr(self) -> None:
        d = self._process.readAllStandardError().data().decode(errors="ignore")
        self._output.insertHtml(f"<span style='color:{theme.RED}'>{d}</span>")
        self._output.ensureCursorVisible()

    def _proc_done(self, code: int, _) -> None:
        self._output.append(f"<br><span style='color:{theme.FG_DIM}'>— exit {code} —</span>")

    def lint(self) -> None:
        t = self._cur_tab()
        if not t or not t.path or not str(t.path).endswith(".py"):
            self.status_message.emit("Select a .py file to lint."); return
        self._output.clear()
        self._output.append(f"<span style='color:{theme.CYAN}'>🧪 flake8</span><br>")
        py = python_executable(self._venv_path)
        try:
            r = subprocess.run(
                [py, "-m", "flake8", "--max-line-length=100", str(t.path)],
                capture_output=True, text=True, timeout=20,
            )
            if r.stdout:
                for line in r.stdout.strip().splitlines():
                    self._output.append(f"<span style='color:{theme.ORANGE}'>{line}</span>")
            else:
                self._output.append(f"<span style='color:{theme.GREEN}'>✅ No issues.</span>")
        except Exception as e:
            self._output.append(f"<span style='color:{theme.RED}'>{e}</span>")

    def create_venv(self) -> None:
        root = os.getcwd()  # best guess; real root comes from explorer signal
        try:
            vd = create_venv(root)
            self.set_venv(str(vd))
            self._output.append(f"<span style='color:{theme.GREEN}'>✅ venv: {vd}</span>")
        except FileExistsError:
            QMessageBox.warning(self, "Exists", "A venv already exists here.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def show_stats(self) -> None:
        # Run in a background task; pull root from model if possible
        # For now just report the current working directory
        root = os.getcwd()
        task = BackgroundTask(collect_stats, root)
        task.finished.connect(self._show_stats_result)
        task.start()

    def _show_stats_result(self, stats) -> None:
        self._output.clear()
        lines = [f"<b>Stats</b>  ({stats.total_files} files)<br>"]
        for ext, c in sorted(stats.by_extension.items(), key=lambda x: -x[1])[:20]:
            loc = stats.lines_by_extension.get(ext, 0)
            loc_str = f"  {loc:,} lines" if loc else ""
            lines.append(f"&nbsp;&nbsp;<span style='color:{theme.CYAN}'>{ext}</span> "
                         f"{c} files{loc_str}<br>")
        self._output.insertHtml("".join(lines))

    def lint_external(self, path: str) -> None:
        """Called externally with an explicit path."""
        self.open_file(path)
        self._tabs.setCurrentIndex(self._tabs.count() - 1)
        # switch to the tab we just opened, then lint
        t = self._cur_tab()
        if t and t.path and str(t.path).endswith(".py"):
            self.lint()

    def install_requirements(self, req_path: str) -> None:
        """pip install -r <req_path> using the current venv."""
        from pycentric.core.services.venv_service import pip_executable
        pip = pip_executable(self._venv_path)
        self._output.clear()
        self._output.append(f"<span style='color:{theme.CYAN}'>📦 Installing from {req_path}…</span><br>")
        self._process.start(pip, ["install", "-r", req_path])
