"""
pycentric.ui.components.file_tree.file_tree_panel
==================================================
File Tree Diagram Generator panel.

Ported from file2tree_gui_v1.1.py (tkinter) to PyQt5.
Improvements over the original:
  • Integrated with PyCentric's project root — auto-loads the open project
  • "Use current project" button wires into the explorer's active path
  • All / None selection shortcuts
  • Options: show hidden files, dirs-first ordering
  • Copy-to-clipboard with one click
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from pycentric.ui.common import theme


class FileTreePanel(QWidget):
    """
    Select a directory, choose which top-level items to include,
    and generate a Unicode tree diagram ready to paste into docs or READMEs.

    Public API
    ----------
    set_project_root(path)  — called by MainWindow when a project is opened
    """

    status_message = pyqtSignal(str)

    def __init__(self, status_fn: Callable[[str], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status_fn = status_fn or (lambda m: None)
        self._root_dir: str = ""
        self.status_message.connect(self._status_fn)
        self._build_ui()

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
        lv.setSpacing(10)

        # Directory row
        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText("Root directory…")
        self._dir_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_dir)
        use_proj_btn = QPushButton("Use Project")
        use_proj_btn.setToolTip("Load the currently open project folder")
        use_proj_btn.clicked.connect(self._use_project)
        dir_row.addWidget(self._dir_edit)
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(use_proj_btn)
        lv.addLayout(dir_row)

        # Item list header
        list_hdr = QHBoxLayout()
        list_hdr.addWidget(QLabel("Items to include:"))
        list_hdr.addStretch()
        all_btn = QPushButton("All")
        all_btn.clicked.connect(lambda: self._select_all(True))
        none_btn = QPushButton("None")
        none_btn.clicked.connect(lambda: self._select_all(False))
        list_hdr.addWidget(all_btn)
        list_hdr.addWidget(none_btn)
        lv.addLayout(list_hdr)

        # Item list
        self._item_list = QListWidget()
        self._item_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._item_list.setAlternatingRowColors(True)
        lv.addWidget(self._item_list)

        # Options
        opt_row = QHBoxLayout()
        self._show_hidden = QCheckBox("Hidden files")
        self._dirs_first  = QCheckBox("Dirs first")
        self._dirs_first.setChecked(True)
        opt_row.addWidget(self._show_hidden)
        opt_row.addWidget(self._dirs_first)
        opt_row.addStretch()
        lv.addLayout(opt_row)

        # Generate button
        gen_btn = QPushButton("Generate Tree")
        gen_btn.setMinimumHeight(36)
        gen_btn.clicked.connect(self._generate)
        lv.addWidget(gen_btn)

        splitter.addWidget(left)

        # ── right: output ────────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 16, 20, 16)
        rv.setSpacing(8)

        out_hdr = QHBoxLayout()
        out_hdr.addWidget(QLabel("Output"))
        out_hdr.addStretch()
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy)
        out_hdr.addWidget(copy_btn)
        rv.addLayout(out_hdr)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Consolas", 10))
        self._output.setPlaceholderText(
            "Tree will appear here after you click Generate…\n\n"
            "Example:\n"
            "my_project/\n"
            "├── src/\n"
            "│   ├── main.py\n"
            "│   └── utils.py\n"
            "└── README.md"
        )
        rv.addWidget(self._output)

        splitter.addWidget(right)
        splitter.setSizes([300, 500])
        root.addWidget(splitter)

    # ── public API ────────────────────────────────────────────────────────────

    def set_project_root(self, path: str) -> None:
        """Called by MainWindow when a project folder is opened."""
        if path and Path(path).is_dir():
            self._root_dir = path
            self._dir_edit.setText(path)
            self._populate_items(path)

    # ── internals ─────────────────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Root Directory")
        if d:
            self._root_dir = d
            self._dir_edit.setText(d)
            self._populate_items(d)
            self.status_message.emit(f"Loaded: {Path(d).name}/")

    def _use_project(self) -> None:
        if self._root_dir:
            self._populate_items(self._root_dir)
            self.status_message.emit(f"Loaded project: {Path(self._root_dir).name}/")
        else:
            self.status_message.emit("No project open — use File › Open Project first")

    def _populate_items(self, directory: str) -> None:
        self._item_list.clear()
        show_hidden = self._show_hidden.isChecked()
        try:
            entries = sorted(os.listdir(directory))
            for name in entries:
                if not show_hidden and name.startswith("."):
                    continue
                is_dir = os.path.isdir(os.path.join(directory, name))
                icon = "📁" if is_dir else "📄"
                label = f"{name}/" if is_dir else name
                item = QListWidgetItem(f"  {icon}  {label}")
                item.setData(Qt.UserRole, name)   # store raw name for tree building
                self._item_list.addItem(item)
            self._select_all(True)
            self.status_message.emit(
                f"Loaded {len(entries)} items from '{Path(directory).name}'"
            )
        except PermissionError:
            self.status_message.emit("Permission denied reading directory")

    def _select_all(self, select: bool) -> None:
        for i in range(self._item_list.count()):
            self._item_list.item(i).setSelected(select)

    def _generate(self) -> None:
        if not self._root_dir or not os.path.isdir(self._root_dir):
            self.status_message.emit("Select a valid directory first")
            return

        selected = [
            self._item_list.item(i).data(Qt.UserRole)
            for i in range(self._item_list.count())
            if self._item_list.item(i).isSelected()
        ]
        if not selected:
            self.status_message.emit("No items selected — nothing to generate")
            return

        tree = self._build_tree(self._root_dir, selected)
        self._output.setPlainText(tree)
        lines = tree.count("\n") + 1
        self.status_message.emit(f"Tree generated: {lines} lines")

    def _build_tree(self, root_dir: str, selected: list[str]) -> str:
        lines = [f"{Path(root_dir).name}/"]

        if self._dirs_first.isChecked():
            selected = sorted(
                selected,
                key=lambda x: (not os.path.isdir(os.path.join(root_dir, x)), x.lower())
            )
        else:
            selected = sorted(selected, key=str.lower)

        for i, name in enumerate(selected):
            is_last = (i == len(selected) - 1)
            self._recurse(lines, os.path.join(root_dir, name), [], is_last)

        return "\n".join(lines)

    def _recurse(self, lines: list[str], path: str,
                 parent_flags: list[bool], is_last: bool) -> None:
        """Recursively build tree lines. parent_flags: True = parent was last child."""
        indent = "".join("    " if flag else "│   " for flag in parent_flags)
        prefix = "└── " if is_last else "├── "
        name   = Path(path).name

        if os.path.isdir(path):
            lines.append(f"{indent}{prefix}{name}/")
            new_flags = parent_flags + [is_last]
            try:
                children  = sorted(os.listdir(path))
                dirs  = [c for c in children if os.path.isdir(os.path.join(path, c))]
                files = [c for c in children if os.path.isfile(os.path.join(path, c))]
                all_c = dirs + files
                for j, child in enumerate(all_c):
                    self._recurse(
                        lines,
                        os.path.join(path, child),
                        new_flags,
                        j == len(all_c) - 1,
                    )
            except PermissionError:
                lines.append(f"{indent}    └── <permission denied>")
        else:
            lines.append(f"{indent}{prefix}{name}")

    def _copy(self) -> None:
        text = self._output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_message.emit("Tree copied to clipboard")
        else:
            self.status_message.emit("Generate a tree first")
