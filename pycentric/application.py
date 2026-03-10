"""
pycentric.application
=====================
Creates and configures the QApplication instance.
"""

from __future__ import annotations
import sys

from PyQt5.QtWidgets import QApplication
from pycentric.ui.common import theme


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("PyCentric Studio")
    app.setOrganizationName("PyCentric")
    theme.apply(app)
    return app
