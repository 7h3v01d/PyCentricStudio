"""
pycentric.ui.components.base64_encoder.base64_panel
====================================================
Base64 Image Encoder panel — converts any image file to a Data URI
and maintains a per-session history.

Ported from encode_icon.py (tkinter + tkinterdnd2) to PyQt5.
Drag-and-drop is handled natively via QWidget.setAcceptDrops().
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QWidget,
)

from pycentric.ui.common import theme


# ── Drag-and-drop zone ────────────────────────────────────────────────────────

class _DropZone(QLabel):
    """A label that accepts file drops and emits file_dropped(path)."""

    file_dropped = pyqtSignal(str)

    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp"}

    def __init__(self) -> None:
        super().__init__("⬇  Drop an image here\nor click Browse")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self._idle()

    # ── appearance ────────────────────────────────────────────────────────────

    def _idle(self) -> None:
        self.setStyleSheet(f"""
            QLabel {{
                background: {theme.BG3};
                border: 2px dashed {theme.BORDER};
                border-radius: 6px;
                color: {theme.FG_DIM};
                padding: 24px;
                min-height: 72px;
            }}
        """)

    def _hover(self) -> None:
        self.setStyleSheet(f"""
            QLabel {{
                background: {theme.BG2};
                border: 2px dashed {theme.ACCENT};
                border-radius: 6px;
                color: {theme.ACCENT};
                padding: 24px;
                min-height: 72px;
            }}
        """)

    # ── drag events ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                ext = Path(urls[0].toLocalFile()).suffix.lower()
                if ext in self._IMAGE_EXTS:
                    event.acceptProposedAction()
                    self._hover()
                    return
        event.ignore()

    def dragLeaveEvent(self, _) -> None:
        self._idle()

    def dropEvent(self, event) -> None:
        self._idle()
        urls = event.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())


# ── Main panel ────────────────────────────────────────────────────────────────

class Base64EncoderPanel(QWidget):
    """
    Standalone panel for encoding images to Base64 Data URIs.

    Signals
    -------
    status_message(str)  — forwarded to the main window status bar
    """

    status_message = pyqtSignal(str)

    _MAX_HISTORY = 12

    def __init__(self, status_fn: Callable[[str], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status_fn = status_fn or (lambda m: None)
        self._history: list[tuple[str, str]] = []   # [(filename, data_uri), …]
        self._build_ui()
        self.status_message.connect(self._status_fn)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Drop zone
        self._drop_zone = _DropZone()
        self._drop_zone.file_dropped.connect(self.process_file)
        root.addWidget(self._drop_zone)

        # Buttons
        btn_row = QHBoxLayout()
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse)

        self._copy_btn = QPushButton("Copy URI")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_latest)

        btn_row.addWidget(browse_btn)
        btn_row.addWidget(self._copy_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Info label
        self._info_label = QLabel()
        self._info_label.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt;")
        self._info_label.setWordWrap(True)
        root.addWidget(self._info_label)

        # History
        hist_hdr = QHBoxLayout()
        hist_hdr.addWidget(QLabel("History  (double-click to copy)"))
        hist_hdr.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_history)
        hist_hdr.addWidget(clear_btn)
        root.addLayout(hist_hdr)

        self._history_list = QListWidget()
        self._history_list.setAlternatingRowColors(True)
        self._history_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._history_list.itemDoubleClicked.connect(self._copy_from_history)
        root.addWidget(self._history_list)

    # ── logic ─────────────────────────────────────────────────────────────────

    def process_file(self, path: str) -> None:
        """Encode *path* and add to history. Called by drop or browse."""
        p = Path(str(path).strip("{}\"'"))
        if not p.exists():
            self.status_message.emit(f"File not found: {p.name}")
            return

        mime, _ = mimetypes.guess_type(str(p))
        mime = mime or "image/png"

        try:
            raw = p.read_bytes()
            b64 = base64.b64encode(raw).decode()
            uri = f"data:{mime};base64,{b64}"
        except Exception as exc:
            self.status_message.emit(f"Encoding failed: {exc}")
            return

        # Prepend to history, cap at _MAX_HISTORY
        self._history.insert(0, (p.name, uri))
        self._history = self._history[:self._MAX_HISTORY]
        self._refresh_history_ui()

        self._copy_btn.setEnabled(True)
        kb_src = len(raw) / 1024
        kb_uri = len(uri) / 1024
        self._info_label.setText(
            f"✓  {p.name}  ·  {mime}  ·  "
            f"{kb_src:.1f} KB source  →  {kb_uri:.1f} KB URI  ({len(uri):,} chars)"
        )
        self.status_message.emit(f"Encoded: {p.name}")

    # ── internals ─────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "",
            "Images (*.png *.jpg *.jpeg *.gif *.svg *.ico *.webp *.bmp)"
        )
        if path:
            self.process_file(path)

    def _copy_latest(self) -> None:
        if self._history:
            self._copy_uri(self._history[0][1])

    def _copy_from_history(self, item: QListWidgetItem) -> None:
        idx = self._history_list.row(item)
        if 0 <= idx < len(self._history):
            self._copy_uri(self._history[idx][1])

    def _copy_uri(self, uri: str) -> None:
        QApplication.clipboard().setText(uri)
        self.status_message.emit("Copied to clipboard!")

    def _clear_history(self) -> None:
        self._history.clear()
        self._history_list.clear()
        self._copy_btn.setEnabled(False)
        self._info_label.clear()
        self.status_message.emit("History cleared")

    def _refresh_history_ui(self) -> None:
        self._history_list.clear()
        for name, uri in self._history:
            approx_kb = (len(uri) * 3 // 4) / 1024
            self._history_list.addItem(f"  📄  {name}   ≈ {approx_kb:.0f} KB")
