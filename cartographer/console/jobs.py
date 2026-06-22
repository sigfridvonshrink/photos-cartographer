"""Single-slot job runner for the console.

Runs one phase job at a time in a worker thread — matching the whole-run lock (never two at once) and
keeping the HTTP loop free to serve SSE. Phase ``run()`` functions call ``sys.exit(...)``; the runner
catches ``SystemExit`` (and anything else) so a finishing or crashing job never tears down the server.
It holds only transient status — the durable truth stays in the artifacts/journals.
"""

import ctypes
import threading
from typing import Callable, Optional

from ..reporting import get_reporter
from .. import photos_utils as U


def _async_raise(thread_ident: Optional[int], exc=KeyboardInterrupt) -> None:
    """Asynchronously raise ``exc`` in the thread with the given ident (the CPython
    ``PyThreadState_SetAsyncExc`` hook). On its own it only fires when that thread next runs Python
    bytecode; the caller pairs it with ``U.kill_active_children()`` so a thread blocked in a worker
    read returns immediately — together they unwind a running phase exactly like a terminal Ctrl-C
    (which every phase already handles: clean lock release, nothing partially applied)."""
    if not thread_ident:
        return
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread_ident), ctypes.py_object(exc))
    if res > 1:                       # somehow set in >1 thread -> undo, never leave it half-applied
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_ident), None)


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = False
        self._status = {"label": None, "state": "idle", "exit": None, "error": None}

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, label: str, target: Callable[[], None]) -> bool:
        """Start ``target`` (a zero-arg callable that does the work, may ``sys.exit``) as the single
        job. Returns False — without starting — if a job is already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._cancel = False
            self._status = {"label": label, "state": "running", "exit": None, "error": None}
            self._thread = threading.Thread(target=self._run, args=(label, target),
                                            name=f"job:{label}", daemon=True)
            self._thread.start()
            return True

    def cancel(self) -> bool:
        """Interrupt the running job like a terminal Ctrl-C. Returns False if nothing is running.
        Marks the run cancelled, async-raises KeyboardInterrupt in the worker thread, and force-kills
        the active worker children so a blocking read returns and the interrupt fires. The phase's own
        ``finally`` releases the workspace lock; the run is journalled/idempotent, so nothing is left
        partially applied."""
        with self._lock:
            t = self._thread
            if not (t is not None and t.is_alive()):
                return False
            self._cancel = True
            ident = t.ident
        _async_raise(ident, KeyboardInterrupt)
        U.kill_active_children()
        return True

    def _run(self, label: str, target: Callable[[], None]) -> None:
        try:
            target()
            self._finish(label, "done", exit_code=0)
        except SystemExit as e:
            # Phases turn Ctrl-C into sys.exit(130), so a cancelled run arrives here as SystemExit —
            # the cancel flag (not the code) is what distinguishes an interrupt from a real failure.
            code = e.code
            code = 0 if code is None else (code if isinstance(code, int) else 1)
            if self._cancel:
                self._finish(label, "cancelled", exit_code=code)
            else:
                self._finish(label, "done" if code == 0 else "failed", exit_code=code)
        except KeyboardInterrupt:
            self._finish(label, "cancelled", exit_code=130)
        except BaseException as e:        # never let a job kill the server
            if self._cancel:
                self._finish(label, "cancelled", error=str(e))
                return
            try:
                get_reporter().error(f"Console: {label} crashed: {e}")
            except Exception:
                pass
            self._finish(label, "failed", error=str(e))

    def _finish(self, label: str, state: str, exit_code=None, error=None) -> None:
        with self._lock:
            self._status = {"label": label, "state": state, "exit": exit_code, "error": error}
