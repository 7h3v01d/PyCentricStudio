"""
pycentric.core.utils.threading
===============================
A safe, reusable wrapper for running callables on a background QThread.

Usage
-----
    task = BackgroundTask(my_fn, arg1, arg2)
    task.finished.connect(on_done)
    task.error.connect(on_error)
    task.start()
    ...
    task.cancel()   # best-effort; worker must check task.is_cancelled
"""

from __future__ import annotations
import traceback
from typing import Any, Callable

from PyQt5.QtCore import QObject, QThread, pyqtSignal


class _Worker(QObject):
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, fn: Callable, args: tuple, kwargs: dict, task: "BackgroundTask") -> None:
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs
        self._task   = task

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            if not self._task.is_cancelled:
                self.finished.emit(result)
        except Exception:
            if not self._task.is_cancelled:
                self.error.emit(traceback.format_exc())


class BackgroundTask(QObject):
    """Runs *fn* on a worker thread; emits finished(result) or error(traceback_str)."""

    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn      = fn
        self._args    = args
        self._kwargs  = kwargs
        self._thread  = QThread()
        self._worker  = _Worker(fn, args, kwargs, self)
        self._worker.moveToThread(self._thread)
        self._cancelled = False

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self._worker.finished.connect(self._cleanup)
        self._worker.error.connect(self._cleanup)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def is_running(self) -> bool:
        return self._thread.isRunning()

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True

    def _cleanup(self) -> None:
        self._thread.quit()
        self._thread.wait(2000)
