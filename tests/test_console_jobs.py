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
