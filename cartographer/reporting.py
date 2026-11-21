"""Event/sink reporting seam (web-console design note, v1).

The pipeline's user-facing output is split into two planes:

- the **control/data plane** — unchanged direct calls/returns/exceptions; and
- this **observation plane** — a one-way status tap. Code emits structured *events*; *sinks*
  render them. Nobody reads events to make a decision: if every sink were removed the pipeline
  would run and produce byte-identical artifacts.

Two status channels (see the design note):

- **log** — discrete, ordered, append-only facts (``LogEvent``). Lossless.
- **progress** — one mutable value per task, latest-wins, high frequency (``ProgressEvent`` with a
  ``state`` lifecycle of start → update → finish). The terminal ``finish`` carries a ``status``
  (``ok``/``aborted``) — the explicit done signal (never inferred from ``cur == total``).

Producers go through a :class:`Reporter`: ``log()`` for scrolling messages, and the
``progress()`` context manager / ``track()`` iterator for the dynamic, overwriting kind — so each
tracked loop is one line and the render/throttle/done logic lives in exactly one place (the sink).

The active reporter is a **module-level global** reached via :func:`get_reporter`, deliberately *not*
a ``contextvars.ContextVar``: progress is incremented from worker threads (the prep threadpool) and
contextvars do not propagate into threads. A plain global is thread-shared, and is safe because the
whole-run lock serializes runs (one per process) — the same idiom the codebase uses for ``CONFIG``.

v1 ships :class:`TtySink` (the only default; it reproduces the former ``ProgressCoordinator``
rendering byte-for-byte) and :class:`CaptureSink` (in-memory, for tests / to prove fan-out). A
file/web sink is deferred to v2.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, List, Optional

# Progress lifecycle states.
START = "start"
UPDATE = "update"
FINISH = "finish"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@dataclass
class LogEvent:
    """A discrete, scrolling status line. Lossless; ordered."""
    msg: str
    level: str = "info"          # info | warn | error
    stream: str = "stderr"       # stdout | stderr — preserves each call site's routing


@dataclass
class ProgressEvent:
    """A snapshot of one progress task (latest-wins).

    ``state`` is the lifecycle marker: ``START`` (task begins), ``UPDATE`` (a tick), ``FINISH``
    (terminal). ``status`` is only meaningful at ``FINISH``. ``force`` requests an immediate render
    regardless of the sink's throttle (e.g. a detail change that should announce itself at once).
    """
    task_id: str
    label: str
    state: str = UPDATE
    cur: int = 0
    total: Optional[int] = None
    detail: str = ""
    force: bool = False
    status: str = "ok"           # ok | aborted (at FINISH)
    duration: Optional[float] = None   # seconds; stamped by Reporter.emit at FINISH (the one timer)

    @property
    def done(self) -> bool:
        return self.state == FINISH


def finished_line(label: str, duration: Optional[float], status: str = "ok") -> str:
    """The one rendering of a finished progress task: 'Finished <label> in <X>s'. Shared by the
    terminal sink (inline) and the web sink (a log line) so the wording/format lives in one place.
    A task its body left by an exception (``status="aborted"``) is said to have stopped, never
    'Finished' — the line is what the user reads as the task's outcome, and an interrupted or failed
    step did not finish (the run's exit status and records carry the rest)."""
    if status == "aborted":
        return f"Stopped {label} after {(duration or 0.0):.2f}s, unfinished"
    return f"Finished {label} in {(duration or 0.0):.2f}s"


def report_lines(r: dict, plan_summary: Optional[dict] = None, planned: bool = False) -> List[str]:
    """The prep run report (RUL-prep_run_summarised) as labelled lines: one rendering, printed by the terminal sink and
    logged by the web sink, so the console shows the summary the terminal prints. `planned` gives the report of a plan
    not yet executed: the same lines without those that tell what an execution applied and wrote."""
    pc = (plan_summary or {}).get("performance_and_cache", {}) or {}
    qf = r.get("quarantine_footprint", {}) or {}
    _qr = r.get("quarantined_by_reason") or {}
    lines = [
        "",
        "=== Prep plan summary ===" if planned else "=== Prep run summary ===",
        f"  Media operations {'planned         ' if planned else 'planned/executed'} : {r.get('media_operations', 0)}  "
        f"(cache ops: {r.get('cache_operations', 0)})",
        f"  No-op / already-correct           : {r.get('no_op_already_correct', 0)}",
        f"  Recognized moves (carried forward): {r.get('recognized_moves', 0)}",
        f"  By-dest files scanned read-only   : {r.get('by_dest_files_scanned_read_only', 0)}",
        f"  Duplicates -> quarantine          : {r.get('duplicates_against_mutable', 0)} vs mutable, "
        f"{r.get('duplicates_against_by_dest', 0)} vs by-dest",
        f"  Other files -> quarantine         : {_qr.get('exiftool_leftover', 0)} write leftover(s), "
        f"{_qr.get('dump_dotfile', 0)} hidden dump file(s), "
        f"{_qr.get('raw_culled', 0)} set-aside JPEG(s) of a culled RAW",
        f"  Metadata reused/extracted/carried/failed : "
        f"{r.get('metadata_reused', 0)}/{r.get('metadata_extracted', 0)}/"
        f"{r.get('metadata_carried_forward', 0)}/{r.get('metadata_failed', 0)}  "
        f"(extractor {r.get('extractor', '?')} {r.get('extractor_version', '?')}, "
        f"field-set v{r.get('field_set_version', '?')})",
        f"  Cache effects applied (upsert/remove): "
        f"{pc.get('db_upserts_applied', 0)}/{pc.get('db_removes_applied', 0)}",
        f"  Camera groups / native-GPS / missing-timestamp : "
        f"{r.get('camera_groups_found', 0)} / {r.get('native_gps_files', 0)} / "
        f"{r.get('missing_timestamp_files', 0)}",
        f"  Blockers / warnings               : {r.get('blockers', 0)} / {r.get('warnings', 0)}",
        f"  Dependency validation             : {pc.get('dependency_validation_status', 'n/a')}  "
        f"(handoff written after validation: {pc.get('handoff_written_after_successful_validation', False)})",
        f"  End-of-prep audit record          : prep-log {pc.get('prep_log_written', False)}, "
        f"DB snapshot {pc.get('prep_db_snapshot_written', False)}",
        f"  Quarantine footprint              : {qf.get('total_files', 0)} files, "
        f"{qf.get('total_bytes', 0)} bytes across {qf.get('plan_id_dirs', 0)} plan(s) "
        f"(never auto-deleted)",
        "========================",
    ]
    if planned:      # what only an execution applies and writes
        lines = [l for l in lines if not l.startswith(("  Cache effects applied", "  Dependency validation",
                                                         "  End-of-prep audit record"))]
    return lines


@dataclass
class ChangesEvent:
    """A command stopped on changes to the workspace that no command made (RUL-unexpected_change_stops): the list
    exactly as printed, the code that accepts it, and the command it was printed for — so a sink can offer the
    acceptance (the console's Accept button sends the same code through the same command). The terminal has the
    printed lines already and ignores it."""
    phase: str
    command: str
    code: str
    lines: List[str] = field(default_factory=list)


@dataclass
class SummaryEvent:
    """The end-of-run summary deliverable (rendered even when progress is quiet)."""
    report: Optional[dict] = None
    plan_summary: Optional[dict] = None
    counters: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------

class Sink:
    """Base sink. A sink renders/records events; it never feeds back into the pipeline."""

    def handle(self, event) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class CaptureSink(Sink):
    """In-memory sink: records every event. For tests and to prove multi-sink fan-out."""

    def __init__(self) -> None:
        self.events: List[object] = []
        self._lock = threading.Lock()

    def handle(self, event) -> None:
        with self._lock:
            self.events.append(event)

    # Convenience filters for assertions.
    def logs(self) -> List[LogEvent]:
        return [e for e in self.events if isinstance(e, LogEvent)]

    def progress(self) -> List[ProgressEvent]:
        return [e for e in self.events if isinstance(e, ProgressEvent)]


def event_to_dict(event) -> dict:
    """Serialize an event to a JSON-ready dict tagged with ``kind`` (for the web sink / SSE)."""
    if isinstance(event, LogEvent):
        return {"kind": "log", "msg": event.msg, "level": event.level, "stream": event.stream}
    if isinstance(event, ProgressEvent):
        return {"kind": "progress", "task_id": event.task_id, "label": event.label,
                "state": event.state, "cur": event.cur, "total": event.total,
                "detail": event.detail, "status": event.status, "duration": event.duration}
    if isinstance(event, SummaryEvent):
        return {"kind": "summary", "report": event.report, "plan_summary": event.plan_summary,
                "counters": event.counters}
    if isinstance(event, ChangesEvent):
        return {"kind": "changes", "phase": event.phase, "command": event.command, "code": event.code,
                "lines": list(event.lines)}
    return {"kind": "unknown"}


class WebSink(Sink):
    """Fans events to any number of SSE subscribers, and keeps just enough state for a client that
    connects mid-run to catch up: a bounded recent-log buffer (lossless within the window) plus the
    latest snapshot per live progress task (finished tasks are dropped). Status is ephemeral — this
    holds no durable truth (that's the artifacts/journals); a dropped event only costs a cosmetic
    update. Per-subscriber queues are bounded and **drop-oldest** so a slow browser can never stall
    the producer (the worker thread emitting events)."""

    def __init__(self, log_buffer: int = 500, queue_max: int = 2000) -> None:
        self._subs: set = set()
        self._lock = threading.Lock()
        self._log = deque(maxlen=log_buffer)   # recent LogEvent dicts, for late join
        self._progress: dict = {}              # task_id -> latest progress dict (live tasks only)
        self._changes = None                   # the last stop on unexpected changes, until the next run starts
        self._queue_max = queue_max

    def _fanout_locked(self, msg) -> None:
        """Push one event dict to every subscriber (caller holds ``self._lock``). Bounded, drop-oldest."""
        for q in self._subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                try:
                    q.get_nowait()      # drop oldest, then enqueue the newest
                    q.put_nowait(msg)
                except queue.Empty:
                    pass

    def handle(self, event) -> None:
        msg = event_to_dict(event)
        extra_logs = []
        with self._lock:
            if msg["kind"] == "log":
                self._log.append(msg)
            elif msg["kind"] == "changes":
                self._changes = msg
            elif msg["kind"] == "summary" and msg.get("report"):
                # The prep run report the terminal prints (RUL-prep_run_summarised), as log lines in the same
                # rendering — the console shows what the CLI shows, a late-joining page included.
                extra_logs = [{"kind": "log", "msg": line, "level": "info", "stream": "stderr"}
                              for line in report_lines(msg["report"], msg.get("plan_summary")) if line]
            elif msg["kind"] == "progress":
                tid = msg["task_id"]
                if msg["state"] == FINISH:
                    self._progress.pop(tid, None)
                    # Record what happened to each progress task as a durable log line — CLI parity:
                    # TtySink prints the same on finish; the console pane lacked it. The duration was
                    # already stamped by Reporter.emit (one timer), and the wording is shared.
                    extra_logs = [{"kind": "log", "msg": finished_line(msg["label"], msg.get("duration"),
                                                                       msg.get("status", "ok")),
                                   "level": "info", "stream": "stderr"}]
                else:
                    self._progress[tid] = msg
            self._fanout_locked(msg)
            for line in extra_logs:
                self._log.append(line)                # also visible in the late-join snapshot
                self._fanout_locked(line)

    def clear_progress(self) -> None:
        """Finish any still-open progress tasks: emit a synthetic FINISH for each live task (so
        subscribers drop the row) and forget it. A safety net the console calls when a run ends, so the
        progress area is always empty afterwards — regardless of whether a phase balanced every
        ``start_phase`` with a ``finish_phase`` or the run was interrupted. Log history is untouched."""
        with self._lock:
            for msg in list(self._progress.values()):
                self._fanout_locked({**msg, "state": FINISH, "status": "ok"})
            self._progress.clear()

    def clear_changes(self) -> None:
        """Forget the last stop on unexpected changes — the console calls it as a run starts, so the list (and its
        Accept button) is offered only for the run that printed it."""
        with self._lock:
            self._changes = None

    def subscribe(self):
        """Register a subscriber. Returns ``(q, snapshot)`` — a fresh queue of future events and the
        catch-up snapshot (recent log + live progress) to render before draining the queue."""
        q: "queue.Queue" = queue.Queue(maxsize=self._queue_max)
        with self._lock:
            self._subs.add(q)
            snapshot = {"log": list(self._log), "progress": list(self._progress.values()), "changes": self._changes}
        return q, snapshot

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._subs.discard(q)

    def snapshot(self) -> dict:
        with self._lock:
            return {"log": list(self._log), "progress": list(self._progress.values()), "changes": self._changes}


class TtySink(Sink):
    """Terminal renderer. Reproduces the former ``ProgressCoordinator`` output exactly.

    On a TTY, progress overwrites a single line with ``\\r\\033[K``; piped, it prints throttled full
    lines. ``quiet`` defaults to "not a TTY" (so redirected output is silent) and can be forced.
    """

    def __init__(self, stream=None, quiet: Optional[bool] = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.is_tty = self.stream.isatty()
        if quiet is None:
            self.quiet = not self.is_tty
        else:
            self.quiet = quiet
            if quiet:
                self.is_tty = False
        self._lock = threading.Lock()
        self._last_print: dict = {}

    def handle(self, event) -> None:
        if isinstance(event, LogEvent):
            self._log(event)
        elif isinstance(event, ProgressEvent):
            self._progress(event)
        elif isinstance(event, SummaryEvent):
            self._summary(event)

    # -- log --------------------------------------------------------------
    def _log(self, e: LogEvent) -> None:
        out = sys.stdout if e.stream == "stdout" else sys.stderr
        print(e.msg, file=out)

    # -- progress ---------------------------------------------------------
    def _progress(self, e: ProgressEvent) -> None:
        if self.quiet:
            return
        with self._lock:
            if e.state == START:
                self._last_print[e.task_id] = 0.0
                if self.is_tty:
                    print(f"\r\033[KStarting {e.label}...", end="", file=self.stream)
                else:
                    print(f"Starting {e.label}...", file=self.stream)
            elif e.state == UPDATE:
                now = time.time()
                last = self._last_print.get(e.task_id, 0.0)
                threshold = 0.1 if self.is_tty else 10.0
                if e.force or now - last > threshold:
                    self._last_print[e.task_id] = now
                    pct = f" ({e.cur / e.total * 100:.1f}%)" if e.total else ""
                    suffix = f" — {e.detail}" if e.detail else ""
                    total = e.total or 0
                    if self.is_tty:
                        print(f"\r\033[K{e.label}: {e.cur}/{total}{pct}{suffix} ...",
                              end="", file=self.stream)
                        self.stream.flush()
                    else:
                        print(f"{e.label}: {e.cur}/{total}{pct}{suffix} ...", file=self.stream)
            elif e.state == FINISH:
                self._last_print.pop(e.task_id, None)
                line = finished_line(e.label, e.duration, e.status)   # duration stamped by Reporter.emit
                if self.is_tty:
                    print(f"\r\033[K{line}", file=self.stream)
                else:
                    print(line, file=self.stream)

    # -- summary ----------------------------------------------------------
    def _summary(self, e: SummaryEvent) -> None:
        # The run summary is a deliverable, so it prints even when live progress is quiet.
        if e.report:
            self._print_report(e.report, e.plan_summary)
            return
        if self.quiet:
            return
        print("\n--- Performance Summary ---", file=sys.stderr)
        if e.plan_summary and "performance_and_cache" in e.plan_summary:
            pc = e.plan_summary["performance_and_cache"]
            fields = [
                "progress_mode", "worker_crashes", "worker_restarts",
                "metadata_extracted", "metadata_reused", "metadata_failed",
                "hashes_computed", "hashes_reused", "hashes_failed",
                "db_effects_seen", "db_upserts_applied", "db_removes_applied",
                "dependency_validation_status", "handoff_written_after_successful_validation",
            ]
            for f in fields:
                default = 0 if any(s in f for s in (
                    "applied", "failed", "crashes", "reused", "computed",
                    "restarts", "seen", "extracted")) else False
                print(f"  {f}: {pc.get(f, default)}", file=sys.stderr)
        else:
            for k, v in sorted(e.counters.items()):
                print(f"  {k}: {v}", file=sys.stderr)
        print("---------------------------", file=sys.stderr)

    def _print_report(self, r, plan_summary=None) -> None:
        """Render the prep run report (RUL-prep_run_summarised) as labelled categories."""
        for line in report_lines(r, plan_summary):
            print(line, file=sys.stderr)


# ---------------------------------------------------------------------------
# Reporter — the producer-facing seam
# ---------------------------------------------------------------------------

class ProgressTask:
    """Handle for one progress task, yielded by :meth:`Reporter.progress`."""

    def __init__(self, reporter: "Reporter", task_id: str, label: str, total: Optional[int]) -> None:
        self._r = reporter
        self.task_id = task_id
        self.label = label
        self.total = total
        self.cur = 0
        self.detail = ""

    def advance(self, n: int = 1) -> None:
        self.cur += n
        self._r.emit(ProgressEvent(self.task_id, self.label, UPDATE, self.cur, self.total,
                                   self.detail, force=False))

    def set_detail(self, detail: str = "") -> None:
        """Set the per-item label and render it immediately (forced), so a long single item
        announces itself before its work begins."""
        self.detail = detail or ""
        self._r.emit(ProgressEvent(self.task_id, self.label, UPDATE, self.cur, self.total,
                                   self.detail, force=True))


class Reporter:
    """Fans events out to its sinks. One per run.

    ``emit`` is a synchronous broadcast — every sink sees every event (fast sinks render inline; the
    queue/thread-boundary handoff is the future web sink's concern, not this layer's).
    """

    def __init__(self, sinks: Optional[Iterable[Sink]] = None) -> None:
        self.sinks: List[Sink] = list(sinks) if sinks is not None else [TtySink()]
        self.counters: dict = {}
        self._lock = threading.Lock()
        self._task_seq = 0
        self._task_start: dict = {}   # task_id -> START time; the single source of finish durations

    # -- fan-out ----------------------------------------------------------
    def emit(self, event) -> None:
        # Time each progress task here, once, so every sink renders the SAME duration without each
        # tracking start times itself. START records the clock; FINISH stamps elapsed onto the event.
        if isinstance(event, ProgressEvent):
            if event.state == START:
                with self._lock:
                    self._task_start[event.task_id] = time.time()
            elif event.state == FINISH and event.duration is None:
                with self._lock:
                    t0 = self._task_start.pop(event.task_id, None)
                if t0 is not None:
                    event.duration = time.time() - t0
        for sink in self.sinks:
            sink.handle(event)

    # -- log channel ------------------------------------------------------
    def log(self, msg: str, level: str = "info", stream: str = "stderr") -> None:
        self.emit(LogEvent(msg, level, stream))

    def warn(self, msg: str, stream: str = "stderr") -> None:
        self.log(msg, level="warn", stream=stream)

    def error(self, msg: str, stream: str = "stderr") -> None:
        self.log(msg, level="error", stream=stream)

    # -- counters (data for the summary, not rendered) --------------------
    def count(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def summary(self, report: Optional[dict] = None, plan_summary: Optional[dict] = None) -> None:
        self.emit(SummaryEvent(report=report, plan_summary=plan_summary,
                               counters=dict(self.counters)))

    # -- progress channel -------------------------------------------------
    def _next_task_id(self) -> str:
        with self._lock:
            self._task_seq += 1
            return f"t{self._task_seq}"

    @contextmanager
    def progress(self, label: str, total: Optional[int] = None) -> Iterator[ProgressTask]:
        """Track one progress task. Emits ``START`` on entry and a terminal ``FINISH`` on exit —
        ``status="aborted"`` if the body raises, else ``status="ok"``. The explicit done signal is
        emitted at *every* site for free, so no caller has to remember it."""
        task_id = self._next_task_id()
        self.emit(ProgressEvent(task_id, label, START, 0, total))
        task = ProgressTask(self, task_id, label, total)
        try:
            yield task
        except BaseException:
            self.emit(ProgressEvent(task_id, label, FINISH, task.cur, total, task.detail,
                                    status="aborted"))
            raise
        else:
            self.emit(ProgressEvent(task_id, label, FINISH, task.cur, total, task.detail,
                                    status="ok"))

    def track(self, iterable: Iterable, label: str, total: Optional[int] = None,
              detail: Optional[Callable[[object], str]] = None) -> Iterator:
        """Iterate ``iterable``, ticking once per item (the common case; sugar over
        :meth:`progress`). ``detail(item)`` — if given — sets the per-item label before the item's
        work, matching the prior ``set_detail``-then-``increment`` ordering."""
        if total is None:
            try:
                total = len(iterable)  # type: ignore[arg-type]
            except TypeError:
                total = None
        with self.progress(label, total) as p:
            for item in iterable:
                if detail is not None:
                    p.set_detail(detail(item))
                yield item
                p.advance()


# ---------------------------------------------------------------------------
# Module-global active reporter (thread-shared; see module docstring)
# ---------------------------------------------------------------------------

_REPORTER: Optional[Reporter] = None
_GLOBAL_LOCK = threading.Lock()


def get_reporter() -> Reporter:
    """Return the active reporter, lazily creating a default TTY reporter if none is installed."""
    global _REPORTER
    if _REPORTER is None:
        with _GLOBAL_LOCK:
            if _REPORTER is None:
                _REPORTER = Reporter([TtySink()])
    return _REPORTER


_NEXT_STEPS_MUTED = 0     # >0 while one phase runs another's commands: only the outer one says what to do next


def emit_next_step(reporter, text: str) -> None:
    """Print the closing 'what to do next' guidance — the last line of a phase command, so the operator
    is never left guessing the next move. A single uniform `Next: …` line, on stdout, shared by the CLI
    and the console (both drive the same phase `run()`). Nothing while :func:`next_steps_muted` holds."""
    if _NEXT_STEPS_MUTED:
        return
    reporter.log(f"\nNext: {text}", stream="stdout")


@contextmanager
def next_steps_muted() -> Iterator[None]:
    """Hold back every `Next: …` line printed inside — for a phase running another's commands as a step of its
    own (geotag plan running prep's plan and execute), whose own `Next:` is the one that applies. A global like
    the reporter, for the same reason: the whole-run lock serializes runs."""
    global _NEXT_STEPS_MUTED
    _NEXT_STEPS_MUTED += 1
    try:
        yield
    finally:
        _NEXT_STEPS_MUTED -= 1


def set_reporter(reporter: Optional[Reporter]) -> Optional[Reporter]:
    """Install ``reporter`` as the active one; return the previous one (for restore)."""
    global _REPORTER
    previous = _REPORTER
    _REPORTER = reporter
    return previous


@contextmanager
def use_reporter(reporter: Reporter) -> Iterator[Reporter]:
    """Temporarily install ``reporter`` (restored on exit). Mainly for tests."""
    previous = set_reporter(reporter)
    try:
        yield reporter
    finally:
        set_reporter(previous)
