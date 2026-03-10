"""
pycentric.__main__
==================
Entry point: ``python -m pycentric`` or the ``pycentric`` CLI script.
"""

import sys
from pycentric.application import create_app
from pycentric.mainwindow import MainWindow


def main() -> None:
    app = create_app(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
