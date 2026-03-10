"""
pycentric.ui.components.venv_manager.venv_panel
================================================
Virtual Environment Manager panel.

Sub-tabs
--------
① Environments   — list, create, clone, delete, wipe, health, activate
② Packages       — installed list, dep tree viewer, upgrade/uninstall per-package
③ PyPI Browser   — search PyPI, view package info, pick version, install
④ Outdated       — list outdated packages, upgrade individually or all
⑤ Snapshots      — save / restore / export requirements snapshots
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

import pycentric.core.services.venv_backend as vbe
from pycentric.core.utils.threading import BackgroundTask, TaskSlot
from pycentric.ui.common import theme


# ── Helpers ───────────────────────────────────────────────────────────────────

def _btn(label: str, handler, tooltip: str = "", color: str = "") -> QPushButton:
    b = QPushButton(label)
    b.clicked.connect(handler)
    if tooltip:
        b.setToolTip(tooltip)
    if color:
        b.setStyleSheet(f"background:{color}; color:white; font-weight:bold;")
    return b


def _mono(w: QPlainTextEdit | QTextEdit) -> None:
    w.setFont(QFont("Consolas", 10))


# ── Main panel ────────────────────────────────────────────────────────────────

class VenvManagerPanel(QWidget):
    status_message = pyqtSignal(str)

    def __init__(self, status_fn=None, parent=None) -> None:
        super().__init__(parent)
        self._status = status_fn or (lambda m: None)
        self._envs: dict = {}
        # Per-operation slots — each holds its task alive and enforces at-most-one
        self._slot_envs    = TaskSlot("envs")
        self._slot_pkgs    = TaskSlot("packages")
        self._slot_dep     = TaskSlot("deptree")
        self._slot_pypi    = TaskSlot("pypi_search")
        self._slot_info    = TaskSlot("pypi_info")
        self._slot_outdated= TaskSlot("outdated")
        self._slot_task    = TaskSlot("generic")    # for create/delete/install/etc.
        self._build_ui()
        self._reload_envs()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # ── output console ──
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(160)
        _mono(self._log)
        self._log.setStyleSheet(f"background:#111; border-top:1px solid {theme.BORDER};")

        log_hdr = QHBoxLayout()
        log_lbl = QLabel("  OUTPUT")
        log_lbl.setStyleSheet(f"color:{theme.FG_DIM}; font-size:9pt; font-weight:bold;")
        clr_btn = QPushButton("Clear"); clr_btn.setFixedSize(50, 20)
        clr_btn.clicked.connect(self._log.clear)
        log_hdr.addWidget(log_lbl); log_hdr.addStretch(); log_hdr.addWidget(clr_btn)

        log_w = QWidget(); lw = QVBoxLayout(log_w)
        lw.setContentsMargins(0, 0, 0, 0); lw.setSpacing(0)
        lw.addLayout(log_hdr); lw.addWidget(self._log)

        # ── tabs ──
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_envs_tab(),      "🐍 Environments")
        self._tabs.addTab(self._build_packages_tab(),  "📦 Packages")
        self._tabs.addTab(self._build_pypi_tab(),      "🔍 PyPI Browser")
        self._tabs.addTab(self._build_outdated_tab(),  "⬆ Outdated")
        self._tabs.addTab(self._build_snapshots_tab(), "📸 Snapshots")
        self._tabs.currentChanged.connect(self._on_tab_change)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(self._tabs)
        vsplit.addWidget(log_w)
        vsplit.setSizes([600, 160])
        root.addWidget(vsplit)

    # ── Tab ①: Environments ───────────────────────────────────────────────────

    def _build_envs_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        # toolbar
        tb = QToolBar(); tb.setMovable(False)
        tb.setStyleSheet(f"background:{theme.BG3}; border-bottom:1px solid {theme.BORDER};")
        for lbl, fn, tip in [
            ("🔄 Refresh",    self._reload_envs,    "Reload all environments"),
            ("➕ New",        self._dlg_create,      "Create a new venv"),
            ("📋 Clone",      self._clone_env,       "Clone selected environment"),
            ("🗑 Delete",     self._delete_env,      "Delete selected environment"),
            ("🧹 Wipe",       self._wipe_env,        "Remove all packages from env"),
            ("▶ Activate",   self._activate_env,    "Copy activate command to clipboard"),
            ("💾 Export Req", self._export_req,      "Export requirements.txt"),
            ("📸 Snapshot",   self._save_snapshot,   "Save package snapshot"),
        ]:
            b = QPushButton(lbl); b.setFixedHeight(26)
            b.setToolTip(tip); b.clicked.connect(fn); tb.addWidget(b)
        lay.addWidget(tb)

        # env table
        self._env_table = QTableWidget(0, 7)
        self._env_table.setHorizontalHeaderLabels(
            ["Name", "Python", "Packages", "Size (MB)", "Health", "Project", "Created"]
        )
        self._env_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._env_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._env_table.setAlternatingRowColors(True)
        self._env_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._env_table.setColumnWidth(0, 160); self._env_table.setColumnWidth(1, 130)
        self._env_table.setColumnWidth(2, 80);  self._env_table.setColumnWidth(3, 90)
        self._env_table.setColumnWidth(4, 80);  self._env_table.setColumnWidth(5, 140)
        self._env_table.setColumnWidth(6, 150)
        self._env_table.currentCellChanged.connect(self._on_env_selected)
        lay.addWidget(self._env_table, 1)

        # detail panel below table
        self._env_detail = QPlainTextEdit(); self._env_detail.setReadOnly(True)
        self._env_detail.setMaximumHeight(120); _mono(self._env_detail)
        lay.addWidget(self._env_detail)
        return w

    # ── Tab ②: Packages ───────────────────────────────────────────────────────

    def _build_packages_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Environment:"))
        self._pkg_env = QComboBox(); self._pkg_env.currentTextChanged.connect(self._load_packages)
        top.addWidget(self._pkg_env)
        top.addStretch()
        top.addWidget(_btn("🔄 Refresh", self._load_packages))
        lay.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        # left: installed packages list
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Installed Packages"))

        self._pkg_filter = QLineEdit(); self._pkg_filter.setPlaceholderText("Filter…")
        self._pkg_filter.textChanged.connect(self._filter_packages)
        ll.addWidget(self._pkg_filter)

        self._pkg_table = QTableWidget(0, 2)
        self._pkg_table.setHorizontalHeaderLabels(["Package", "Version"])
        self._pkg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pkg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pkg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._pkg_table.setAlternatingRowColors(True)
        self._pkg_table.currentCellChanged.connect(self._on_pkg_selected)
        ll.addWidget(self._pkg_table, 1)

        pkg_btns = QHBoxLayout()
        pkg_btns.addWidget(_btn("📥 Info",     self._show_pypi_info_for_pkg, "Fetch PyPI info"))
        pkg_btns.addWidget(_btn("⬆ Upgrade",  self._upgrade_pkg))
        pkg_btns.addWidget(_btn("🗑 Remove",   self._remove_pkg, color=theme.RED))
        ll.addLayout(pkg_btns)
        splitter.addWidget(left)

        # right: dependency tree
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4, 0, 0, 0)
        rl.addWidget(QLabel("Dependency Tree"))
        self._dep_tree = QTreeWidget()
        self._dep_tree.setHeaderLabels(["Package", "Version", "Summary"])
        self._dep_tree.setColumnWidth(0, 180); self._dep_tree.setColumnWidth(1, 80)
        self._dep_tree.setAlternatingRowColors(True)
        rl.addWidget(self._dep_tree, 1)
        rl.addWidget(_btn("🌳 Load Tree", self._load_dep_tree))

        # package install row
        inst_row = QHBoxLayout()
        self._pkg_install_name = QLineEdit(); self._pkg_install_name.setPlaceholderText("package or package==1.2.3")
        inst_row.addWidget(self._pkg_install_name, 1)
        inst_row.addWidget(_btn("📥 Install", self._install_pkg))
        rl.addLayout(inst_row)
        splitter.addWidget(right)
        splitter.setSizes([400, 500])
        lay.addWidget(splitter, 1)
        return w

    # ── Tab ③: PyPI Browser ───────────────────────────────────────────────────

    def _build_pypi_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        # search bar
        search_row = QHBoxLayout()
        self._pypi_query = QLineEdit(); self._pypi_query.setPlaceholderText("Search PyPI…")
        self._pypi_query.returnPressed.connect(self._search_pypi)
        search_row.addWidget(self._pypi_query, 1)
        search_row.addWidget(_btn("🔍 Search", self._search_pypi))
        lay.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)

        # left: results list
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Results"))
        self._pypi_results = QTableWidget(0, 3)
        self._pypi_results.setHorizontalHeaderLabels(["Package", "Version", "Summary"])
        self._pypi_results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pypi_results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pypi_results.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._pypi_results.setColumnWidth(0, 160); self._pypi_results.setColumnWidth(1, 80)
        self._pypi_results.setAlternatingRowColors(True)
        self._pypi_results.currentCellChanged.connect(self._on_pypi_result_selected)
        ll.addWidget(self._pypi_results, 1)
        splitter.addWidget(left)

        # right: package detail + install
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4, 0, 0, 0)

        info_grp = QGroupBox("Package Info")
        ig = QVBoxLayout(info_grp)
        self._pypi_info = QPlainTextEdit(); self._pypi_info.setReadOnly(True); _mono(self._pypi_info)
        ig.addWidget(self._pypi_info)
        rl.addWidget(info_grp, 1)

        install_grp = QGroupBox("Install into Environment")
        ilg = QFormLayout(install_grp)
        self._pypi_env = QComboBox()
        self._pypi_ver = QComboBox()
        ilg.addRow("Environment:", self._pypi_env)
        ilg.addRow("Version:", self._pypi_ver)
        rl.addWidget(install_grp)

        install_row = QHBoxLayout()
        install_row.addWidget(_btn("📥 Install Selected", self._install_from_pypi))
        install_row.addWidget(_btn("📋 Copy pip command", self._copy_pip_cmd))
        rl.addLayout(install_row)
        splitter.addWidget(right)
        splitter.setSizes([400, 500])
        lay.addWidget(splitter, 1)
        return w

    # ── Tab ④: Outdated ───────────────────────────────────────────────────────

    def _build_outdated_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Environment:"))
        self._out_env = QComboBox(); top.addWidget(self._out_env)
        top.addWidget(_btn("🔄 Check Outdated", self._check_outdated))
        top.addWidget(_btn("⬆ Upgrade All",     self._upgrade_all))
        top.addStretch()
        lay.addLayout(top)

        self._out_table = QTableWidget(0, 3)
        self._out_table.setHorizontalHeaderLabels(["Package", "Installed", "Latest"])
        self._out_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._out_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._out_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._out_table.setAlternatingRowColors(True)
        lay.addWidget(self._out_table, 1)

        lay.addWidget(_btn("⬆ Upgrade Selected", self._upgrade_selected_outdated))
        return w

    # ── Tab ⑤: Snapshots ──────────────────────────────────────────────────────

    def _build_snapshots_tab(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Environment:"))
        self._snap_env = QComboBox(); top.addWidget(self._snap_env)
        top.addWidget(_btn("📸 Save Snapshot", self._save_snapshot))
        top.addWidget(_btn("🔄 Refresh List",  self._load_snapshots))
        top.addStretch()
        lay.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        snap_list_w = QWidget(); sl = QVBoxLayout(snap_list_w); sl.setContentsMargins(0,0,0,0)
        sl.addWidget(QLabel("Saved Snapshots"))
        self._snap_list = QTableWidget(0, 2)
        self._snap_list.setHorizontalHeaderLabels(["Filename", "Date"])
        self._snap_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._snap_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._snap_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._snap_list.currentCellChanged.connect(self._on_snap_selected)
        sl.addWidget(self._snap_list, 1)
        sl.addWidget(_btn("📤 Export as requirements.txt", self._export_snap))
        splitter.addWidget(snap_list_w)

        snap_detail_w = QWidget(); sd = QVBoxLayout(snap_detail_w); sd.setContentsMargins(4,0,0,0)
        sd.addWidget(QLabel("Snapshot Contents"))
        self._snap_detail = QPlainTextEdit(); self._snap_detail.setReadOnly(True); _mono(self._snap_detail)
        sd.addWidget(self._snap_detail, 1)
        splitter.addWidget(snap_detail_w)
        splitter.setSizes([300, 600])
        lay.addWidget(splitter, 1)
        return w

    # ── Data loading ──────────────────────────────────────────────────────────

    def _reload_envs(self) -> None:
        self._log_info("Loading environments…")
        self._slot_envs.run(
            vbe.load_environments,
            on_done=self._on_envs_loaded,
            on_error=lambda e: self._log_err(f"Load failed: {e}"),
        )

    def _on_envs_loaded(self, envs: dict) -> None:
        self._envs = envs
        self._env_table.setRowCount(0)
        combos = [self._pkg_env, self._pypi_env, self._out_env, self._snap_env]
        current = [c.currentText() for c in combos]
        for c in combos:
            c.blockSignals(True); c.clear()

        for name, info in envs.items():
            ok, _ = vbe.check_health(name)
            row = self._env_table.rowCount()
            self._env_table.insertRow(row)
            meta = info.get("metadata", {})
            cells = [
                name,
                info.get("python_version", "?"),
                str(len(info.get("packages", {}))),
                f"{info.get('size_mb', 0):.1f}",
                "✅" if ok else "⚠",
                meta.get("project", ""),
                meta.get("created", "")[:10],
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if col == 4:
                    item.setForeground(QColor(theme.GREEN if ok else theme.YELLOW))
                self._env_table.setItem(row, col, item)
            for c in combos:
                c.addItem(name)

        for c, prev in zip(combos, current):
            idx = c.findText(prev)
            if idx >= 0: c.setCurrentIndex(idx)
            c.blockSignals(False)

        self._log_ok(f"Loaded {len(envs)} environment(s).")
        self._status(f"Venv: {len(envs)} environments")

    def _selected_env_name(self) -> str | None:
        row = self._env_table.currentRow()
        if row < 0: return None
        item = self._env_table.item(row, 0)
        return item.text() if item else None

    def _on_env_selected(self, row, *_) -> None:
        item = self._env_table.item(row, 0)
        if not item: return
        name = item.text()
        info = self._envs.get(name, {})
        meta = info.get("metadata", {})
        ok, health_msg = vbe.check_health(name)
        self._env_detail.setPlainText(
            f"Name:    {name}\n"
            f"Path:    {info.get('path', '')}\n"
            f"Python:  {info.get('python_version', '?')}\n"
            f"Packages:{len(info.get('packages', {}))}\n"
            f"Size:    {info.get('size_mb', 0):.2f} MB\n"
            f"Health:  {'OK' if ok else 'Issues — ' + health_msg}\n"
            f"Project: {meta.get('project', '')}\n"
            f"ID:      {info.get('env_id', '')}\n"
            f"Created: {meta.get('created', '')[:19]}\n"
            f"Template:{meta.get('template', 'None')}"
        )

    # ── Package tab ───────────────────────────────────────────────────────────

    def _load_packages(self) -> None:
        name = self._pkg_env.currentText()
        if not name: return
        self._log_info(f"Loading packages for {name}…")
        self._slot_pkgs.run(
            vbe.get_installed_packages, name,
            on_done=self._on_packages_loaded,
            on_error=lambda e: self._log_err(e),
        )

    def _on_packages_loaded(self, pkgs: dict) -> None:
        self._all_pkgs = pkgs
        self._populate_pkg_table(pkgs)

    def _populate_pkg_table(self, pkgs: dict) -> None:
        self._pkg_table.setRowCount(0)
        for name, ver in sorted(pkgs.items(), key=lambda x: x[0].lower()):
            row = self._pkg_table.rowCount()
            self._pkg_table.insertRow(row)
            self._pkg_table.setItem(row, 0, QTableWidgetItem(name))
            self._pkg_table.setItem(row, 1, QTableWidgetItem(ver))

    def _filter_packages(self) -> None:
        q = self._pkg_filter.text().lower()
        if not hasattr(self, "_all_pkgs"): return
        filtered = {k: v for k, v in self._all_pkgs.items() if q in k.lower()}
        self._populate_pkg_table(filtered)

    def _on_pkg_selected(self, row, *_) -> None:
        self._dep_tree.clear()  # Clear tree on new selection

    def _selected_pkg(self) -> str | None:
        row = self._pkg_table.currentRow()
        item = self._pkg_table.item(row, 0)
        return item.text() if item else None

    def _load_dep_tree(self) -> None:
        name = self._pkg_env.currentText()
        pkg  = self._selected_pkg()
        if not name or not pkg: return
        self._log_info(f"Building dependency tree for {pkg}…")
        self._slot_dep.run(
            vbe.get_dependency_tree, name, pkg,
            on_done=self._on_dep_tree_loaded,
            on_error=lambda e: self._log_err(e),
        )

    def _on_dep_tree_loaded(self, tree: dict) -> None:
        self._dep_tree.clear()
        if not tree:
            self._dep_tree.addTopLevelItem(QTreeWidgetItem(["No dependencies found"]))
            return
        root_pkg = next(iter(tree))
        root_info = tree[root_pkg]

        def _add_node(parent, pkg_name: str, visited: set) -> None:
            if pkg_name in visited: return
            visited.add(pkg_name)
            info = tree.get(pkg_name, {})
            node = QTreeWidgetItem(parent, [pkg_name, info.get("version", "?"), info.get("summary", "")[:60]])
            node.setForeground(0, QColor(theme.CYAN))
            for dep in info.get("requires", []):
                _add_node(node, dep, visited)

        root_node = QTreeWidgetItem(self._dep_tree, [
            root_pkg, root_info.get("version", "?"), root_info.get("summary", "")[:60]
        ])
        root_node.setForeground(0, QColor(theme.GREEN))
        for dep in root_info.get("requires", []):
            _add_node(root_node, dep, {root_pkg})
        self._dep_tree.expandAll()
        self._log_ok(f"Tree loaded for {root_pkg} ({len(tree)} nodes).")

    def _install_pkg(self) -> None:
        name = self._pkg_env.currentText()
        spec = self._pkg_install_name.text().strip()
        if not name or not spec: return
        self._log_info(f"Installing {spec} into {name}…")
        self._run_task(vbe.install_package, name, spec)

    def _upgrade_pkg(self) -> None:
        name = self._pkg_env.currentText()
        pkg  = self._selected_pkg()
        if not name or not pkg: return
        self._run_task(vbe.upgrade_package, name, pkg)

    def _remove_pkg(self) -> None:
        name = self._pkg_env.currentText()
        pkg  = self._selected_pkg()
        if not name or not pkg: return
        if QMessageBox.question(
            self, "Confirm", f"Uninstall '{pkg}' from '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self._run_task(vbe.uninstall_package, name, pkg)

    def _show_pypi_info_for_pkg(self) -> None:
        pkg = self._selected_pkg()
        if pkg:
            self._tabs.setCurrentIndex(2)
            self._pypi_query.setText(pkg)
            self._fetch_pypi_info(pkg)

    # ── PyPI tab ──────────────────────────────────────────────────────────────

    def _search_pypi(self) -> None:
        q = self._pypi_query.text().strip()
        if not q: return
        self._log_info(f"Searching PyPI for '{q}'…")
        self._slot_pypi.run(
            vbe.search_pypi, q,
            on_done=self._on_search_done,
            on_error=lambda e: self._log_err(e),
        )

    def _on_search_done(self, result: tuple) -> None:
        ok, data = result
        if not ok:
            self._log_err(str(data)); return
        self._pypi_results.setRowCount(0)
        for pkg in data:
            row = self._pypi_results.rowCount()
            self._pypi_results.insertRow(row)
            self._pypi_results.setItem(row, 0, QTableWidgetItem(pkg["name"]))
            self._pypi_results.setItem(row, 1, QTableWidgetItem(pkg["version"]))
            self._pypi_results.setItem(row, 2, QTableWidgetItem(pkg["summary"][:80]))
        self._log_ok(f"Found {len(data)} result(s).")

    def _on_pypi_result_selected(self, row, *_) -> None:
        item = self._pypi_results.item(row, 0)
        if item:
            self._fetch_pypi_info(item.text())

    def _fetch_pypi_info(self, pkg: str) -> None:
        self._slot_info.run(
            vbe.get_pypi_info, pkg,
            on_done=self._on_pypi_info,
            on_error=lambda e: self._log_err(e),
        )

    def _on_pypi_info(self, result: tuple) -> None:
        ok, data = result
        if not ok:
            self._pypi_info.setPlainText(str(data)); return
        lines = [
            f"Name:          {data['name']}",
            f"Version:       {data['version']}",
            f"Summary:       {data['summary']}",
            f"Author:        {data['author']}",
            f"License:       {data['license']}",
            f"Requires Py:   {data['requires_python']}",
            f"Home Page:     {data['home_page']}",
            f"Keywords:      {data['keywords']}",
            "",
            "Description:",
            data["description"],
        ]
        self._pypi_info.setPlainText("\n".join(lines))

        self._pypi_ver.clear()
        self._pypi_ver.addItem(data["version"] + "  (latest)")
        for v in data["versions"]:
            if v != data["version"]:
                self._pypi_ver.addItem(v)

    def _install_from_pypi(self) -> None:
        name = self._pypi_env.currentText()
        row  = self._pypi_results.currentRow()
        pkg_item = self._pypi_results.item(row, 0)
        if not name or not pkg_item:
            QMessageBox.warning(self, "Select", "Select an environment and a package first.")
            return
        pkg = pkg_item.text()
        ver_text = self._pypi_ver.currentText().split()[0]
        spec = f"{pkg}=={ver_text}" if ver_text else pkg
        self._log_info(f"Installing {spec} into {name}…")
        self._run_task(vbe.install_package, name, pkg, ver_text)

    def _copy_pip_cmd(self) -> None:
        row = self._pypi_results.currentRow()
        item = self._pypi_results.item(row, 0)
        if not item: return
        pkg = item.text()
        ver = self._pypi_ver.currentText().split()[0]
        cmd = f"pip install {pkg}=={ver}" if ver else f"pip install {pkg}"
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(cmd)
        self._log_info(f"Copied: {cmd}")

    # ── Outdated tab ──────────────────────────────────────────────────────────

    def _check_outdated(self) -> None:
        name = self._out_env.currentText()
        if not name: return
        self._log_info(f"Checking outdated packages in {name}…")
        self._slot_outdated.run(
            vbe.get_outdated, name,
            on_done=self._on_outdated_loaded,
            on_error=lambda e: self._log_err(e),
        )

    def _on_outdated_loaded(self, pkgs: list) -> None:
        self._out_table.setRowCount(0)
        for p in pkgs:
            row = self._out_table.rowCount()
            self._out_table.insertRow(row)
            self._out_table.setItem(row, 0, QTableWidgetItem(p.get("name", "")))
            self._out_table.setItem(row, 1, QTableWidgetItem(p.get("version", "")))
            latest = p.get("latest_version", "")
            item = QTableWidgetItem(latest)
            item.setForeground(QColor(theme.GREEN))
            self._out_table.setItem(row, 2, item)
        msg = f"{len(pkgs)} outdated package(s)." if pkgs else "All packages up to date ✅"
        self._log_ok(msg)

    def _upgrade_all(self) -> None:
        name = self._out_env.currentText()
        if not name: return
        if QMessageBox.question(
            self, "Upgrade All", f"Upgrade all packages in '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self._run_task(vbe.upgrade_all, name)

    def _upgrade_selected_outdated(self) -> None:
        name = self._out_env.currentText()
        row  = self._out_table.currentRow()
        item = self._out_table.item(row, 0)
        if not name or not item: return
        self._run_task(vbe.upgrade_package, name, item.text())

    # ── Snapshots tab ─────────────────────────────────────────────────────────

    def _save_snapshot(self) -> None:
        name = self._snap_env.currentText() or self._selected_env_name()
        if not name: return
        ok, msg = vbe.save_snapshot(name)
        if ok:
            self._log_ok(msg); self._load_snapshots()
        else:
            self._log_err(msg)

    def _load_snapshots(self) -> None:
        name = self._snap_env.currentText()
        if not name: return
        snaps = vbe.list_snapshots(name)
        self._snap_list.setRowCount(0)
        for s in snaps:
            row = self._snap_list.rowCount()
            self._snap_list.insertRow(row)
            self._snap_list.setItem(row, 0, QTableWidgetItem(s.name))
            ts = s.name.replace(f"{name}_", "").replace(".json", "")
            self._snap_list.setItem(row, 1, QTableWidgetItem(ts))
        self._snap_detail.clear()

    def _on_snap_selected(self, row, *_) -> None:
        item = self._snap_list.item(row, 0)
        if not item: return
        snap_file = vbe.SNAPSHOTS_DIR / item.text()
        try:
            import json
            data = json.loads(snap_file.read_text())
            pkgs = data.get("packages", {})
            lines = [f"{n}=={v}" for n, v in sorted(pkgs.items())]
            self._snap_detail.setPlainText(
                f"Timestamp: {data.get('timestamp', '')}\n"
                f"Packages:  {len(pkgs)}\n\n" +
                "\n".join(lines)
            )
        except Exception as e:
            self._snap_detail.setPlainText(f"Error: {e}")

    def _export_snap(self) -> None:
        row = self._snap_list.currentRow()
        item = self._snap_list.item(row, 0)
        if not item: return
        fn, _ = QFileDialog.getSaveFileName(self, "Export requirements.txt", "", "Text (*.txt)")
        if not fn: return
        try:
            import json
            data = json.loads((vbe.SNAPSHOTS_DIR / item.text()).read_text())
            pkgs = data.get("packages", {})
            Path(fn).write_text("\n".join(f"{n}=={v}" for n, v in sorted(pkgs.items())))
            self._log_ok(f"Exported to {fn}")
        except Exception as e:
            self._log_err(str(e))

    # ── Env actions ───────────────────────────────────────────────────────────

    def _dlg_create(self) -> None:
        dlg = _CreateEnvDialog(self)
        if dlg.exec() == QDialog.Accepted:
            name, py_ver, template, project = dlg.values()
            self._log_info(f"Creating environment '{name}'…")
            self._run_task(vbe.create_env, name, py_ver or None, template or None, project)

    def _clone_env(self) -> None:
        name = self._selected_env_name()
        if not name: return
        dst, ok = QInputDialog.getText(self, "Clone Environment", "New environment name:")
        if ok and dst:
            self._run_task(vbe.clone_env, name, dst.strip())

    def _delete_env(self) -> None:
        name = self._selected_env_name()
        if not name: return
        if QMessageBox.question(
            self, "Delete", f"Permanently delete '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self._run_task(vbe.delete_env, name)

    def _wipe_env(self) -> None:
        name = self._selected_env_name()
        if not name: return
        if QMessageBox.question(
            self, "Wipe", f"Remove all packages from '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self._run_task(vbe.wipe_env, name)

    def _activate_env(self) -> None:
        name = self._selected_env_name()
        if not name: return
        env_path = Path(vbe.ENVS_DIR / name)
        if os.name == "nt":
            cmd = str(env_path / "Scripts" / "activate.bat")
        else:
            cmd = f"source {env_path / 'bin' / 'activate'}"
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(cmd)
        self._log_ok(f"Copied activate command to clipboard:\n  {cmd}")

    def _export_req(self) -> None:
        name = self._selected_env_name()
        if not name: return
        fn, _ = QFileDialog.getSaveFileName(self, "Export requirements.txt", f"{name}_requirements.txt", "Text (*.txt)")
        if fn:
            self._run_task(vbe.export_requirements, name, fn)

    # ── Tab change ────────────────────────────────────────────────────────────

    def _on_tab_change(self, idx: int) -> None:
        if idx == 0:
            self._reload_envs()
        elif idx == 1:
            self._load_packages()
        elif idx == 3:
            self._check_outdated()
        elif idx == 4:
            self._load_snapshots()

    # ── Generic task runner ───────────────────────────────────────────────────

    def _run_task(self, fn, *args) -> None:
        self._slot_task.run(
            fn, *args,
            on_done=self._on_task_done,
            on_error=lambda e: self._log_err(e),
        )

    def _on_task_done(self, result) -> None:
        if isinstance(result, tuple):
            ok, msg = result[0], result[1]
            if ok:
                self._log_ok(msg)
            else:
                self._log_err(msg)
        else:
            self._log_ok(str(result))
        self._reload_envs()

    # ── Logging helpers ───────────────────────────────────────────────────────

    def _log_info(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.insertHtml(f"<span style='color:{theme.CYAN}'>[{ts}] {msg}</span><br>")
        self._log.ensureCursorVisible()
        self._status(msg)

    def _log_ok(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.insertHtml(f"<span style='color:{theme.GREEN}'>[{ts}] ✅ {msg}</span><br>")
        self._log.ensureCursorVisible()
        self._status(msg)

    def _log_err(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.insertHtml(f"<span style='color:{theme.RED}'>[{ts}] ❌ {msg}</span><br>")
        self._log.ensureCursorVisible()
        self._status(f"Error: {msg}")


# ── Create Environment Dialog ─────────────────────────────────────────────────

class _CreateEnvDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Virtual Environment")
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        self._name    = QLineEdit(); self._name.setPlaceholderText("my_env")
        self._py_ver  = QLineEdit(); self._py_ver.setPlaceholderText("e.g. 3.11  (blank = default)")
        self._project = QLineEdit(); self._project.setPlaceholderText("project name (optional)")
        self._template = QComboBox()
        self._template.addItem("None")
        for t in vbe.TEMPLATES_DIR.glob("*.txt"):
            self._template.addItem(t.stem)

        layout.addRow("Name *:", self._name)
        layout.addRow("Python version:", self._py_ver)
        layout.addRow("Project:", self._project)
        layout.addRow("Template:", self._template)

        btns = QHBoxLayout()
        ok_btn = QPushButton("Create"); ok_btn.clicked.connect(self._validate)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        btns.addWidget(ok_btn); btns.addWidget(cancel)
        layout.addRow(btns)

    def _validate(self) -> None:
        import re
        name = self._name.text().strip()
        if not re.match(r"^[a-zA-Z0-9_]+$", name):
            QMessageBox.warning(self, "Invalid", "Name must be alphanumeric/underscore only.")
            return
        self.accept()

    def values(self) -> tuple[str, str, str, str]:
        tpl = self._template.currentText()
        return (
            self._name.text().strip(),
            self._py_ver.text().strip(),
            "" if tpl == "None" else tpl,
            self._project.text().strip() or "Unknown",
        )
