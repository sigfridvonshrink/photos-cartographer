"""Unit tests for the event/sink reporting seam (cartographer/reporting.py)."""

import io

import pytest

from cartographer.reporting import (
    START, UPDATE, FINISH,
    LogEvent, ProgressEvent, SummaryEvent,
    CaptureSink, TtySink, Reporter,
    get_reporter, set_reporter, use_reporter,
)


# --- Reporter / event emission -------------------------------------------

def test_log_emits_logevent_with_routing():
    cap = CaptureSink()
    r = Reporter([cap])
    r.log("hello")
    r.warn("careful")
    r.error("boom", stream="stdout")
    logs = cap.logs()
    assert [(e.msg, e.level, e.stream) for e in logs] == [
        ("hello", "info", "stderr"),
        ("careful", "warn", "stderr"),
        ("boom", "error", "stdout"),
    ]


def test_track_emits_start_updates_and_ok_finish():
    cap = CaptureSink()
    r = Reporter([cap])
    out = list(r.track([10, 20, 30], "hashing", detail=lambda x: f"item-{x}"))
    assert out == [10, 20, 30]                      # iteration is transparent

    prog = cap.progress()
    assert prog[0].state == START
    assert prog[0].total == 3
    assert prog[-1].state == FINISH
    assert prog[-1].status == "ok"
    assert prog[-1].cur == 3                          # advanced once per item

    # Each item: a forced detail UPDATE before its work, then an advance UPDATE after.
    updates = [e for e in prog if e.state == UPDATE]
    assert updates[0].force is True and updates[0].detail == "item-10" and updates[0].cur == 0
    assert updates[1].force is False and updates[1].cur == 1


def test_progress_finish_is_aborted_on_exception_and_reraises():
    cap = CaptureSink()
    r = Reporter([cap])
    with pytest.raises(ValueError):
        with r.progress("work", total=5) as p:
            p.advance()
            raise ValueError("nope")
    finish = cap.progress()[-1]
    assert finish.state == FINISH
    assert finish.status == "aborted"
    assert finish.cur == 1                            # reports progress reached before abort


def test_track_total_inferred_none_for_lazy_iterable():
    cap = CaptureSink()
    r = Reporter([cap])
    list(r.track((x for x in range(3)), "scan"))      # generator has no len()
    assert cap.progress()[0].total is None


def test_emit_fans_out_to_all_sinks():
    a, b = CaptureSink(), CaptureSink()
    r = Reporter([a, b])
    r.log("x")
    list(r.track([1], "y"))
    assert len(a.events) == len(b.events) > 0
    assert [type(e) for e in a.events] == [type(e) for e in b.events]


def test_counters_feed_summary_event():
    cap = CaptureSink()
    r = Reporter([cap])
    r.count("hashes_computed", 3)
    r.count("hashes_computed")
    r.summary()
    summ = [e for e in cap.events if isinstance(e, SummaryEvent)][-1]
    assert summ.counters["hashes_computed"] == 4


# --- TtySink rendering (the byte-for-byte contract) -----------------------

class _FakeStream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def test_ttysink_plain_progress_format():
    stream = _FakeStream(tty=False)
    sink = TtySink(stream=stream, quiet=False)
    sink.handle(ProgressEvent("t1", "hashing", START, 0, 4))
    sink.handle(ProgressEvent("t1", "hashing", UPDATE, 2, 4, detail="foo.jpg", force=True))
    sink.handle(ProgressEvent("t1", "hashing", FINISH, 4, 4))
    text = stream.getvalue()
    assert "Starting hashing..." in text
    assert "hashing: 2/4 (50.0%) — foo.jpg ..." in text
    assert "Finished hashing in " in text


def test_ttysink_tty_uses_carriage_return_overwrite():
    stream = _FakeStream(tty=True)
    sink = TtySink(stream=stream, quiet=False)
    sink.handle(ProgressEvent("t1", "scan", UPDATE, 1, 0, force=True))   # total 0 -> no pct
    out = stream.getvalue()
    assert "\r\033[K" in out
    assert "scan: 1/0 ..." in out                     # 0 total renders as "1/0", no percent


def test_ttysink_quiet_suppresses_progress_but_not_report():
    stream = _FakeStream(tty=False)
    sink = TtySink(stream=stream, quiet=True)
    sink.handle(ProgressEvent("t1", "scan", START, 0, 3))
    assert stream.getvalue() == ""                    # progress silent when quiet
    # A structured report is a deliverable: prints (to stderr) even when quiet.
    sink.handle(SummaryEvent(report={"media_operations": 7}))
    # (rendered to sys.stderr, not our fake stream — just assert it did not raise and stayed silent here)
    assert stream.getvalue() == ""


def test_ttysink_log_routes_stdout_vs_stderr(capsys):
    sink = TtySink(stream=_FakeStream(tty=False), quiet=False)
    sink.handle(LogEvent("to-out", stream="stdout"))
    sink.handle(LogEvent("to-err", stream="stderr"))
    captured = capsys.readouterr()
    assert captured.out.strip() == "to-out"
    assert captured.err.strip() == "to-err"


# --- module-global active reporter ----------------------------------------

def test_get_reporter_lazily_creates_default():
    set_reporter(None)
    try:
        r = get_reporter()
        assert isinstance(r, Reporter)
        assert get_reporter() is r                     # stable
    finally:
        set_reporter(None)


def test_use_reporter_installs_and_restores():
    set_reporter(None)
    base = get_reporter()
    cap = CaptureSink()
    custom = Reporter([cap])
    with use_reporter(custom):
        assert get_reporter() is custom
        get_reporter().log("inside")
    assert get_reporter() is base
    assert any(isinstance(e, LogEvent) for e in cap.events)
    set_reporter(None)
