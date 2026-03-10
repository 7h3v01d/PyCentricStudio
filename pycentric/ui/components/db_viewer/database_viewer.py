"""
pycentric.ui.components.db_viewer.database_viewer
=================================================
SQLite database browser panel.
"""

from __future__ import annotations
import csv
import datetime
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtSql import QSqlDatabase, QSqlQuery, QSqlTableModel
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QShortcut, QSplitter, QTableView,
    QToolBar, QVBoxLayout, QWidget,
)

from pycentric.core.types import Language
from pycentric.ui.common import theme
from pycentric.ui.components.editor.highlighter import UniversalHighlighter


class _AddRowDialog(QDialog):
    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Row")
        layout = QFormLayout(self)
        self._inputs: list[tuple[str, QLineEdit]] = []
        for col in range(model.columnCount()):
            hdr = str(model.headerData(col, Qt.Horizontal))
            w = QLineEdit()
            self._inputs.append((hdr, w))
            layout.addRow(hdr, w)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> dict[str, str]:
        return {h: w.text() for h, w in self._inputs}


class DatabaseViewerPanel(QWidget):
    def __init__(self, status_fn=None, parent=None) -> None:
        super().__init__(parent)
        self._status = status_fn or (lambda msg: None)
        self._db: QSqlDatabase | None = None
        self._model: QSqlTableModel | None = None
        self._conn_name = f"pycentric_db_{id(self)}"
        self._build_ui()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # toolbar
        tb = QToolBar(); tb.setMovable(False)
        for lbl, fn in [
            ("📂 Open DB",    self.open_db),
            ("➕ New Table",  self.create_table),
            ("🗑 Drop Table", self.drop_table),
            ("➕ Add Row",    self.add_row),
            ("➕ Add Col",    self.add_column),
            ("➖ Del Col",    self.del_column),
            ("💾 Export CSV", self.export_csv),
            ("🔄 Refresh",    self._refresh_tables),
        ]:
            b = QPushButton(lbl); b.setFixedHeight(26); b.clicked.connect(fn); tb.addWidget(b)
        layout.addWidget(tb)

        splitter = QSplitter(Qt.Horizontal)

        # ── left sidebar ──
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(4,4,4,4)
        ll.addWidget(QLabel("Tables"))
        self._tbl_list = QListWidget()
        self._tbl_list.currentTextChanged.connect(self._load_table)
        ll.addWidget(self._tbl_list)
        ll.addWidget(QLabel("Schema"))
        self._schema = QPlainTextEdit(); self._schema.setReadOnly(True)
        self._schema.setFont(theme.mono_font(9)); self._schema.setMaximumHeight(180)
        ll.addWidget(self._schema)
        left.setMaximumWidth(240)
        splitter.addWidget(left)

        # ── right ──
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(4,4,4,4)

        # SQL console
        qbox = QGroupBox("SQL Console")
        qbl = QVBoxLayout(qbox)
        self._query_in = QPlainTextEdit()
        self._query_in.setPlaceholderText("SELECT * FROM table  — Ctrl+Enter to run")
        self._query_in.setFont(theme.mono_font())
        self._query_in.setMaximumHeight(110)
        self._query_hl = UniversalHighlighter(self._query_in.document(), Language.SQL)
        QShortcut(QKeySequence("Ctrl+Return"), self._query_in).activated.connect(self.run_query)

        btn_run = QPushButton("▶ Run (Ctrl+Enter)"); btn_run.clicked.connect(self.run_query)
        self._hist = QListWidget(); self._hist.setMaximumHeight(70)
        self._hist.itemDoubleClicked.connect(
            lambda it: self._query_in.setPlainText(it.data(Qt.UserRole)))
        qbl.addWidget(self._query_in); qbl.addWidget(btn_run)
        qbl.addWidget(QLabel("History (double-click to restore):")); qbl.addWidget(self._hist)
        rl.addWidget(qbox)

        # table selector + view
        self._combo = QComboBox()
        self._combo.currentTextChanged.connect(self._load_table)
        rl.addWidget(self._combo)

        self._table_view = QTableView()
        self._table_view.setAlternatingRowColors(True)
        self._table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        rl.addWidget(self._table_view, 1)

        splitter.addWidget(right)
        splitter.setSizes([220, 900])
        layout.addWidget(splitter, 1)

    # ── db helpers ────────────────────────────────────────────────────────────

    def _q(self) -> QSqlQuery:
        return QSqlQuery(self._db)

    def _exec(self, sql: str) -> QSqlQuery:
        q = self._q(); q.exec(sql); return q

    def _require_db(self) -> bool:
        if self._db and self._db.isOpen():
            return True
        QMessageBox.warning(self, "No Database", "Open a database file first.")
        return False

    # ── public actions ────────────────────────────────────────────────────────

    def open_db(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(
            self, "Open SQLite DB", "",
            "SQLite (*.db *.sqlite *.sqlite3);;All (*)",
        )
        if not fn: return
        if self._db and self._db.isOpen():
            self._db.close(); QSqlDatabase.removeDatabase(self._conn_name)
        self._db = QSqlDatabase.addDatabase("QSQLITE", self._conn_name)
        self._db.setDatabaseName(fn)
        if not self._db.open():
            QMessageBox.critical(self, "Error", "Could not open database."); return
        self._refresh_tables()
        self._status(f"DB: {fn}")

    def _refresh_tables(self) -> None:
        if not self._db: return
        tables = self._db.tables()
        self._tbl_list.clear(); self._tbl_list.addItems(tables)
        self._combo.blockSignals(True)
        self._combo.clear(); self._combo.addItems(tables)
        self._combo.blockSignals(False)
        if tables: self._load_table(tables[0])

    def _load_table(self, name: str) -> None:
        if not name or not self._db: return
        self._model = QSqlTableModel(self, self._db)
        self._model.setTable(name)
        self._model.setEditStrategy(QSqlTableModel.OnFieldChange)
        self._model.select()
        self._table_view.setModel(self._model)
        self._table_view.resizeColumnsToContents()

        # schema sidebar
        q = self._exec(f"PRAGMA table_info({name})")
        rows = []
        while q.next():
            nn = "NOT NULL" if q.value("notnull") else ""
            pk = "PK" if q.value("pk") else ""
            rows.append(f"  {q.value('name')}  {q.value('type')}  {nn}  {pk}".strip())
        self._schema.setPlainText(f"Table: {name}\n" + "\n".join(rows))
        self._status(f"Table: {name}  ({self._model.rowCount()} rows)")

    def run_query(self) -> None:
        if not self._require_db(): return
        sql = self._query_in.toPlainText().strip()
        if not sql: return
        q = QSqlQuery(self._db)
        if q.exec(sql):
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            it = QListWidgetItem(f"{ts}  {sql[:60]}")
            it.setData(Qt.UserRole, sql)
            self._hist.insertItem(0, it)
            if sql.strip().upper().startswith("SELECT"):
                self._model = QSqlTableModel(self, self._db)
                self._model.setQuery(q)
                self._table_view.setModel(self._model)
                self._table_view.resizeColumnsToContents()
            else:
                self._db.commit(); self._refresh_tables()
            self._status("Query OK")
        else:
            QMessageBox.critical(self, "SQL Error", q.lastError().text())

    def create_table(self) -> None:
        if not self._require_db(): return
        name, ok = QInputDialog.getText(self, "New Table", "Table name:")
        if ok and name:
            q = self._q()
            if q.exec(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT)"):
                self._db.commit(); self._refresh_tables()
            else:
                QMessageBox.critical(self, "Error", q.lastError().text())

    def drop_table(self) -> None:
        if not self._require_db(): return
        name = self._combo.currentText()
        if not name: return
        if QMessageBox.question(self, "Drop", f"Drop '{name}'?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        q = self._q()
        if q.exec(f"DROP TABLE {name}"):
            self._db.commit(); self._refresh_tables()
        else:
            QMessageBox.critical(self, "Error", q.lastError().text())

    def add_row(self) -> None:
        if not self._model: return
        dlg = _AddRowDialog(self._model, self)
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.values()
            row = self._model.rowCount()
            self._model.insertRows(row, 1)
            for col, (hdr, _) in enumerate(dlg._inputs):
                self._model.setData(self._model.index(row, col), vals[hdr])
            if not self._model.submitAll():
                QMessageBox.critical(self, "Error", self._model.lastError().text())
            else:
                self._db.commit()

    def add_column(self) -> None:
        if not self._require_db() or not self._combo.currentText(): return
        name, ok = QInputDialog.getText(self, "Add Column", "Column name:")
        if ok and name:
            tbl = self._combo.currentText()
            q = self._q()
            if q.exec(f"ALTER TABLE {tbl} ADD COLUMN {name} TEXT"):
                self._db.commit(); self._load_table(tbl)
            else:
                QMessageBox.critical(self, "Error", q.lastError().text())

    def del_column(self) -> None:
        if not self._model: return
        tbl = self._combo.currentText()
        cols = [str(self._model.headerData(i, Qt.Horizontal))
                for i in range(self._model.columnCount())]
        col, ok = QInputDialog.getItem(self, "Delete Column", "Column:", cols, 0, False)
        if not ok: return
        if QMessageBox.question(self, "Confirm", f"Delete column '{col}'?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        # SQLite: recreate table without the column
        q = self._q(); q.exec(f"PRAGMA table_info({tbl})")
        keep = []
        while q.next():
            if q.value("name") != col:
                keep.append((q.value("name"), q.value("type")))
        tmp = f"{tbl}_pycentric_tmp"
        defs     = ", ".join(f"{n} {t}" for n, t in keep)
        col_list = ", ".join(n for n, _ in keep)
        for sql in [
            f"CREATE TABLE {tmp} ({defs})",
            f"INSERT INTO {tmp} ({col_list}) SELECT {col_list} FROM {tbl}",
            f"DROP TABLE {tbl}",
            f"ALTER TABLE {tmp} RENAME TO {tbl}",
        ]:
            self._exec(sql)
        self._db.commit(); self._load_table(tbl)

    def export_csv(self) -> None:
        if not self._model: return
        fn, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        if not fn: return
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([str(self._model.headerData(i, Qt.Horizontal))
                            for i in range(self._model.columnCount())])
                for row in range(self._model.rowCount()):
                    w.writerow([str(self._model.data(self._model.index(row, col)) or "")
                                for col in range(self._model.columnCount())])
            self._status(f"Exported: {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def closeEvent(self, e) -> None:
        if self._db and self._db.isOpen():
            self._db.close()
        QSqlDatabase.removeDatabase(self._conn_name)
        e.accept()
