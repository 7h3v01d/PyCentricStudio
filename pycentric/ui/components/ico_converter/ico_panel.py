"""
pycentric.ui.components.ico_converter.ico_panel
================================================
PNG → ICO converter panel.

Adapted from png_to_ico_gui_v0.3.py (PyQt6) to PyQt5.
Adds:
  • Drag-and-drop input
  • Auto-suggested output path (same dir, same stem, .ico extension)
  • Per-size checkboxes so the user can choose which resolutions to embed
  • Live preview via QPixmap (no temp file needed)
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSplitter, QVBoxLayout, QWidget, QLineEdit,
    QGridLayout,
)

from pycentric.ui.common import theme

try:
    from PIL import Image as _PILImage
    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False


# ── standard ICO sizes ────────────────────────────────────────────────────────

_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


# ── Drag-and-drop zone ────────────────────────────────────────────────────────

class _DropZone(QLabel):
    file_dropped = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__("⬇  Drop a PNG here\nor click Browse")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self._idle()

    def _idle(self) -> None:
        self.setStyleSheet(f"""
            QLabel {{
                background: {theme.BG3};
                border: 2px dashed {theme.BORDER};
                border-radius: 6px;
                color: {theme.FG_DIM};
                padding: 20px;
                min-height: 64px;
            }}
        """)

    def _hover(self) -> None:
        self.setStyleSheet(f"""
            QLabel {{
                background: {theme.BG2};
                border: 2px dashed {theme.ACCENT};
                border-radius: 6px;
                color: {theme.ACCENT};
                padding: 20px;
                min-height: 64px;
            }}
        """)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            ext = Path(event.mimeData().urls()[0].toLocalFile()).suffix.lower()
            if ext == ".png":
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

class IcoConverterPanel(QWidget):
    """PNG → ICO conversion with live preview and size selection."""

    status_message = pyqtSignal(str)

    def __init__(self, status_fn: Callable[[str], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status_fn = status_fn or (lambda m: None)
        self.status_message.connect(self._status_fn)
        self._build_ui()

        if not _HAS_PILLOW:
            self.status_message.emit("Pillow not installed — pip install Pillow")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── left: controls ──────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(20, 16, 12, 16)
        lv.setSpacing(12)

        # Drop zone
        self._drop = _DropZone()
        self._drop.file_dropped.connect(self._load_png)
        lv.addWidget(self._drop)

        # Input path
        in_row = QHBoxLayout()
        self._png_edit = QLineEdit()
        self._png_edit.setPlaceholderText("PNG input path…")
        self._png_edit.textChanged.connect(self._on_path_typed)
        browse_in = QPushButton("Browse…")
        browse_in.clicked.connect(self._browse_png)
        in_row.addWidget(self._png_edit)
        in_row.addWidget(browse_in)
        lv.addLayout(in_row)

        # Output path
        out_row = QHBoxLayout()
        self._ico_edit = QLineEdit()
        self._ico_edit.setPlaceholderText("ICO output path…")
        browse_out = QPushButton("Save as…")
        browse_out.clicked.connect(self._browse_ico)
        out_row.addWidget(self._ico_edit)
        out_row.addWidget(browse_out)
        lv.addLayout(out_row)

        # Size checkboxes
        size_box = QGroupBox("Embed sizes (px)")
        size_grid = QGridLayout(size_box)
        self._size_checks: dict[tuple[int, int], QCheckBox] = {}
        for i, sz in enumerate(_SIZES):
            cb = QCheckBox(f"{sz[0]}")
            cb.setChecked(True)
            self._size_checks[sz] = cb
            size_grid.addWidget(cb, i // 4, i % 4)
        lv.addWidget(size_box)

        # Convert button
        self._convert_btn = QPushButton("Convert to ICO")
        self._convert_btn.setMinimumHeight(36)
        self._convert_btn.clicked.connect(self._convert)
        lv.addWidget(self._convert_btn)

        lv.addStretch()
        splitter.addWidget(left)

        # ── right: preview ──────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 16, 20, 16)
        rv.setSpacing(8)

        rv.addWidget(QLabel("Preview"))

        self._preview = QLabel("No image selected")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumSize(220, 220)
        self._preview.setStyleSheet(f"""
            background: {theme.BG3};
            border: 1px solid {theme.BORDER};
            border-radius: 6px;
            color: {theme.FG_DIM};
        """)
        rv.addWidget(self._preview)

        self._img_info = QLabel()
        self._img_info.setAlignment(Qt.AlignCenter)
        self._img_info.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt;")
        self._img_info.setWordWrap(True)
        rv.addWidget(self._img_info)
        rv.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([440, 240])
        root.addWidget(splitter)

    # ── logic ─────────────────────────────────────────────────────────────────

    def _load_png(self, path: str) -> None:
        path = path.strip("{}\"'")
        self._png_edit.setText(path)
        # Auto-suggest output alongside input file
        p = Path(path)
        self._ico_edit.setText(str(p.with_suffix(".ico")))
        self._update_preview(path)

    def _on_path_typed(self, text: str) -> None:
        if Path(text).is_file():
            self._update_preview(text)

    def _browse_png(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select PNG", "", "PNG (*.png)")
        if path:
            self._load_png(path)

    def _browse_ico(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save ICO", "", "ICO (*.ico)")
        if path:
            if not path.lower().endswith(".ico"):
                path += ".ico"
            self._ico_edit.setText(path)

    def _update_preview(self, path: str) -> None:
        if not _HAS_PILLOW:
            return
        try:
            img = _PILImage.open(path).convert("RGBA")
            w, h = img.size
            img.thumbnail((210, 210), _PILImage.Resampling.LANCZOS)
            tw, th = img.size
            raw = img.tobytes("raw", "RGBA")
            qimg = QImage(raw, tw, th, tw * 4, QImage.Format_RGBA8888)
            self._preview.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    210, 210,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            self._preview.setText("")
            self._img_info.setText(f"{Path(path).name}  ·  {w} × {h} px")
        except Exception as exc:
            self._preview.setText("Error loading image")
            self._img_info.setText(str(exc))

    def _convert(self) -> None:
        if not _HAS_PILLOW:
            self.status_message.emit("Pillow required — pip install Pillow")
            return

        png_path = self._png_edit.text().strip()
        ico_path = self._ico_edit.text().strip()

        if not png_path or not Path(png_path).is_file():
            self.status_message.emit("Select a valid PNG file first")
            return
        if not ico_path:
            self.status_message.emit("Specify an output ICO path")
            return

        sizes = [sz for sz, cb in self._size_checks.items() if cb.isChecked()]
        if not sizes:
            self.status_message.emit("Check at least one size")
            return

        try:
            img = _PILImage.open(png_path).convert("RGBA")
            img.save(ico_path, format="ICO", sizes=sizes)
            size_str = ", ".join(str(s[0]) for s in sorted(sizes))
            self.status_message.emit(
                f"Saved {Path(ico_path).name}  ({len(sizes)} sizes: {size_str} px)"
            )
        except Exception as exc:
            self.status_message.emit(f"Conversion failed: {exc}")
