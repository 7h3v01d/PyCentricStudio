"""
pycentric.core.utils.threading
================================
Safe, reusable background task system for PyQt5.

Root cause of "QThread: Destroyed while thread is still running"
----------------------------------------------------------------
Python's GC destroys a BackgroundTask object as soon as the last Python
reference to it is dropped — even if the QThread is still running.
The fix is two-part:

  1. BackgroundTask keeps a strong reference to itself alive until the
     thread finishes, via _self_ref.  This prevents GC from collecting
     it mid-run.

  2. We do NOT call deleteLater() on QThread or _Worker from within
     BackgroundTask.  Those Qt calls tell Qt to delete the C++ object,
     but Python still holds self._thread / self._worker references
     that then point at freed memory.  Instead we let Python's normal
     reference counting handle cleanup once _self_ref is cleared.

Signal arity contract
---------------------
  finished(object)        — result of the callable
  error(str)              — short error message ONLY (one arg, simpler for callers)
  progress(int 0-100)     — optional progress updates

The full traceback is logged to stderr automatically; callers only need
to handle the human-readable one-line message.

Usage — simple
--------------
    task = BackgroundTask(my_fn, arg1, arg2)
    task.finished.connect(on_result)
    task.error.connect(lambda msg: show_error(msg))
    task.start()

Usage — with progress + cancellation (just declare the params)
--------------------------------------------------------------
    def long_fn(root, progress_cb, cancelled):
        for i, item in enumerate(items):
            if cancelled(): return None
            progress_cb(i * 100 // total)
        return "done"

    task = BackgroundTask(long_fn, root)
    task.progress.connect(progress_bar.setValue)
    task.error.connect(lambda m: status_bar.showMessage(m))
    task.start()

Usage — TaskSlot (at most one running at a time)
------------------------------------------------
    _SEARCH = TaskSlot("search")          # class or instance attribute
    ...
    _SEARCH.run(search_fn, root, query,
                on_done=self._on_done,
                on_error=lambda m: self._log(m))
"""

from __future__ import annotations
import inspect
import sys
import traceback as _tb
from typing import Any, Callable

from PyQt5.QtCore import QObject, QThread, pyqtSignal


# ── Worker (lives on the background thread) ───────────────────────────────────

class _Worker(QObject):
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)      # single-arg: short message
    progress = pyqtSignal(int)

    def __init__(
        self,
        fn: Callable,
        args: tuple,
        kwargs: dict,
        cancelled_flag: list,       # list[bool] — mutable shared flag
    ) -> None:
        super().__init__()
        self._fn        = fn
        self._args      = args
        self._kwargs    = kwargs
        self._cancelled = cancelled_flag

    def run(self) -> None:
        try:
            # Auto-inject progress_cb / cancelled when the function declares them
            sig   = inspect.signature(self._fn)
            extra: dict[str, Any] = {}
            if "progress_cb" in sig.parameters:
                extra["progress_cb"] = lambda v: self.progress.emit(int(v))
            if "cancelled" in sig.parameters:
                extra["cancelled"] = lambda: bool(self._cancelled[0])

            result = self._fn(*self._args, **{**self._kwargs, **extra})

            if not self._cancelled[0]:
                self.finished.emit(result)
        except Exception:
            if not self._cancelled[0]:
                full  = _tb.format_exc()
                short = full.strip().splitlines()[-1]
                print(full, file=sys.stderr)   # full traceback always to stderr
                self.error.emit(short)


# ── BackgroundTask ────────────────────────────────────────────────────────────

class BackgroundTask(QObject):
    """
    Run *fn* on a QThread.

    Signals
    -------
    finished(object)   — result value
    error(str)         — short one-line error message
    progress(int)      — 0-100 progress updates
    """

    finished = pyqtSignal(object)
    error    = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._cancelled_flag: list[bool] = [False]
        self._self_ref: "BackgroundTask | None" = None   # keeps self alive

        self._thread = QThread()
        self._worker = _Worker(fn, args, kwargs, self._cancelled_flag)
        self._worker.moveToThread(self._thread)

        # Worker signals → task signals (relay to caller)
        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self._worker.progress.connect(self.progress)

        # Thread lifecycle
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        # Release self-reference only AFTER thread has fully stopped.
        # QThread.finished fires on the main thread after quit()+wait().
        self._thread.finished.connect(self._release)

    # ── control ───────────────────────────────────────────────────────────────

    def start(self) -> "BackgroundTask":
        if not self._thread.isRunning():
            self._self_ref = self      # prevent GC until thread finishes
            self._thread.start()
        return self

    def cancel(self) -> None:
        """Best-effort cancel.  Worker checks cancelled() if it declared it."""
        self._cancelled_flag[0] = True
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)    # wait up to 2 s for clean exit

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @property
    def is_cancelled(self) -> bool:
        return bool(self._cancelled_flag[0])

    # ── internal cleanup ──────────────────────────────────────────────────────

    def _release(self) -> None:
        """Called on the main thread once QThread has finished.
        Clearing _self_ref allows Python to GC this object normally.
        _thread and _worker are also cleared so Qt objects are freed."""
        self._self_ref = None
        # Nullify references so Python ref-count drops to zero cleanly
        self._worker = None   # type: ignore[assignment]
        self._thread = None   # type: ignore[assignment]

    # ── chainable helpers ─────────────────────────────────────────────────────

    def on_done(self, slot: Callable) -> "BackgroundTask":
        self.finished.connect(slot); return self

    def on_error(self, slot: Callable) -> "BackgroundTask":
        self.error.connect(slot); return self

    def on_progress(self, slot: Callable) -> "BackgroundTask":
        self.progress.connect(slot); return self


# ── TaskSlot ──────────────────────────────────────────────────────────────────

class TaskSlot:
    """
    Ensures at most one BackgroundTask runs at a time for a named operation.
    Stores the task reference internally, solving the GC lifetime problem for
    fire-and-forget usages where the caller doesn't keep a reference.

    Usage
    -----
        _SEARCH = TaskSlot("search")   # attribute on the widget
        ...
        _SEARCH.run(fn, arg1, arg2,
                    on_done=self._on_done,
                    on_error=lambda m: self._status(m))
    """

    def __init__(self, name: str = "") -> None:
        self.name     = name
        self._current: BackgroundTask | None = None

    def run(
        self,
        fn: Callable,
        *args: Any,
        on_done:     Callable | None = None,
        on_error:    Callable | None = None,
        on_progress: Callable | None = None,
        **kwargs: Any,
    ) -> BackgroundTask:
        # Cancel previous task if still running
        if self._current and self._current.is_running():
            self._current.cancel()

        task = BackgroundTask(fn, *args, **kwargs)
        if on_done:     task.finished.connect(on_done)
        if on_error:    task.error.connect(on_error)
        if on_progress: task.progress.connect(on_progress)

        # Store reference so neither GC nor TaskSlot replacement kills it early
        self._current = task
        task.start()
        return task

    def cancel(self) -> None:
        if self._current:
            self._current.cancel()

    def is_running(self) -> bool:
        return bool(self._current and self._current.is_running())
