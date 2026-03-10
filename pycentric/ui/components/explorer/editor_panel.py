"""
pycentric.ui.components.explorer.editor_panel
=============================================
The right-hand side of the Explorer tab.

2026 improvements
-----------------
* Undo / Redo toolbar buttons (wired to document)
* Go-to-Line (Ctrl+G) dialog
* Lint now prefers `ruff` → falls back to `flake8` → falls back to `pyflakes`
* show_stats uses the current project root from the explorer signal, not cwd
* Word-wrap toggle (Ctrl+Alt+Z)
* process output: timestamps + colour-coded stdout/stderr
"""

from __future__ import annotations
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QProcess, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QShortcut, QSplitter,
    QTabWidget, QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from pycentric.core.services.filesystem import collect_stats
from pycentric.core.services.venv_service import find_venv, python_executable, create_venv
from pycentric.core.types import detect_language
from pycentric.core.utils.threading import BackgroundTask, TaskSlot
from pycentric.ui.common import theme
from pycentric.ui.components.editor.editor_tab import EditorTab
from pycentric.ui.components.editor.find_replace_dlg import FindReplaceDialog


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# Detect which linter is available once at import time
_RUFF    = shutil.which("ruff")
_FLAKE8  = shutil.which("flake8")


class EditorPanel(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._venv_path: Path | None   = None
        self._project_root: str | None = None
        self._stats_slot               = TaskSlot("stats")

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
            "PyCentric Studio\n\n"
            "  • Open a project folder in the sidebar\n"
            "  • Click a file to open it in a tab\n"
            "  • Right-click tree for context options\n"
            "  • Use Ctrl+? to view all keyboard shortcuts\n\n"
            "Editor features:\n"
            "  • Line numbers & current-line highlight\n"
            "  • Syntax highlighting (Python, JS, SQL, MD, …)\n"
            "  • Auto-close brackets and quotes\n"
            "  • Tab → 4 spaces,  Shift+Tab → dedent\n"
            "  • Trailing whitespace stripped on save"
        )
        self._tabs.addTab(_welcome, "Welcome")

        # Output console
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(theme.mono_font())
        self._output.setStyleSheet(f"background:#111; border-top:1px solid {theme.BORDER};")
        self._output.setMaximumHeight(220)

        hdr = QHBoxLayout()
        lbl = QLabel("  OUTPUT"); lbl.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt; font-weight:bold;")
        btn_clr = QPushButton("Clear"); btn_clr.setFixedSize(50, 20)
        btn_clr.clicked.connect(self._output.clear)
        hdr.addWidget(lbl); hdr.addStretch(); hdr.addWidget(btn_clr)

        out_w  = QWidget(); ow = QVBoxLayout(out_w)
        ow.setContentsMargins(0, 0, 0, 0); ow.setSpacing(0)
        ow.addLayout(hdr); ow.addWidget(self._output)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(self._tabs); vsplit.addWidget(out_w)
        vsplit.setSizes([640, 200])
        root.addWidget(vsplit, 1)

    def _make_toolbar(self) -> QToolBar:
        tb = QToolBar(); tb.setMovable(False)
        tb.setStyleSheet(f"background:{theme.BG3}; border-bottom:1px solid {theme.BORDER}; padding:2px;")

        def _add(label, tip, fn):
            b = QPushButton(label); b.setToolTip(tip)
            b.setFixedHeight(26); b.clicked.connect(fn); tb.addWidget(b)

        _add("💾 Save",     "Ctrl+S — save current file",          self.save_current)
        _add("↩ Undo",     "Ctrl+Z — undo",                       self._undo)
        _add("↪ Redo",     "Ctrl+Y — redo",                       self._redo)
        _add("▶ Run",       "Ctrl+R — run Python file",            self.run_py)
        _add("⬛ Stop",     "Kill running process",                self.stop_proc)
        _add("🔍 Find",     "Ctrl+H — find & replace",             self.open_find_replace)
        _add("↕ Go to Ln", "Ctrl+G — jump to line",               self.goto_line)
        _add("👁 Preview",  "Markdown preview (MD files)",         self.toggle_preview)
        _add("🧪 Lint",     f"Lint with {'ruff' if _RUFF else 'flake8'}",  self.lint)
        _add("📦 Venv",     "Create venv in project root",        self.create_venv)
        _add("📊 Stats",    "Project file statistics",             self.show_stats)
        _add("⇌ Wrap",     "Ctrl+Alt+Z — toggle word wrap",       self.toggle_wrap)
        return tb

    def _shortcuts(self) -> None:
        for key, fn in [
            ("Ctrl+S",      self.save_current),
            ("Ctrl+R",      self.run_py),
            ("Ctrl+H",      self.open_find_replace),
            ("Ctrl+G",      self.goto_line),
            ("Ctrl+W",      lambda: self._close_tab(self._tabs.currentIndex())),
            ("Ctrl+T",      self._new_blank_tab),
            ("Ctrl+Z",      self._undo),
            ("Ctrl+Y",      self._redo),
            ("Ctrl+Alt+Z",  self.toggle_wrap),
        ]:
            QShortcut(QKeySequence(key), self).activated.connect(fn)

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
        idx  = self._tabs.addTab(t, name)
        self._tabs.setCurrentIndex(idx)

    def set_venv(self, venv_path: str) -> None:
        self._venv_path = Path(venv_path)
        self.status_message.emit(f"venv: {self._venv_path.name}")

    def set_project_root(self, root: str) -> None:
        """Called by ProjectExplorer whenever a new folder is opened."""
        self._project_root = root

    def run_file(self, path: str) -> None:
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
            if r == QMessageBox.Save:    w.save()
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
        base = self._tabs.tabText(i).rstrip(" *")
        self._tabs.setTabText(i, base + (" *" if modified else ""))

    def _on_cursor(self, ln: int, col: int, tab: EditorTab) -> None:
        if self._tabs.currentWidget() is tab:
            self.status_message.emit(f"Ln {ln}  Col {col}  |  {tab.path or ''}")

    def _cur_tab(self) -> EditorTab | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, EditorTab) else None

    # ── editor actions ────────────────────────────────────────────────────────

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

    def _undo(self) -> None:
        t = self._cur_tab()
        if t: t.undo()

    def _redo(self) -> None:
        t = self._cur_tab()
        if t: t.redo()

    def toggle_preview(self) -> None:
        t = self._cur_tab()
        if t: t.toggle_preview()

    def toggle_wrap(self) -> None:
        t = self._cur_tab()
        if not t: return
        cur = t.editor.lineWrapMode()
        t.editor.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if cur == QPlainTextEdit.NoWrap
            else QPlainTextEdit.NoWrap
        )

    def goto_line(self) -> None:
        t = self._cur_tab()
        if not t: return
        n, ok = QInputDialog.getInt(
            self, "Go to Line", "Line number:",
            value=t.editor.textCursor().blockNumber() + 1,
            min=1, max=max(1, t.editor.document().blockCount()),
        )
        if ok:
            t.goto_line(n)

    def open_find_replace(self) -> None:
        t = self._cur_tab()
        if not t: return
        sel = t.editor.textCursor().selectedText()
        dlg = FindReplaceDialog(t.editor, self)
        if sel: dlg.set_search_term(sel)
        dlg.show()

    # ── run / process ─────────────────────────────────────────────────────────

    def run_py(self) -> None:
        t = self._cur_tab()
        if not t or not t.path or not str(t.path).endswith(".py"):
            self.status_message.emit("Open a .py file to run."); return
        self.save_current()
        self._run_path(str(t.path))

    def _run_path(self, path: str) -> None:
        if self._process.state() == QProcess.Running:
            self.status_message.emit("A process is already running."); return
        self._output.clear()
        self._out(f"▶ {Path(path).name}  [{_ts()}]", theme.CYAN)
        py = python_executable(self._venv_path)
        self._process.start(py, [path])

    def stop_proc(self) -> None:
        if self._process.state() == QProcess.Running:
            self._process.kill()
            self._out("⬛ Killed.", theme.RED)

    def _stdout(self) -> None:
        d = self._process.readAllStandardOutput().data().decode(errors="ignore")
        self._output.insertPlainText(d)
        self._output.ensureCursorVisible()

    def _stderr(self) -> None:
        d = self._process.readAllStandardError().data().decode(errors="ignore")
        self._out(d.rstrip(), theme.RED)

    def _proc_done(self, code: int, _) -> None:
        colour = theme.GREEN if code == 0 else theme.RED
        self._out(f"— exit {code} —  [{_ts()}]", colour)

    def _out(self, msg: str, colour: str = "") -> None:
        col = colour or theme.FG
        self._output.insertHtml(f"<span style='color:{col}'>{msg}</span><br>")
        self._output.ensureCursorVisible()

    # ── lint ──────────────────────────────────────────────────────────────────

    def lint(self) -> None:
        t = self._cur_tab()
        if not t or not t.path or not str(t.path).endswith(".py"):
            self.status_message.emit("Open a .py file to lint."); return
        self._output.clear()
        py  = python_executable(self._venv_path)
        src = str(t.path)

        if _RUFF:
            cmd = [_RUFF, "check", "--output-format=text", src]
            linter = "ruff"
        elif _FLAKE8:
            cmd = [_FLAKE8, "--max-line-length=100", src]
            linter = "flake8"
        else:
            cmd = [py, "-m", "pyflakes", src]
            linter = "pyflakes"

        self._out(f"🧪 {linter}  [{_ts()}]", theme.CYAN)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = (r.stdout + r.stderr).strip()
            if output:
                for line in output.splitlines():
                    # colour error lines red, warnings orange
                    col = theme.RED if ": E" in line or "error" in line.lower() \
                          else theme.ORANGE
                    self._out(line, col)
            else:
                self._out("✅ No issues found.", theme.GREEN)
        except FileNotFoundError:
            self._out(f"{linter} not found — install it in the venv.", theme.RED)
        except Exception as e:
            self._out(str(e), theme.RED)

    def lint_external(self, path: str) -> None:
        self.open_file(path)
        t = self._cur_tab()
        if t and t.path and str(t.path).endswith(".py"):
            self.lint()

    # ── stats ─────────────────────────────────────────────────────────────────

    def show_stats(self) -> None:
        root = self._project_root or os.getcwd()
        self._out(f"📊 Scanning {root} …", theme.CYAN)
        self._stats_slot.run(
            collect_stats, root,
            on_done=self._show_stats_result,
            on_error=lambda s: self._out(f"Stats error: {s}", theme.RED),
        )

    def _show_stats_result(self, stats) -> None:
        self._output.clear()
        self._out(f"📊 Project Stats  ({stats.total_files} files,  "
                  f"{stats.python_files} .py,  {stats.total_lines:,} lines)", theme.CYAN)
        for ext, c in sorted(stats.by_extension.items(), key=lambda x: -x[1])[:20]:
            loc = stats.lines_by_extension.get(ext, 0)
            loc_str = f"  {loc:,} lines" if loc else ""
            self._out(f"  {ext:<12} {c:4} files{loc_str}")

    # ── venv ──────────────────────────────────────────────────────────────────

    def create_venv(self) -> None:
        root = self._project_root or os.getcwd()
        try:
            vd = create_venv(root)
            self.set_venv(str(vd))
            self._out(f"✅ venv created: {vd}", theme.GREEN)
        except FileExistsError:
            QMessageBox.warning(self, "Exists", "A venv already exists here.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def install_requirements(self, req_path: str) -> None:
        from pycentric.core.services.venv_service import pip_executable
        pip = pip_executable(self._venv_path)
        self._output.clear()
        self._out(f"📦 Installing from {req_path}  [{_ts()}]", theme.CYAN)
        self._process.start(pip, ["install", "-r", req_path])
