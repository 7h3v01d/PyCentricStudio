"""
pycentric.ui.components.import_mapper.import_mapper_panel
==========================================================
Import Mapper panel — visualise Python import dependencies.

Tabs
----
① Tree      — sortable flat table of every module with all metrics
② Analytics — KPI cards + sortable full metrics table
③ Graph     — pyvis interactive force-directed graph  (requires pyvis)
④ Arch      — architectural layer view HTML            (built-in, no extra deps)
⑤ Report    — Markdown summary (copy / export)

Integration points
------------------
  panel.set_project_root(path: str)   — called by MainWindow when Explorer opens a project
  panel.rescan()                       — public slot, also wired to F5
  panel.status_message  (signal str)  — emitted on every state change

Thread model
------------
Scan runs in BackgroundTask (TaskSlot), never blocks the UI thread.
pyvis graph building also runs in a TaskSlot — it can be slow on big projects.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QAction, QCheckBox, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from pycentric.core.services.import_scanner import (
    ImportScanner,
    build_architecture_html,
    build_interactive_graph,
    build_markdown_report,
    clear_cache,
    export_dot,
)
from pycentric.core.utils.threading import TaskSlot
from pycentric.ui.common import theme

# Optional: pyvis and QtWebEngine
try:
    import pyvis  # noqa: F401
    _PYVIS_OK = True
except ImportError:
    _PYVIS_OK = False

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE_OK = True
except ImportError:
    _WEBENGINE_OK = False


# ── tiny helpers ─────────────────────────────────────────────────────────────

def _btn(label: str, handler, tip: str = "", color: str = "") -> QPushButton:
    b = QPushButton(label)
    b.clicked.connect(handler)
    if tip:
        b.setToolTip(tip)
    if color:
        b.setStyleSheet(f"background:{color}; color:white; font-weight:bold;")
    return b


def _cell(text: str, numeric_val=None) -> QTableWidgetItem:
    """Create a QTableWidgetItem that sorts numerically when a value is given."""
    it = QTableWidgetItem()
    if numeric_val is not None:
        it.setData(Qt.UserRole, numeric_val)          # sort key
        it.setText(str(text))
    else:
        it.setText(str(text))
    return it


def _health_color(score: int) -> str:
    if score >= 75:
        return theme.GREEN
    if score >= 50:
        return "#f39c12"
    return theme.RED


def _webview_or_placeholder(message: str) -> QWidget:
    """Return a live QWebEngineView or a labelled placeholder if unavailable."""
    if _WEBENGINE_OK:
        return QWebEngineView()
    lbl = QLabel(message)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(f"color:{theme.FG_DIM}; font-size:11pt; padding:40px;")
    return lbl


# ── Filter bar ───────────────────────────────────────────────────────────────

class _FilterBar(QGroupBox):
    """Search + fan-in threshold + checkboxes, emits changed() on any edit."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Filters", parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search module…")
        self._search.setMaximumWidth(220)
        self._search.textChanged.connect(self.changed)

        self._min_fi = QSpinBox()
        self._min_fi.setRange(0, 999)
        self._min_fi.setPrefix("Fan-in ≥ ")
        self._min_fi.setMaximumWidth(130)
        self._min_fi.valueChanged.connect(self.changed)

        self._hide_tests = QCheckBox("Hide tests")
        self._hide_tests.setChecked(True)
        self._hide_tests.stateChanged.connect(self.changed)

        self._hide_ext = QCheckBox("Hide externals")
        self._hide_ext.setChecked(False)
        self._hide_ext.stateChanged.connect(self.changed)

        self._cluster = QCheckBox("Cluster by pkg")
        self._cluster.setChecked(True)
        self._cluster.stateChanged.connect(self.changed)

        reset = _btn("Reset", self._reset, "Reset all filters to defaults")

        for w in (self._search, self._min_fi, self._hide_tests,
                  self._hide_ext, self._cluster, reset):
            row.addWidget(w)
        row.addStretch()

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def search(self) -> str:
        return self._search.text().strip()

    @property
    def min_fan_in(self) -> int:
        return self._min_fi.value()

    @property
    def hide_tests(self) -> bool:
        return self._hide_tests.isChecked()

    @property
    def show_external(self) -> bool:
        return not self._hide_ext.isChecked()

    @property
    def cluster(self) -> bool:
        return self._cluster.isChecked()

    def _reset(self) -> None:
        self._search.setText("")
        self._min_fi.setValue(0)
        self._hide_tests.setChecked(True)
        self._hide_ext.setChecked(False)
        self._cluster.setChecked(True)


# ── KPI card ─────────────────────────────────────────────────────────────────

class _KpiCard(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(120)
        self.setStyleSheet(
            f"background:{theme.BG3}; border-radius:7px; "
            f"border:1px solid {theme.BORDER};"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self._val = QLabel("—")
        self._val.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self._val.setStyleSheet(f"color:{theme.CYAN}; border:none;")
        self._lbl = QLabel(label.upper())
        self._lbl.setStyleSheet(
            f"color:{theme.FG_DIM}; font-size:8pt; "
            "letter-spacing:0.08em; border:none;"
        )
        lay.addWidget(self._val)
        lay.addWidget(self._lbl)

    def set_value(self, text: str, color: str = "") -> None:
        self._val.setText(text)
        if color:
            self._val.setStyleSheet(f"color:{color}; border:none;")
        else:
            self._val.setStyleSheet(f"color:{theme.CYAN}; border:none;")


# ── Analytics tab ─────────────────────────────────────────────────────────────

_ANALYTICS_COLS = [
    "Module", "Type", "LOC", "Classes", "Funcs",
    "Complexity", "Fan-in", "Fan-out", "Instability", "Health", "Cycle?",
]


class _AnalyticsTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        # KPI row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(6)
        self._kpis: dict[str, _KpiCard] = {}
        for lbl in ("Modules", "LOC", "Layers", "Cycles",
                    "Health", "Violations", "Orphans"):
            c = _KpiCard(lbl)
            self._kpis[lbl] = c
            kpi_row.addWidget(c)
        kpi_row.addStretch()
        lay.addLayout(kpi_row)

        # Full table
        self._tbl = QTableWidget()
        self._tbl.setColumnCount(len(_ANALYTICS_COLS))
        self._tbl.setHorizontalHeaderLabels(_ANALYTICS_COLS)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setSortingEnabled(True)
        self._tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self._tbl.setStyleSheet(
            "QTableWidget::item { padding: 3px 6px; }"
        )
        lay.addWidget(self._tbl)

    def refresh(self, scanner: ImportScanner) -> None:
        s = scanner.project_stats()
        h = s.get("avg_health", 0)
        hc = _health_color(int(h))

        self._kpis["Modules"].set_value(str(s.get("total_modules", 0)))
        self._kpis["LOC"].set_value(f"{s.get('total_loc', 0):,}")
        self._kpis["Layers"].set_value(str(len(s.get("layers", []))))
        self._kpis["Cycles"].set_value(
            str(s.get("total_cycles", 0)),
            theme.RED if s.get("total_cycles", 0) else theme.GREEN,
        )
        self._kpis["Health"].set_value(f"{h}/100", hc)
        nv = len(s.get("arch_violations", []))
        self._kpis["Violations"].set_value(
            str(nv), "#f39c12" if nv else theme.GREEN
        )
        self._kpis["Orphans"].set_value(
            str(len(s.get("orphan_modules", []))), theme.FG_DIM
        )

        self._tbl.setSortingEnabled(False)
        self._tbl.setRowCount(len(scanner.module_info))
        for row, (fqn, d) in enumerate(sorted(scanner.module_info.items())):
            health = d.get("health_score", 0)
            self._tbl.setItem(row, 0, _cell(fqn))
            self._tbl.setItem(row, 1, _cell(d.get("module_type", "general")))
            self._tbl.setItem(row, 2, _cell(d.get("loc", 0), d.get("loc", 0)))
            self._tbl.setItem(row, 3, _cell(d.get("num_classes", 0), d.get("num_classes", 0)))
            self._tbl.setItem(row, 4, _cell(d.get("num_functions", 0), d.get("num_functions", 0)))
            self._tbl.setItem(row, 5, _cell(d.get("complexity", 0), d.get("complexity", 0)))
            self._tbl.setItem(row, 6, _cell(d.get("fan_in", 0), d.get("fan_in", 0)))
            self._tbl.setItem(row, 7, _cell(d.get("fan_out", 0), d.get("fan_out", 0)))
            self._tbl.setItem(row, 8, _cell(f"{d.get('instability', 0.0):.2f}", d.get("instability", 0.0)))
            h_item = _cell(health, health)
            h_item.setForeground(QColor(_health_color(health)))
            h_item.setToolTip("\n".join(d.get("health_breakdown", [])))
            self._tbl.setItem(row, 9, h_item)
            cyc_item = _cell("⚠ Yes" if d.get("in_cycle") else "✓ No")
            if d.get("in_cycle"):
                cyc_item.setForeground(QColor(theme.RED))
            self._tbl.setItem(row, 10, cyc_item)
        self._tbl.setSortingEnabled(True)


# ── Tree tab ──────────────────────────────────────────────────────────────────

_TREE_COLS = [
    "Module", "Type", "Fan-in", "Fan-out",
    "Health", "LOC", "Complexity", "All Imports",
]


class _TreeTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self._tbl = QTableWidget()
        self._tbl.setColumnCount(len(_TREE_COLS))
        self._tbl.setHorizontalHeaderLabels(_TREE_COLS)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setSortingEnabled(True)
        self._tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self._tbl.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.Stretch
        )
        self._tbl.setStyleSheet(
            "QTableWidget::item { padding: 3px 6px; }"
        )
        lay.addWidget(self._tbl)

    def refresh(
        self,
        scanner: ImportScanner,
        search: str = "",
        min_fi: int = 0,
        hide_tests: bool = True,
    ) -> None:
        cycles_flat = {m for c in scanner.find_cycles() for m in c}

        rows = []
        for mod, d in scanner.module_info.items():
            if hide_tests and d.get("is_test"):
                continue
            if search and search.lower() not in mod.lower():
                continue
            if d.get("fan_in", 0) < min_fi and min_fi > 0:
                continue
            # Skip empty __init__
            if (mod.endswith(".__init__") or mod == "__init__") and not d.get("imports"):
                continue
            rows.append((mod, d))

        self._tbl.setSortingEnabled(False)
        self._tbl.setRowCount(len(rows))
        for row, (mod, d) in enumerate(sorted(rows, key=lambda x: x[0])):
            health     = d.get("health_score", 0)
            all_imps   = ", ".join(
                d.get("internal_imports", []) + d.get("external_imports", [])
            ) or "—"
            in_cycle   = mod in cycles_flat

            self._tbl.setItem(row, 0, _cell(mod))
            self._tbl.setItem(row, 1, _cell(d.get("module_type", "general")))
            self._tbl.setItem(row, 2, _cell(d.get("fan_in", 0), d.get("fan_in", 0)))
            self._tbl.setItem(row, 3, _cell(d.get("fan_out", 0), d.get("fan_out", 0)))
            h_item = _cell(health, health)
            h_item.setForeground(QColor(_health_color(health)))
            h_item.setToolTip("\n".join(d.get("health_breakdown", [])))
            self._tbl.setItem(row, 4, h_item)
            self._tbl.setItem(row, 5, _cell(d.get("loc", 0), d.get("loc", 0)))
            self._tbl.setItem(row, 6, _cell(d.get("complexity", 0), d.get("complexity", 0)))
            self._tbl.setItem(row, 7, _cell(all_imps))

            # Highlight cycle rows
            if in_cycle:
                for col in range(self._tbl.columnCount()):
                    it = self._tbl.item(row, col)
                    if it:
                        it.setBackground(QColor("#3d1515"))
                name_it = self._tbl.item(row, 0)
                if name_it:
                    name_it.setForeground(QColor(theme.RED))

        self._tbl.setSortingEnabled(True)


# ── Issues tab ────────────────────────────────────────────────────────────────

class _IssuesTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(10)

        self._cycles_lbl = QLabel("🔄 Circular Dependencies")
        self._cycles_lbl.setStyleSheet(f"color:{theme.CYAN}; font-weight:bold; font-size:10pt;")
        lay.addWidget(self._cycles_lbl)
        self._cycles = QPlainTextEdit()
        self._cycles.setReadOnly(True)
        self._cycles.setFont(QFont("Consolas", 9))
        self._cycles.setMaximumHeight(160)
        self._cycles.setStyleSheet(
            f"background:{theme.BG2}; color:{theme.RED}; border:1px solid {theme.BORDER};"
        )
        lay.addWidget(self._cycles)

        self._viol_lbl = QLabel("⚡ Architecture Layer Violations")
        self._viol_lbl.setStyleSheet(f"color:{theme.CYAN}; font-weight:bold; font-size:10pt;")
        lay.addWidget(self._viol_lbl)
        self._violations = QPlainTextEdit()
        self._violations.setReadOnly(True)
        self._violations.setFont(QFont("Consolas", 9))
        self._violations.setMaximumHeight(160)
        self._violations.setStyleSheet(
            f"background:{theme.BG2}; color:#f39c12; border:1px solid {theme.BORDER};"
        )
        lay.addWidget(self._violations)

        self._orphan_lbl = QLabel("🏝 Orphan Modules (no imports in or out)")
        self._orphan_lbl.setStyleSheet(f"color:{theme.CYAN}; font-weight:bold; font-size:10pt;")
        lay.addWidget(self._orphan_lbl)
        self._orphans = QPlainTextEdit()
        self._orphans.setReadOnly(True)
        self._orphans.setFont(QFont("Consolas", 9))
        self._orphans.setMaximumHeight(120)
        self._orphans.setStyleSheet(
            f"background:{theme.BG2}; color:{theme.FG_DIM}; border:1px solid {theme.BORDER};"
        )
        lay.addWidget(self._orphans)
        lay.addStretch()

    def refresh(self, scanner: ImportScanner) -> None:
        s = scanner.project_stats()

        cycles = s.get("cycles", [])
        if cycles:
            self._cycles_lbl.setText(f"🔄 Circular Dependencies ({len(cycles)} groups)")
            self._cycles.setPlainText(
                "\n".join("  →  ".join(c) for c in cycles)
            )
        else:
            self._cycles_lbl.setText("🔄 Circular Dependencies")
            self._cycles.setPlainText("✅ None detected")

        viols = s.get("arch_violations", [])
        if viols:
            self._viol_lbl.setText(f"⚡ Architecture Layer Violations ({len(viols)})")
            self._violations.setPlainText(
                "\n".join(
                    f"{src} (layer {sl})  →  {dst} (layer {dl})"
                    for src, dst, sl, dl in viols
                )
            )
        else:
            self._viol_lbl.setText("⚡ Architecture Layer Violations")
            self._violations.setPlainText("✅ None detected")

        orphans = s.get("orphan_modules", [])
        if orphans:
            self._orphan_lbl.setText(f"🏝 Orphan Modules ({len(orphans)})")
            self._orphans.setPlainText("\n".join(orphans))
        else:
            self._orphan_lbl.setText("🏝 Orphan Modules")
            self._orphans.setPlainText("✅ None")


# ── Main panel ────────────────────────────────────────────────────────────────

class ImportMapperPanel(QWidget):
    """
    Top-level widget registered as the ⑥ tab in MainWindow.

    Call set_project_root(path) whenever the explorer opens a project.
    The panel triggers an incremental re-scan automatically.
    """

    status_message = pyqtSignal(str)

    def __init__(self, status_fn=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status   = status_fn or (lambda m: None)
        self._scanner  = ImportScanner()
        self._slot_scan  = TaskSlot("im_scan")
        self._slot_graph = TaskSlot("im_graph")
        self._tmpdir   = Path(tempfile.mkdtemp(prefix="pycentric_im_"))
        self._build_ui()
        self._show_idle()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── toolbar ──
        tb = QToolBar()
        tb.setMovable(False)
        tb.setStyleSheet(
            f"QToolBar {{ background:{theme.BG2}; border-bottom:1px solid {theme.BORDER}; "
            f"padding:3px; spacing:4px; }}"
        )

        self._scan_btn = tb.addAction("⟳  Scan")
        self._scan_btn.setToolTip("Scan / re-scan the current project  (F5)")
        self._scan_btn.setShortcut("F5")
        self._scan_btn.triggered.connect(self.rescan)

        tb.addSeparator()

        act_arch = tb.addAction("Export Arch HTML")
        act_arch.triggered.connect(self._export_arch)

        act_graph = tb.addAction("Export Graph HTML")
        act_graph.triggered.connect(self._export_graph)

        act_md = tb.addAction("Export Markdown")
        act_md.triggered.connect(self._export_md)

        act_json = tb.addAction("Export JSON")
        act_json.triggered.connect(self._export_json)

        act_dot = tb.addAction("Export DOT")
        act_dot.triggered.connect(self._export_dot)

        tb.addSeparator()

        act_clear = tb.addAction("Clear Cache")
        act_clear.setToolTip("Delete the incremental scan cache — next scan will be full")
        act_clear.triggered.connect(self._clear_cache)

        root.addWidget(tb)

        # ── filter bar ──
        self._filters = _FilterBar()
        self._filters.changed.connect(self._on_filter_changed)
        root.addWidget(self._filters)

        # ── status strip ──
        self._status_lbl = QLabel("  No project loaded")
        self._status_lbl.setStyleSheet(
            f"background:{theme.BG3}; color:{theme.FG_DIM}; "
            f"padding:3px 8px; border-bottom:1px solid {theme.BORDER}; font-size:8pt;"
        )
        root.addWidget(self._status_lbl)

        # ── inner tabs ──
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs)

        # Tab ① — Tree
        self._tree_tab = _TreeTab()
        self._tabs.addTab(self._tree_tab, "📋  Tree")

        # Tab ② — Analytics (KPI + table)
        self._analytics_tab = _AnalyticsTab()
        self._tabs.addTab(self._analytics_tab, "📊  Analytics")

        # Tab ③ — Issues (cycles / violations / orphans)
        self._issues_tab = _IssuesTab()
        self._tabs.addTab(self._issues_tab, "⚠  Issues")

        # Tab ④ — Interactive graph (pyvis)
        if _WEBENGINE_OK:
            self._graph_view = QWebEngineView()
            self._tabs.addTab(self._graph_view, "🕸  Graph")
        else:
            placeholder = QLabel(
                "QtWebEngine not installed.\n\n"
                "pip install PyQtWebEngine\n\n"
                "Use Export Graph HTML to view in your browser."
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f"color:{theme.FG_DIM}; font-size:11pt; padding:40px;"
            )
            self._graph_view = None
            self._tabs.addTab(placeholder, "🕸  Graph")

        # Tab ⑤ — Architecture layer view
        if _WEBENGINE_OK:
            self._arch_view = QWebEngineView()
            self._tabs.addTab(self._arch_view, "🏗  Architecture")
        else:
            placeholder = QLabel(
                "QtWebEngine not installed.\n\n"
                "pip install PyQtWebEngine\n\n"
                "Use Export Arch HTML to view in your browser."
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f"color:{theme.FG_DIM}; font-size:11pt; padding:40px;"
            )
            self._arch_view = None
            self._tabs.addTab(placeholder, "🏗  Architecture")

        # Tab ⑥ — Markdown report
        self._report = QPlainTextEdit()
        self._report.setReadOnly(True)
        self._report.setFont(QFont("Consolas", 10))
        self._report.setStyleSheet(
            f"background:{theme.BG2}; color:{theme.FG}; border:none;"
        )
        self._tabs.addTab(self._report, "📝  Report")

    # ── public slots ──────────────────────────────────────────────────────────

    def set_project_root(self, path: str) -> None:
        """Called by MainWindow whenever Explorer opens a new project."""
        if not path:
            return
        p = Path(path)
        if not p.is_dir():
            return
        if self._scanner.project_root == p:
            return          # same project — do nothing (user can F5 manually)
        self._scanner.project_root = p
        self.rescan()

    def rescan(self) -> None:
        """Launch (or re-launch) a background scan of the current project."""
        if not self._scanner.project_root:
            self._show_idle()
            return

        root = self._scanner.project_root
        self._set_strip(f"  ⟳  Scanning {root.name} …")
        self._status(f"ImportMapper: scanning {root.name}…")

        def _do_scan(cancelled=None):
            self._scanner.scan(cancelled=cancelled)

        self._slot_scan.run(
            _do_scan,
        ).on_done(
            lambda _: self._on_scan_done()
        ).on_error(
            lambda e: self._on_error(e)
        )

    # ── scan callbacks ────────────────────────────────────────────────────────

    def _on_scan_done(self) -> None:
        s  = self._scanner.project_stats()
        pn = self._scanner.project_root.name
        msg = (
            f"  ✓  {pn}  ·  {s.get('total_modules', 0)} modules  ·  "
            f"{s.get('total_loc', 0):,} LOC  ·  "
            f"{s.get('total_cycles', 0)} cycles  ·  "
            f"health {s.get('avg_health', 0)}/100"
        )
        self._set_strip(msg)
        self._status(f"ImportMapper: {pn} scanned")
        self._refresh_all()

    def _on_error(self, msg: str) -> None:
        self._set_strip(f"  ✗  Error: {msg}")
        self._status(f"ImportMapper error: {msg}")

    # ── filter ────────────────────────────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        if not self._scanner.module_info:
            return
        f = self._filters
        self._tree_tab.refresh(
            self._scanner, f.search, f.min_fan_in, f.hide_tests
        )
        # Re-render graph with new filters (background — can be slow)
        if self._graph_view is not None and _PYVIS_OK:
            self._rebuild_graph()

    # ── refresh ───────────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        f = self._filters
        self._tree_tab.refresh(self._scanner, f.search, f.min_fan_in, f.hide_tests)
        self._analytics_tab.refresh(self._scanner)
        self._issues_tab.refresh(self._scanner)
        self._refresh_arch()
        self._report.setPlainText(build_markdown_report(self._scanner))
        if _PYVIS_OK and self._graph_view is not None:
            self._rebuild_graph()
        elif self._graph_view is None and not _PYVIS_OK:
            # Already showing placeholder
            pass

    def _refresh_arch(self) -> None:
        if self._arch_view is None:
            return
        try:
            html = build_architecture_html(self._scanner)
            arch_path = self._tmpdir / "arch.html"
            arch_path.write_text(html, encoding="utf-8")
            from PyQt5.QtCore import QUrl
            self._arch_view.load(QUrl.fromLocalFile(str(arch_path)))
        except Exception as exc:
            self._set_strip(f"  Architecture view error: {exc}")

    def _rebuild_graph(self) -> None:
        """Build pyvis graph in a background thread — it touches the filesystem."""
        if self._graph_view is None or not _PYVIS_OK:
            return
        f = self._filters
        graph_path = str(self._tmpdir / "graph.html")

        def _do_graph():
            build_interactive_graph(
                self._scanner, graph_path,
                show_external=f.show_external,
                search_filter=f.search,
                min_fan_in=f.min_fan_in,
                hide_tests=f.hide_tests,
                cluster_packages=f.cluster,
            )
            return graph_path

        self._slot_graph.run(_do_graph).on_done(
            lambda path: self._load_graph(path)
        ).on_error(
            lambda e: self._set_strip(f"  Graph error: {e}")
        )

    def _load_graph(self, path: str) -> None:
        if self._graph_view is None:
            return
        from PyQt5.QtCore import QUrl
        self._graph_view.load(QUrl.fromLocalFile(path))

    # ── exports ───────────────────────────────────────────────────────────────

    def _export_arch(self) -> None:
        if not self._scanner.module_info:
            self._warn_no_scan()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Architecture HTML", "", "HTML (*.html)"
        )
        if path:
            Path(path).write_text(
                build_architecture_html(self._scanner), encoding="utf-8"
            )
            self._status(f"Arch HTML → {path}")

    def _export_graph(self) -> None:
        if not self._scanner.module_info:
            self._warn_no_scan()
            return
        if not _PYVIS_OK:
            QMessageBox.information(
                self, "pyvis not installed",
                "Install pyvis to export the interactive graph:\n\n"
                "    pip install pyvis",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Graph HTML", "", "HTML (*.html)"
        )
        if path:
            f = self._filters
            build_interactive_graph(
                self._scanner, path,
                show_external=f.show_external,
                search_filter=f.search,
                min_fan_in=f.min_fan_in,
                hide_tests=f.hide_tests,
                cluster_packages=f.cluster,
            )
            self._status(f"Graph HTML → {path}")

    def _export_md(self) -> None:
        if not self._scanner.module_info:
            self._warn_no_scan()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Markdown Report", "", "Markdown (*.md)"
        )
        if path:
            Path(path).write_text(
                build_markdown_report(self._scanner), encoding="utf-8"
            )
            self._status(f"Markdown → {path}")

    def _export_json(self) -> None:
        if not self._scanner.module_info:
            self._warn_no_scan()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON Report", "", "JSON (*.json)"
        )
        if path:
            s    = self._scanner.project_stats()
            data = {
                "project": str(self._scanner.project_root),
                "modules": self._scanner.module_info,
                "cycles": self._scanner.find_cycles(),
                "stats": {
                    k: v for k, v in s.items()
                    if k not in ("most_imported", "most_complex", "layers", "layer_map")
                },
            }
            Path(path).write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
            self._status(f"JSON → {path}")

    def _export_dot(self) -> None:
        if not self._scanner.module_info:
            self._warn_no_scan()
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save DOT Graph", "",
            "PNG (*.png);;SVG (*.svg);;DOT source (*.dot)",
        )
        if not path:
            return
        dot = export_dot(self._scanner)
        if path.endswith(".dot"):
            Path(path).write_text(dot, encoding="utf-8")
            self._status(f"DOT → {path}")
        else:
            fmt = "svg" if path.endswith(".svg") else "png"
            if shutil.which("dot"):
                import subprocess
                try:
                    subprocess.run(
                        ["dot", f"-T{fmt}", "-o", path],
                        input=dot.encode(), check=True, capture_output=True,
                    )
                    self._status(f"Graphviz {fmt.upper()} → {path}")
                    return
                except Exception:
                    pass
            # Fallback: save .dot source
            dot_path = Path(path).with_suffix(".dot")
            dot_path.write_text(dot, encoding="utf-8")
            QMessageBox.warning(
                self, "Graphviz not found",
                "Install Graphviz and ensure 'dot' is on PATH for PNG/SVG export.\n\n"
                f"DOT source saved instead:\n{dot_path}",
            )

    def _clear_cache(self) -> None:
        clear_cache()
        self._status("ImportMapper: scan cache cleared — next scan will be full")
        self._set_strip("  Cache cleared  ·  next scan will be full")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _show_idle(self) -> None:
        self._set_strip("  No project loaded  ·  open a project in Explorer")

    def _set_strip(self, msg: str) -> None:
        self._status_lbl.setText(msg)

    def _warn_no_scan(self) -> None:
        QMessageBox.information(
            self, "No data",
            "Scan a project first  (⟳ Scan button or F5).",
        )
