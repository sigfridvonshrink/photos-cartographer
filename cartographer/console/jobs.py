"""Single-slot job runner for the console.

Runs one phase job at a time in a worker thread — matching the whole-run lock (never two at once) and
keeping the HTTP loop free to serve SSE. Phase ``run()`` functions call ``sys.exit(...)``; the runner
catches ``SystemExit`` (and anything else) so a finishing or crashing job never tears down the server.
It holds only transient status — the durable truth stays in the artifacts/journals.
"""

import threading
from typing import Callable, Optional

from ..reporting import get_reporter


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
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
            self._status = {"label": label, "state": "running", "exit": None, "error": None}
            self._thread = threading.Thread(target=self._run, args=(label, target),
                                            name=f"job:{label}", daemon=True)
            self._thread.start()
            return True

    def _run(self, label: str, target: Callable[[], None]) -> None:
        try:
            target()
            self._finish(label, "done", exit_code=0)
        except SystemExit as e:
            code = e.code
            code = 0 if code is None else (code if isinstance(code, int) else 1)
            self._finish(label, "done" if code == 0 else "failed", exit_code=code)
        except BaseException as e:        # never let a job kill the server
            try:
                get_reporter().error(f"Console: {label} crashed: {e}")
            except Exception:
                pass
            self._finish(label, "failed", error=str(e))

    def _finish(self, label: str, state: str, exit_code=None, error=None) -> None:
        with self._lock:
            self._status = {"label": label, "state": state, "exit": exit_code, "error": error}
