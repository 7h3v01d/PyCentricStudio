"""
pycentric.ui.components.editor.editor_tab
==========================================
A self-contained QWidget representing one open file in the editor area.
Responsibilities:
  • Load / save file content
  • Attach the syntax highlighter
  • Host the optional Markdown preview splitter
  • Track modified state and emit signals
"""

from __future__ import annotations
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QPlainTextEdit, QSplitter, QWidget, QVBoxLayout, QMessageBox

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    _HAS_WEB = True
except ImportError:
    _HAS_WEB = False

try:
    import markdown2 as _md2
    _HAS_MD2 = True
except ImportError:
    _HAS_MD2 = False

from pycentric.core.types import Language, detect_language
from pycentric.ui.common import theme
from pycentric.ui.components.editor.highlighter import UniversalHighlighter


class EditorTab(QWidget):
    """One tab in the multi-file editor."""

    modified_changed   = pyqtSignal(bool)       # emitted when dirty state flips
    cursor_moved       = pyqtSignal(int, int)    # (line, col) 1-based
    save_requested     = pyqtSignal()

    def __init__(self, path: str | Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.path: Path | None = Path(path) if path else None
        self._modified = False

        self._build_ui()
        if self.path:
            self.load(self.path)

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Vertical)

        self.editor = QPlainTextEdit()
        self.editor.setFont(theme.editor_font())
        self.editor.setStyleSheet(f"background: {theme.BG2}; color: {theme.FG}; border: none;")
        self.editor.setTabStopDistance(28)   # ~4 spaces in Consolas 11
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)

        self._preview: QWebEngineView | None = None
        if _HAS_WEB:
            self._preview = QWebEngineView()
            self._preview.setVisible(False)
            self._splitter.addWidget(self.editor)
            self._splitter.addWidget(self._preview)
            self._splitter.setSizes([700, 0])
        else:
            self._splitter.addWidget(self.editor)

        layout.addWidget(self._splitter)

        self._highlighter = UniversalHighlighter(self.editor.document(), Language.TEXT)

    # ── load / save ───────────────────────────────────────────────────────────

    def load(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except PermissionError as e:
            self.editor.setPlainText(f"Permission denied: {e}")
            self.editor.setReadOnly(True)
            return
        except Exception as e:
            self.editor.setPlainText(f"Error reading file: {e}")
            self.editor.setReadOnly(True)
            return

        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.editor.setReadOnly(False)
        self._highlighter.set_language(detect_language(self.path))
        self._set_modified(False)

    def save(self) -> bool:
        if not self.path or self.editor.isReadOnly():
            return False
        try:
            self.path.write_text(self.editor.toPlainText(), encoding="utf-8")
            self._set_modified(False)
            if self._preview_active():
                self._render_markdown()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return False

    # ── preview ───────────────────────────────────────────────────────────────

    def toggle_preview(self) -> bool:
        """Toggle Markdown preview.  Returns new visible state."""
        if not (self._preview and self.path and
                self.path.suffix.lower() in (".md", ".markdown")):
            return False
        vis = not self._preview.isVisible()
        self._preview.setVisible(vis)
        if vis:
            self._render_markdown()
            self._splitter.setSizes([400, 400])
        else:
            self._splitter.setSizes([700, 0])
        return vis

    def _preview_active(self) -> bool:
        return bool(self._preview and self._preview.isVisible())

    def _render_markdown(self) -> None:
        if not self._preview:
            return
        if not _HAS_MD2:
            self._preview.setHtml("<i>Install <code>markdown2</code> for preview.</i>")
            return
        html = _md2.markdown(
            self.editor.toPlainText(),
            extras=["fenced-code-blocks", "tables", "codehilite"],
        )
        self._preview.setHtml(f"""<!DOCTYPE html><html><head><style>
            body{{font-family:sans-serif;background:{theme.BG};color:{theme.FG};
                  margin:20px;line-height:1.65}}
            pre{{background:{theme.BG3};padding:12px;border-radius:4px;overflow-x:auto}}
            code{{font-family:Consolas,monospace}}
            a{{color:{theme.CYAN}}}
            table{{border-collapse:collapse}}
            td,th{{border:1px solid {theme.BORDER};padding:4px 10px}}
            blockquote{{border-left:3px solid {theme.ACCENT};padding-left:12px;color:{theme.FG_DIM}}}
        </style></head><body>{html}</body></html>""")

    # ── state helpers ─────────────────────────────────────────────────────────

    @property
    def is_modified(self) -> bool:
        return self._modified

    def _set_modified(self, val: bool) -> None:
        if self._modified != val:
            self._modified = val
            self.modified_changed.emit(val)

    def _on_text_changed(self) -> None:
        self._set_modified(True)

    def _on_cursor_moved(self) -> None:
        cur = self.editor.textCursor()
        self.cursor_moved.emit(cur.blockNumber() + 1, cur.columnNumber() + 1)

    def display_name(self) -> str:
        return self.path.name if self.path else "Untitled"
