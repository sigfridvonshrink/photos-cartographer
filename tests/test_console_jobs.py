"""Unit tests for the console JobRunner (single-slot, SystemExit-safe)."""

import sys
import time

from cartographer.console.jobs import JobRunner


def _wait(runner, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if not runner.running:
            return runner.status()
        time.sleep(0.005)
    raise AssertionError(f"job did not finish: {runner.status()}")


def test_runs_target_to_done():
    r = JobRunner()
    seen = []
    assert r.start("prep:plan", lambda: seen.append("ran")) is True
    st = _wait(r)
    assert seen == ["ran"]
    assert st["state"] == "done" and st["exit"] == 0


def test_systemexit_zero_is_done_nonzero_is_failed():
    r = JobRunner()
    r.start("ok", lambda: sys.exit(0))
    assert _wait(r)["state"] == "done"

    r2 = JobRunner()
    r2.start("blocked", lambda: sys.exit(2))
    st = _wait(r2)
    assert st["state"] == "failed" and st["exit"] == 2


def test_exception_marks_failed_and_keeps_runner_alive():
    r = JobRunner()
    def boom():
        raise RuntimeError("kaboom")
    r.start("crash", boom)            # must NOT raise into the caller / server
    st = _wait(r)
    assert st["state"] == "failed" and "kaboom" in (st["error"] or "")
    # runner is reusable after a crash
    assert r.start("again", lambda: None) is True
    assert _wait(r)["state"] == "done"


def test_single_slot_rejects_concurrent_start():
    r = JobRunner()
    release = []
    def slow():
        while not release:
            time.sleep(0.005)
    assert r.start("first", slow) is True
    assert r.running is True
    assert r.start("second", lambda: None) is False   # rejected while one is in flight
    release.append(1)
    _wait(r)


def test_cancel_is_noop_when_idle():
    r = JobRunner()
    assert r.cancel() is False                         # nothing running -> nothing to interrupt


def test_cancel_interrupts_a_running_job_via_keyboardinterrupt():
    # A job that does NOT special-case Ctrl-C surfaces the interrupt as KeyboardInterrupt.
    r = JobRunner()
    import threading
    started = threading.Event()
    def loop():
        started.set()
        while True:
            time.sleep(0.02)
    assert r.start("prep plan", loop) is True
    assert started.wait(2)
    assert r.cancel() is True
    st = _wait(r)
    assert st["state"] == "cancelled"


def test_cancel_marks_cancelled_even_when_phase_exits_130():
    # Real phases catch KeyboardInterrupt and sys.exit(130); the cancel flag (not the code) is what
    # tells the runner it was an interrupt rather than a genuine failure.
    r = JobRunner()
    import threading
    started = threading.Event()
    def phase_like():
        started.set()
        try:
            while True:
                time.sleep(0.02)
        except KeyboardInterrupt:
            sys.exit(130)
    assert r.start("geotag execute", phase_like) is True
    assert started.wait(2)
    assert r.cancel() is True
    st = _wait(r)
    assert st["state"] == "cancelled" and st["exit"] == 130
    # an UNcancelled sys.exit(130) is still a failure (not mislabelled cancelled)
    r2 = JobRunner()
    r2.start("x", lambda: sys.exit(130))
    assert _wait(r2)["state"] == "failed"
