"""
pycentric.ui.components.editor.editor_tab
==========================================
A self-contained QWidget representing one open file in the editor area.

Improvements (2026)
-------------------
* Line number gutter (LineNumberArea)
* Current-line highlight
* Bracket auto-close: (), [], {}, "", ''
* QPlainTextEdit::undo/redo wired properly (Ctrl+Z / Ctrl+Y)
* Tab key inserts 4 spaces (no hard tab characters)
* Save-with-trailing-whitespace-strip option
* display_name() includes * for unsaved
"""

from __future__ import annotations
from pathlib import Path

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QKeySequence, QPainter, QTextCharFormat, QTextCursor,
)
from PyQt5.QtWidgets import (
    QMessageBox, QPlainTextEdit, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

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


# ── Line-number gutter ────────────────────────────────────────────────────────

class _Gutter(QWidget):
    """Narrow left panel that paints line numbers."""

    WIDTH = 52

    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, 0)

    def paintEvent(self, event) -> None:
        self._editor._paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with line-number gutter + current-line highlight."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_gutter_width(0)
        self._highlight_current_line()

    # ── gutter ────────────────────────────────────────────────────────────────

    def _gutter_width(self) -> int:
        digits = max(1, len(str(self.blockCount())))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, _) -> None:
        self.setViewportMargins(self._gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self._gutter_width(), cr.height()))

    def _paint_gutter(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(theme.BG3))
        block       = self.firstVisibleBlock()
        block_num   = block.blockNumber()
        top         = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom      = top + round(self.blockBoundingRect(block).height())
        cur_block   = self.textCursor().blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                num = str(block_num + 1)
                if block_num == cur_block:
                    painter.setPen(QColor(theme.FG))
                else:
                    painter.setPen(QColor(theme.FG_DIM))
                painter.drawText(
                    0, top, self._gutter.width() - 4, self.fontMetrics().height(),
                    Qt.AlignRight, num,
                )
            block   = block.next()
            top     = bottom
            bottom  = top + round(self.blockBoundingRect(block).height())
            block_num += 1

    # ── current-line highlight ────────────────────────────────────────────────

    def _highlight_current_line(self) -> None:
        extras = []
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(theme.BG3))
            sel.format.setProperty(QTextCharFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extras.append(sel)
        self.setExtraSelections(extras)

    # ── keyboard overrides ────────────────────────────────────────────────────

    _PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}

    def keyPressEvent(self, event) -> None:
        key   = event.text()
        mods  = event.modifiers()

        # Tab → 4 spaces
        if event.key() == Qt.Key_Tab and not mods:
            self.insertPlainText("    ")
            return

        # Shift+Tab → dedent
        if event.key() == Qt.Key_Backtab:
            cur = self.textCursor()
            cur.select(QTextCursor.LineUnderCursor)
            line = cur.selectedText()
            if line.startswith("    "):
                cur.insertText(line[4:])
            elif line.startswith("\t"):
                cur.insertText(line[1:])
            return

        # Auto-close brackets and quotes
        if key in self._PAIRS:
            close  = self._PAIRS[key]
            cur    = self.textCursor()
            sel    = cur.selectedText()
            if sel:
                cur.insertText(key + sel + close)
            else:
                cur.insertText(key + close)
                cur.movePosition(QTextCursor.Left)
                self.setTextCursor(cur)
            return

        # Skip closing char if it's already the next character
        if key in self._PAIRS.values():
            cur  = self.textCursor()
            doc  = self.document()
            nxt  = doc.characterAt(cur.position())
            if nxt == key:
                cur.movePosition(QTextCursor.Right)
                self.setTextCursor(cur)
                return

        super().keyPressEvent(event)


# ── EditorTab ─────────────────────────────────────────────────────────────────

class EditorTab(QWidget):
    """One tab in the multi-file editor."""

    modified_changed = pyqtSignal(bool)
    cursor_moved     = pyqtSignal(int, int)    # (line, col) 1-based
    save_requested   = pyqtSignal()

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

        self.editor = CodeEditor()
        self.editor.setFont(theme.editor_font())
        self.editor.setStyleSheet(f"background:{theme.BG2}; color:{theme.FG}; border:none;")
        self.editor.setTabStopDistance(28)
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

    def save(self, strip_trailing: bool = True) -> bool:
        if not self.path or self.editor.isReadOnly():
            return False
        try:
            text = self.editor.toPlainText()
            if strip_trailing:
                text = "\n".join(l.rstrip() for l in text.splitlines())
                if text and not text.endswith("\n"):
                    text += "\n"
            self.path.write_text(text, encoding="utf-8")
            self._set_modified(False)
            if self._preview_active():
                self._render_markdown()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return False

    # ── undo / redo (expose to toolbar) ──────────────────────────────────────

    def undo(self) -> None:
        self.editor.undo()

    def redo(self) -> None:
        self.editor.redo()

    def can_undo(self) -> bool:
        return self.editor.document().isUndoAvailable()

    def can_redo(self) -> bool:
        return self.editor.document().isRedoAvailable()

    # ── preview ───────────────────────────────────────────────────────────────

    def toggle_preview(self) -> bool:
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

    # ── state ─────────────────────────────────────────────────────────────────

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
        base = self.path.name if self.path else "Untitled"
        return base + (" *" if self._modified else "")

    def goto_line(self, n: int) -> None:
        """Jump editor cursor to line n (1-based)."""
        doc = self.editor.document()
        block = doc.findBlockByLineNumber(max(0, n - 1))
        if block.isValid():
            cur = QTextCursor(block)
            self.editor.setTextCursor(cur)
            self.editor.ensureCursorVisible()
            self.editor.centerCursor()
