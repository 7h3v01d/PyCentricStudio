"""
pycentric.ui.components.explorer.git_panel
==========================================
A compact Git operations widget backed by GitService.
"""

from __future__ import annotations
from typing import Callable

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from pycentric.core.services.git import GitService
from pycentric.ui.common.theme import BG, FG_DIM


class GitPanel(QGroupBox):
    def __init__(self, get_root: Callable[[], str | None], parent=None) -> None:
        super().__init__("⎇  Git", parent)
        self._get_root = get_root
        self._service: GitService | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        btns = QHBoxLayout()
        for lbl, fn in [
            ("Status", self._status), ("Log", self._log),
            ("Diff",   self._diff),   ("Pull", self._pull),
        ]:
            b = QPushButton(lbl); b.setFixedHeight(24)
            b.clicked.connect(fn); btns.addWidget(b)
        layout.addLayout(btns)

        row2 = QHBoxLayout()
        self._msg = QLineEdit(); self._msg.setPlaceholderText("Commit message…")
        btn_stage  = QPushButton("Stage All"); btn_stage.setFixedHeight(24)
        btn_commit = QPushButton("Commit");    btn_commit.setFixedHeight(24)
        btn_stage.clicked.connect(self._stage_all)
        btn_commit.clicked.connect(self._commit)
        row2.addWidget(self._msg); row2.addWidget(btn_stage); row2.addWidget(btn_commit)
        layout.addLayout(row2)

        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setFont(QFont("Consolas", 9))
        self._out.setMaximumHeight(140)
        self._out.setStyleSheet(f"background: {BG}; border: none;")
        layout.addWidget(self._out)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _svc(self) -> GitService | None:
        root = self._get_root()
        if not root:
            self._out.appendPlainText("No project folder selected.")
            return None
        if self._service is None or str(self._service.root) != root:
            self._service = GitService(root)
        return self._service

    def _run(self, method_name: str, *args) -> None:
        svc = self._svc()
        if svc is None:
            return
        result = getattr(svc, method_name)(*args)
        self._out.appendPlainText(f"$ git {result.command.split('git ')[-1]}\n{result.output}\n")

    # ── slots ─────────────────────────────────────────────────────────────────

    def _status(self)    -> None: self._out.clear(); self._run("status")
    def _log(self)       -> None: self._out.clear(); self._run("log")
    def _diff(self)      -> None: self._out.clear(); self._run("diff")
    def _pull(self)      -> None: self._out.clear(); self._run("pull")
    def _stage_all(self) -> None: self._run("add_all"); self._out.appendPlainText("Staged all.")

    def _commit(self) -> None:
        msg = self._msg.text().strip()
        if not msg:
            self._out.appendPlainText("Enter a commit message."); return
        self._run("commit", msg)
        self._msg.clear()

    def refresh_root(self) -> None:
        """Call when the project root changes."""
        self._service = None
        self._out.clear()
