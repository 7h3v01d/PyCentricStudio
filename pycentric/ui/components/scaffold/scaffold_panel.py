"""
pycentric.ui.components.scaffold.scaffold_panel
================================================
Project structure scaffold builder.
Parse a Unicode-box-drawing tree → create real files/folders or zip.
"""

from __future__ import annotations
import os
import tempfile
import zipfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from pycentric.core.types import FILE_TEMPLATES
from pycentric.ui.common import theme

# ── Presets ───────────────────────────────────────────────────────────────────

PRESETS: dict[str, str] = {
    "Standard Python Package": """\
my_package/
├── .gitignore
├── README.md
├── LICENSE.md
├── pyproject.toml
├── requirements.txt
├── src/
│   └── my_package/
│       ├── __init__.py
│       ├── core.py
│       └── utils.py
└── tests/
    ├── __init__.py
    └── test_core.py""",

    "CLI Application": """\
my_cli_app/
├── .gitignore
├── README.md
├── pyproject.toml
├── requirements.txt
├── src/
│   └── my_cli_app/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       └── core/
│           ├── __init__.py
│           └── logic.py
└── tests/
    ├── __init__.py
    └── test_cli.py""",

    "GUI + CLI Application": """\
my_app/
├── .gitignore
├── README.md
├── pyproject.toml
├── requirements.txt
├── src/
│   └── my_app/
│       ├── __init__.py
│       ├── __main__.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── logic.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── commands.py
│       └── gui/
│           ├── __init__.py
│           ├── main_window.py
│           └── assets/
│               └── style.qss
└── tests/
    ├── __init__.py
    ├── test_cli.py
    └── test_gui.py""",

    "Flask / FastAPI Microservice": """\
api_project/
├── .gitignore
├── README.md
├── pyproject.toml
├── requirements.txt
├── run.py
├── src/
│   └── api/
│       ├── __init__.py
│       ├── routes.py
│       └── models.py
└── tests/
    ├── test_routes.py
    └── conftest.py""",

    "Data Science Workflow": """\
ds_project/
├── README.md
├── environment.yml
├── notebooks/
│   ├── exploration.ipynb
│   └── modeling.ipynb
├── src/
│   └── analysis/
│       ├── __init__.py
│       ├── preprocessing.py
│       ├── train.py
│       └── visualize.py
├── data/
│   ├── raw/
│   └── cleaned/
└── tests/
    └── test_preprocessing.py""",

    "Plugin Library": """\
plugin_lib/
├── README.md
├── pyproject.toml
├── src/
│   └── pluginlib/
│       ├── __init__.py
│       ├── core.py
│       └── plugins/
│           ├── __init__.py
│           ├── plugin_a.py
│           └── plugin_b.py
└── tests/
    ├── test_core.py
    └── test_plugins.py""",

    "Security / Crypto Library": """\
securex/
├── README.md
├── pyproject.toml
├── requirements.txt
├── src/
│   └── securex/
│       ├── __init__.py
│       ├── crypto/
│       │   ├── __init__.py
│       │   ├── encrypt.py
│       │   └── decrypt.py
│       └── auth/
│           ├── __init__.py
│           └── login.py
└── tests/
    ├── test_encrypt.py
    └── test_auth.py""",
}


def parse_tree(text: str) -> list[tuple[str, bool]]:
    """
    Convert a Unicode box-drawing tree to (relative_path, is_dir) pairs.
    Handles │  ├── └── prefixes of any depth.
    """
    stack: list[str] = []
    result: list[tuple[str, bool]] = []

    for line in text.strip().splitlines():
        # Strip box-drawing chars and leading whitespace to get the name
        clean = line.lstrip("│├└─ \t")
        if not clean.strip():
            continue

        # Calculate indent depth (each level is 4 chars: "│   " or "    ")
        prefix_len = len(line) - len(line.lstrip("│├└─ \t"))
        level = prefix_len // 4

        is_dir = clean.endswith("/")
        name   = clean.rstrip("/") if is_dir else clean

        # Trim stack to current level
        stack = stack[:level]
        stack.append(name)

        full = os.path.join(*stack)
        result.append((full, is_dir))

    return result


class ScaffoldPanel(QWidget):
    def __init__(self, status_fn=None, parent=None) -> None:
        super().__init__(parent)
        self._status = status_fn or (lambda msg: None)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── left: presets + editor ──
        left = QWidget(); ll = QVBoxLayout(left); ll.setSpacing(6)

        preset_box = QGroupBox("Presets")
        pb = QVBoxLayout(preset_box)
        self._preset_list = QListWidget()
        self._preset_list.addItems(PRESETS.keys())
        self._preset_list.currentTextChanged.connect(self._load_preset)
        pb.addWidget(self._preset_list)
        btn_row = QHBoxLayout()
        for lbl, fn in [
            ("Load", self._load_selected),
            ("Save…", self._save_preset),
            ("Open…", self._open_preset),
        ]:
            b = QPushButton(lbl); b.clicked.connect(fn); btn_row.addWidget(b)
        pb.addLayout(btn_row)
        ll.addWidget(preset_box)

        editor_box = QGroupBox("Tree Editor")
        eb = QVBoxLayout(editor_box)
        self._edit = QPlainTextEdit()
        self._edit.setFont(theme.mono_font())
        self._edit.setPlaceholderText(
            "Paste or type a directory tree…\n\n"
            "project/\n├── src/\n│   └── main.py\n└── README.md"
        )
        self._edit.textChanged.connect(self._update_preview)
        eb.addWidget(self._edit)

        actions = QHBoxLayout()
        for lbl, fn in [
            ("🏗 Build…", self._build),
            ("📦 Export Zip…", self._export_zip),
            ("📋 Copy", self._copy),
        ]:
            b = QPushButton(lbl); b.clicked.connect(fn); actions.addWidget(b)
        eb.addLayout(actions)
        ll.addWidget(editor_box, 1)
        layout.addWidget(left, 1)

        # ── right: live preview + log ──
        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Live Preview"))
        self._preview = QPlainTextEdit(); self._preview.setReadOnly(True)
        self._preview.setFont(theme.mono_font())
        rl.addWidget(self._preview, 1)
        rl.addWidget(QLabel("Output Log"))
        self._log = QPlainTextEdit(); self._log.setReadOnly(True)
        self._log.setFont(theme.mono_font()); self._log.setMaximumHeight(130)
        rl.addWidget(self._log)
        layout.addWidget(right, 1)

    # ── preset helpers ────────────────────────────────────────────────────────

    def _load_preset(self, name: str) -> None:
        if name in PRESETS:
            self._edit.setPlainText(PRESETS[name])

    def _load_selected(self) -> None:
        item = self._preset_list.currentItem()
        if item: self._load_preset(item.text())

    def _save_preset(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(self, "Save Preset", "", "Tree Files (*.tree);;All (*)")
        if fn:
            Path(fn).write_text(self._edit.toPlainText(), encoding="utf-8")
            self._status(f"Preset saved: {fn}")

    def _open_preset(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(self, "Open Preset", "", "Tree Files (*.tree);;All (*)")
        if fn:
            self._edit.setPlainText(Path(fn).read_text(encoding="utf-8"))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._edit.toPlainText())
        self._status("Tree copied to clipboard.")

    # ── preview ───────────────────────────────────────────────────────────────

    def _update_preview(self) -> None:
        try:
            items = parse_tree(self._edit.toPlainText())
            lines = [f"{'[DIR] ' if d else '[FILE]'} {p}" for p, d in items]
            self._preview.setPlainText("\n".join(lines))
        except Exception:
            self._preview.setPlainText("⚠ Invalid tree format")

    # ── build / export ────────────────────────────────────────────────────────

    def _iter_paths(self) -> list[tuple[str, bool]] | None:
        txt = self._edit.toPlainText()
        if not txt.strip():
            QMessageBox.warning(self, "Empty", "Enter a directory tree first.")
            return None
        return parse_tree(txt)

    def _write_structure(self, base: str | Path, items: list[tuple[str, bool]]) -> None:
        base = Path(base)
        for rel_path, is_dir in items:
            full = base / rel_path
            if is_dir:
                full.mkdir(parents=True, exist_ok=True)
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                ext = full.suffix
                full.write_text(FILE_TEMPLATES.get(ext, ""), encoding="utf-8")

    def _build(self) -> None:
        items = self._iter_paths()
        if items is None: return
        dest = QFileDialog.getExistingDirectory(self, "Choose Destination")
        if not dest: return
        try:
            self._write_structure(dest, items)
            self._log.appendPlainText(f"✅ Structure built in {dest}")
            self._status(f"Built in {dest}")
            QMessageBox.information(self, "Done", "Project structure created!")
        except Exception as e:
            self._log.appendPlainText(f"❌ {e}")
            QMessageBox.critical(self, "Error", str(e))

    def _export_zip(self) -> None:
        items = self._iter_paths()
        if items is None: return
        fn, _ = QFileDialog.getSaveFileName(self, "Export Zip", "", "Zip Files (*.zip)")
        if not fn: return
        try:
            with tempfile.TemporaryDirectory() as td:
                self._write_structure(td, items)
                with zipfile.ZipFile(fn, "w", zipfile.ZIP_DEFLATED) as zf:
                    for r, _, files in os.walk(td):
                        for f in files:
                            fp = os.path.join(r, f)
                            zf.write(fp, os.path.relpath(fp, td))
            self._log.appendPlainText(f"📦 Exported to {fn}")
            self._status(f"Zip exported: {fn}")
        except Exception as e:
            self._log.appendPlainText(f"❌ {e}")
            QMessageBox.critical(self, "Error", str(e))
