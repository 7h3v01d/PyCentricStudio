"""
pycentric.ui.components.cleaner.cleaner_panel
=============================================
Project cache / build artefact cleaner panel.
All deletion logic lives in pycentric.core.services.cleaner.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from pycentric.core.services.cleaner import CLEAN_PATTERNS, CleanPattern, clean, scan
from pycentric.core.utils.threading import BackgroundTask
from pycentric.ui.common import theme


class CleanerPanel(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, status_fn=None, parent=None) -> None:
        super().__init__(parent)
        self._status = status_fn or (lambda m: None)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # folder picker
        frow = QHBoxLayout()
        self._folder = QLineEdit(); self._folder.setPlaceholderText("Project folder…")
        btn = QPushButton("Browse…"); btn.clicked.connect(self._browse)
        frow.addWidget(QLabel("Folder:")); frow.addWidget(self._folder, 1); frow.addWidget(btn)
        layout.addLayout(frow)

        # pattern checkboxes
        pbox = QGroupBox("What to clean")
        pb = QVBoxLayout(pbox)
        self._checks: list[tuple[QCheckBox, CleanPattern]] = []
        for pat in CLEAN_PATTERNS:
            cb = QCheckBox(pat.label)
            cb.setChecked(pat.enabled_by_default)
            self._checks.append((cb, pat))
            pb.addWidget(cb)

        scroll = QScrollArea(); scroll.setWidget(pbox)
        scroll.setWidgetResizable(True); scroll.setMaximumHeight(280)
        layout.addWidget(scroll)

        # action buttons
        brow = QHBoxLayout()
        btn_scan  = QPushButton("🔍 Scan (Preview)")
        btn_clean = QPushButton("🗑 Clean Now")
        btn_clean.setStyleSheet(f"background:{theme.RED}; color:white; font-weight:bold;")
        btn_scan.clicked.connect(self._scan)
        btn_clean.clicked.connect(self._clean)
        brow.addWidget(btn_scan); brow.addWidget(btn_clean)
        layout.addLayout(brow)

        layout.addWidget(QLabel("Output:"))
        self._out = QPlainTextEdit(); self._out.setReadOnly(True)
        self._out.setFont(theme.mono_font())
        layout.addWidget(self._out, 1)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if d: self._folder.setText(d)

    def _selected_patterns(self) -> list[CleanPattern]:
        return [pat for cb, pat in self._checks if cb.isChecked()]

    def _require_folder(self) -> str | None:
        folder = self._folder.text().strip()
        if not folder or not __import__("os").path.isdir(folder):
            QMessageBox.warning(self, "Error", "Select a valid project folder.")
            return None
        return folder

    # ── actions ───────────────────────────────────────────────────────────────

    def _scan(self) -> None:
        folder = self._require_folder()
        if not folder: return
        patterns = self._selected_patterns()
        items = scan(folder, patterns)
        self._out.clear()
        if items:
            self._out.appendPlainText(f"Found {len(items)} item(s) to clean:\n")
            for i in items:
                self._out.appendPlainText(f"  {i}")
        else:
            self._out.appendPlainText("✅ Nothing to clean — project is tidy!")
        self._status(f"Scan: {len(items)} item(s) found.")

    def _clean(self) -> None:
        folder = self._require_folder()
        if not folder: return
        patterns = self._selected_patterns()
        items = scan(folder, patterns)
        if not items:
            self._out.clear(); self._out.appendPlainText("✅ Nothing to clean."); return
        if QMessageBox.question(
            self, "Confirm",
            f"Permanently delete {len(items)} item(s)?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        self._out.clear()
        self._status("Cleaning…")

        def _do_clean():
            return clean(folder, patterns)

        task = self._task = BackgroundTask(_do_clean)
        task.finished.connect(self._on_clean_done)
        task.error.connect(lambda e: self._out.appendPlainText(f"Error: {e}"))
        task.start()

    def _on_clean_done(self, results) -> None:
        deleted = sum(1 for r in results if r.deleted)
        errors  = sum(1 for r in results if not r.deleted)
        for r in results:
            if r.deleted:
                self._out.appendPlainText(f"✅ {r.path}")
            else:
                self._out.appendPlainText(f"❌ {r.path}: {r.error}")
        self._out.appendPlainText(f"\n— Done: {deleted} deleted, {errors} errors —")
        self._status(f"Cleaned {deleted} item(s).")
