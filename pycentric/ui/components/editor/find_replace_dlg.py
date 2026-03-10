"""
pycentric.ui.components.editor.find_replace_dlg
================================================
Non-modal Find & Replace dialog for QPlainTextEdit.
"""

from __future__ import annotations
import re

from PyQt5.QtGui import QKeySequence, QTextDocument
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QShortcut, QVBoxLayout,
)
from pycentric.ui.common.theme import FG_DIM


class FindReplaceDialog(QDialog):
    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent)
        self._editor = editor
        self.setWindowTitle("Find & Replace")
        self.setFixedWidth(480)
        self.setModal(False)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        for row_label, attr in [("Find:", "_find"), ("Replace:", "_replace")]:
            row = QHBoxLayout()
            row.addWidget(QLabel(row_label))
            w = QLineEdit()
            setattr(self, attr, w)
            row.addWidget(w)
            layout.addLayout(row)

        opts = QHBoxLayout()
        self._case = QCheckBox("Case Sensitive")
        self._word = QCheckBox("Whole Word")
        opts.addWidget(self._case); opts.addWidget(self._word)
        layout.addLayout(opts)

        btns = QHBoxLayout()
        for label, slot in [
            ("▼ Next", self.find_next), ("▲ Prev", self.find_prev),
            ("Replace", self.replace_one), ("Replace All", self.replace_all),
        ]:
            b = QPushButton(label); b.clicked.connect(slot); btns.addWidget(b)
        layout.addLayout(btns)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {FG_DIM};")
        layout.addWidget(self._status)

        QShortcut(QKeySequence("Return"), self).activated.connect(self.find_next)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

    # ── internal ─────────────────────────────────────────────────────────────

    def _td_flags(self, backward: bool = False) -> QTextDocument.FindFlags:
        flags = QTextDocument.FindFlags()
        if self._case.isChecked(): flags |= QTextDocument.FindCaseSensitively
        if self._word.isChecked(): flags |= QTextDocument.FindWholeWords
        if backward:               flags |= QTextDocument.FindBackward
        return flags

    def _set_status(self, found: bool) -> None:
        self._status.setText("" if found else "Not found.")

    # ── public API ────────────────────────────────────────────────────────────

    def find_next(self) -> None:
        t = self._find.text()
        if t: self._set_status(self._editor.find(t, self._td_flags()))

    def find_prev(self) -> None:
        t = self._find.text()
        if t: self._set_status(self._editor.find(t, self._td_flags(True)))

    def replace_one(self) -> None:
        cur = self._editor.textCursor()
        if cur.hasSelection():
            cur.insertText(self._replace.text())
        self.find_next()

    def replace_all(self) -> None:
        t = self._find.text()
        if not t:
            return
        flags = 0 if self._case.isChecked() else re.IGNORECASE
        pat = (r'\b' + re.escape(t) + r'\b') if self._word.isChecked() else re.escape(t)
        new_text, n = re.subn(pat, self._replace.text(), self._editor.toPlainText(), flags=flags)
        self._editor.setPlainText(new_text)
        self._status.setText(f"Replaced {n} occurrence(s).")

    def set_search_term(self, term: str) -> None:
        """Pre-fill the find field (e.g. from selected text)."""
        self._find.setText(term)
