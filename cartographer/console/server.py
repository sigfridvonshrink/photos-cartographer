"""Operational console server (web-console design, v2.1).

A local web server that drives the SAME plan/validate/execute core the CLI drives — it only triggers
phase runs (in-process, single-slot via JobRunner) and streams their status to the browser over SSE
(via WebSink). One mutation path: every action calls the phase's own ``run()``; the web layer never
re-implements a move/plan. Operates on the cwd workspace, like every other phase.

Scope: all three phases' plan / dry-run / monitoring + every ``execute`` behind the explicit 2-step
confirm gate (``_execute_guard`` / ``_plan_summary``), the folded-in decision editor, and — for full
CLI parity (v2.5) — geotag ``finalize`` (non-destructive package bundling, a plain run) and prep
``prune-quarantine`` (the sole op a sealed workspace permits; its destructive ``--yes`` delete is gated
by ``_prune_guard``). Every phase command is now driveable from the console.

Static assets are package data (``cartographer/console/web``) read via importlib.resources, so they
resolve identically from a checkout and from inside the zipapp. The shared design system
(``tokens.css`` + vendored fonts) is reused from ``cartographer/editor/web`` — one copy.
"""

import argparse
import errno
import importlib.resources as _res
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import photos_utils as U
from ..editor import server as _editor
from ..reporting import Reporter, WebSink, set_reporter
from .jobs import JobRunner

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png",
}

# (phase, command) pairs the console may trigger. Non-mutating planning/validation for all three
# phases; every phase's `execute` is mutating and goes through the explicit 2-step gate
# (_execute_guard) — never a one-click run. The set now covers ALL CLI commands (v2.5 — full parity):
# geotag `finalize` (non-destructive package bundling, a plain run) and prep `prune-quarantine` (the
# sole op allowed on a sealed workspace; its destructive --yes delete is gated by _prune_guard).
_RUNNABLE = {
    ("prep", "plan"), ("prep", "dry-run"), ("prep", "execute"), ("prep", "prune-quarantine"),
    ("geotag", "plan"), ("geotag", "execute"), ("geotag", "finalize"),
    ("merge", "init-library"), ("merge", "plan"), ("merge", "dry-run"), ("merge", "execute"),
}

WEB = WebSink()
JOBS = JobRunner()


def _read_pkg(pkg, subdir, parts):
    if not parts or any(p in ("", ".", "..") for p in parts):
        return None
    try:
        t = _res.files(pkg).joinpath(subdir, *parts)
        return t.read_bytes() if t.is_file() else None
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None


def _asset(rel):
    """Bytes for a web asset. Shared design tokens + fonts come from the editor package (one copy);
    everything else from the console package. None if missing / path-escaping (-> 404)."""
    rel = (rel or "").lstrip("/") or "index.html"
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if rel == "tokens.css" or rel.startswith("vendor/"):
        return _read_pkg("cartographer.editor", "web", parts)
    return _read_pkg("cartographer.console", "web", parts)


def _bind(host, port, handler):
    for p in range(port, port + 64):
        try:
            return ThreadingHTTPServer((host, p), handler)
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
    raise OSError(errno.EADDRINUSE, f"no free port in {port}..{port + 63}")


def _phase_module(phase):
    if phase == "prep":
        from .. import photos_1_prep as m
        return m
    if phase == "geotag":
        from .. import photos_2_geotag as m
        return m
    if phase == "merge":
        from .. import photos_3_merge as m
        return m
    return None


def _make_target(phase, command, extra=None, pre=None):
    """Build the zero-arg job callable for (phase, command [, extra argv]): parse the phase's own argv
    so defaults match the CLI exactly, then call its run(). `pre` carries phase-level options that must
    precede the subcommand (e.g. ['-j', '8'] — `-j` lives on the parent parser, so it is rejected after
    the command); `extra` carries the subcommand's own positionals/flags (e.g. the optional library path
    for merge init-library). run() reads cwd as the workspace and may sys.exit() (JobRunner catches)."""
    mod = _phase_module(phase)
    parser = argparse.ArgumentParser()
    mod.add_arguments(parser)
    args = parser.parse_args([*(pre or []), command, *(extra or [])])

    def target():
        try:
            mod.run(args)
        finally:
            # Whatever happened (success, sys.exit, exception, interrupt), leave the progress area
            # empty: finish any progress task the phase left open. The log history stays.
            WEB.clear_progress()
    return target


def _read_plan(path):
    if not os.path.exists(path):
        return None, {"exists": False}
    try:
        with open(path) as f:
            return json.load(f), None
    except (OSError, ValueError) as e:
        return None, {"exists": True, "error": f"could not read plan: {e}", "blockers": ["unreadable plan"]}


def _json_status(path):
    """The `status` field of a JSON artifact, or None if absent/unreadable — a cheap visible-state read."""
    try:
        with open(path) as f:
            return (json.load(f) or {}).get("status")
    except (OSError, ValueError):
        return None


def _current_fingerprints(workspace):
    """Current values for the CHEAP artifact-dep freshness check (`plan_dependencies_fresh`). The
    costly geotag GPX fingerprint is deliberately omitted — that's the phase's deep check, run at
    execute. Keys match what the phases record in `depends_on`."""
    fps = {
        "folders_fingerprint": U.folders_fingerprint(),
        "media_extensions_fingerprint": U.media_extensions_fingerprint(),
    }
    try:
        fps["config_fingerprint"] = U.sha256_file(U.config_path(workspace))
    except OSError:
        pass
    try:
        fps["filename_format_fingerprint"] = U.sha256_text(U.CONFIG["filename_timestamp_format"])
        fps["camera_group_fingerprint"] = U.sha256_text(
            json.dumps(U.CONFIG.get("camera_time_and_timezone_policy") or {}, sort_keys=True))
    except Exception:
        pass
    try:
        hp = U.handoff_path(workspace)
        if os.path.exists(hp):
            with open(hp) as f:
                fps["handoff"] = U.handoff_content_fingerprint(json.load(f))
    except (OSError, ValueError):
        pass
    return fps


def _staleness(workspace, plan, cur):
    """Cheap stale reasons for a loaded plan's deps (empty if cur not supplied)."""
    if cur is None:
        return []
    return U.plan_dependencies_fresh(workspace, plan.get("depends_on") or {}, cur)


def _prep_summary(workspace, cur=None):
    plan, miss = _read_plan(U.prep_plan_path(workspace))
    if plan is None:
        return miss
    ops = plan.get("operations", []) or []
    counts = {}
    for op in ops:
        counts[op.get("type", "?")] = counts.get(op.get("type", "?"), 0) + 1
    summ = plan.get("summary", {}) or {}
    blockers = list(plan.get("blockers", []) or [])
    op_line = " · ".join(f"{t} {n}" for t, n in sorted(counts.items())) or "none"
    return {
        "exists": True, "plan_id": plan.get("plan_id"), "operations": len(ops), "blockers": blockers,
        "stale": _staleness(workspace, plan, cur),
        "lines": [f"{len(ops)} operation(s):", f"  {op_line}",
                  f"  no-op / already-correct {summ.get('no_op_files', 0)} · "
                  f"warnings {len(plan.get('warnings', []) or [])} · blockers {len(blockers)}"],
    }


def _geotag_summary(workspace, cur=None):
    from ..photos_2_geotag import executable_plan_path
    plan, miss = _read_plan(executable_plan_path(workspace))
    if plan is None:
        return miss
    dests = plan.get("destinations", {}) or {}
    ops = sum(len(d.get("operations", []) or []) for d in dests.values())
    blockers = list(plan.get("blockers", []) or [])
    return {
        "exists": True, "plan_id": plan.get("plan_id"), "operations": ops, "blockers": blockers,
        "stale": _staleness(workspace, plan, cur),
        "lines": [f"{ops} time/GPS write(s) across {len(dests)} destination(s)",
                  f"  status {plan.get('status', '?')} · blockers {len(blockers)}"],
    }


def _merge_summary(workspace, cur=None):
    from ..photos_3_merge import merge_plan_path
    plan, miss = _read_plan(merge_plan_path(workspace))
    if plan is None:
        return miss
    t = plan.get("totals", {}) or {}
    blockers = list(plan.get("blockers", []) or [])
    placed = t.get("placed_new", 0)
    return {
        "exists": True, "plan_id": plan.get("plan_id"), "operations": placed, "blockers": blockers,
        "stale": _staleness(workspace, plan, cur),
        "lines": [f"{placed} new · {t.get('already_present', 0)} already-present · "
                  f"{t.get('renamed_for_library', 0)} renamed · {t.get('blocked', 0)} blocked into the "
                  f"permanent library", f"  blockers {len(blockers)}"],
    }


_SUMMARIZERS = {"prep": _prep_summary, "geotag": _geotag_summary, "merge": _merge_summary}


def _plan_summary(workspace, phase="prep", cur=None):
    """Summarize the REAL saved plan artifact for `phase` (per the shared contract, the gate shows a
    summary of the actual serialized plan execution will consume — not a JS simulation). Common shape:
    exists / plan_id / operations / blockers / stale / lines. Each phase reads its own artifact (prep
    photos-10, geotag photos-24, merge photos-30). Pass `cur` (current fingerprints) to fill `stale`."""
    fn = _SUMMARIZERS.get(phase)
    return fn(workspace, cur) if fn else {"exists": False}


def _execute_guard(workspace, phase, payload):
    """Server-side enforcement of the 2-step gate for any phase's execute. Returns an error string to
    refuse, or None to allow. Refused unless the client explicitly confirmed, a saved plan exists with
    no blockers, is not stale (cheap dep check), and (if supplied) the reviewed plan_id still matches.
    The phase's own execute still re-validates everything besides (full fingerprint incl. GPX,
    no-clobber, the whole-run lock) — this is the deliberate gate on top, not a replacement."""
    if not payload.get("confirm"):
        return "execute requires explicit confirmation"
    s = _plan_summary(workspace, phase, _current_fingerprints(workspace))
    if not s.get("exists"):
        return "no saved plan — run plan first"
    if s.get("error"):
        return s["error"]
    if s.get("blockers"):
        return f"plan has {len(s['blockers'])} blocker(s) — resolve them and re-plan"
    if s.get("stale"):
        return f"plan is stale ({s['stale'][0]}) — re-plan"
    pid = payload.get("plan_id")
    if pid and pid != s.get("plan_id"):
        return "the plan changed since you reviewed it — re-open the gate"
    return None


_JOBS_MAX = 256


def _cpu_count():
    """Logical CPUs of the machine running the SERVER (the Jobs box's upper bound), floored at 1."""
    try:
        return max(1, os.cpu_count() or 2)
    except Exception:
        return 1


def _default_jobs():
    """Console default for -j: one fewer than the server machine's logical CPUs, floored at 1. The user
    can override it via the in-page Jobs box (up to the CPU count)."""
    return max(1, _cpu_count() - 1)


def _jobs_argv(jobs):
    """['-j', N] for a valid client-supplied jobs count, else [] (fall back to the phase default). A
    non-int / out-of-range value is ignored rather than erroring — it's an affordance, not a contract."""
    try:
        j = int(jobs)
    except (TypeError, ValueError):
        return []
    if 1 <= j <= _JOBS_MAX:
        return ["-j", str(j)]
    return []


def _prune_extra(payload):
    """Build the prune-quarantine argv from a payload `prune` block: selectors (plan_ids / all /
    older_than_days) and the destructive `delete` (→ --yes). No `delete` ⇒ a safe dry-run (no --yes)."""
    pr = payload.get("prune") or {}
    extra = []
    for pid in (pr.get("plan_ids") or []):
        extra += ["--plan-id", str(pid)]
    if pr.get("older_than_days") is not None:
        extra += ["--older-than-days", str(int(pr["older_than_days"]))]
    if pr.get("all"):
        extra += ["--all"]
    if pr.get("delete"):
        extra += ["--yes"]
    return extra


def _prune_guard(payload):
    """Gate the DESTRUCTIVE quarantine delete. A dry-run (no `delete`) is always allowed. A delete
    requires explicit confirmation AND a selector (a plan id, --all, or older-than-days) so the UI can
    never one-click an unscoped purge. The core still validates; this is the deliberate gate on top."""
    pr = payload.get("prune") or {}
    if not pr.get("delete"):
        return None                                  # dry-run: safe, no confirmation needed
    if not payload.get("confirm"):
        return "quarantine delete requires explicit confirmation"
    if not (pr.get("plan_ids") or pr.get("all") or pr.get("older_than_days") is not None):
        return "select what to prune (a plan id, all, or older-than-days) before deleting"
    return None


def _library_blessed(workspace):
    """True if the workspace's configured `merge.library_root` is a blessed library (carries the
    `.photos-library` marker). Merge plan hard-requires it, so the console gates on it too — and an
    `init-library` that blesses it then flips merge/plan on. Cheap, best-effort (a marker stat)."""
    try:
        with open(U.config_path(workspace)) as f:
            lib = ((json.load(f) or {}).get("merge") or {}).get("library_root")
    except (OSError, ValueError):
        return False
    return bool(lib) and U.is_library(lib)


def _runnable_actions(workspace, phases, sealed, busy, initialized=True):
    """Per-command affordance from VISIBLE artifacts (not a deep validation): {cmd: {ok, reason}}.
    Encodes the sequential pipeline (prep → geotag → merge) + plan-exists/executable/staleness, plus
    the sealed and run-in-progress global stops. The core still validates in depth and refuses; this
    only stops the UI offering actions that can't currently make sense."""
    out = {}

    def g(cmd, ok, reason=""):
        out[cmd] = {"ok": bool(ok), "reason": "" if ok else reason}

    if busy:
        for c in _RUNNABLE:
            g("/".join(c), False, "a run is in progress")
        return out
    if not initialized and not phases["prep"]["plan_exists"]:
        # TRULY fresh cwd: no guard sentinel AND no prep plan yet — prep plan is the only meaningful
        # action. NOTE the guard is written by prep EXECUTE, not plan, so once a plan exists we must
        # fall through to the normal logic (which enables prep dry-run/execute off the saved plan);
        # otherwise a freshly-planned-but-not-yet-executed workspace would wrongly stay locked down.
        for c in _RUNNABLE:
            g("/".join(c), c == ("prep", "plan"),
              "initialize the workspace first — run prep plan")
        return out
    if sealed:
        # A sealed workspace is terminal: everything is refused EXCEPT prune-quarantine, the sole
        # maintenance op the seal permits (mirrors prep's own carve-out — see _prune_guard / the
        # seal-prune-exception behavior). Quarantine cleanup must survive the seal.
        for c in _RUNNABLE:
            g("/".join(c), c == ("prep", "prune-quarantine"),
              "" if c == ("prep", "prune-quarantine") else "workspace is sealed (already merged)")
        return out

    from ..photos_2_geotag import complete_log_path, execution_summary_path
    pe, ge, me = phases["prep"], phases["geotag"], phases["merge"]
    prep_done = os.path.exists(U.handoff_path(workspace))         # prep executed → handoff written
    geotag_done = os.path.exists(complete_log_path(workspace))    # geotag finalized → complete log
    geotag_executed = _json_status(execution_summary_path(workspace)) == "success"  # ready to finalize

    g("prep/plan", True)
    g("prep/dry-run", pe["plan_exists"], "run prep plan first")
    g("prep/execute", pe["executable"], "needs a clean, blocker-free, fresh prep plan")
    g("prep/prune-quarantine", True)     # maintenance, runnable anytime (the destructive delete is gated)
    g("geotag/plan", prep_done, "run prep execute first")
    g("geotag/execute", ge["executable"], "needs a clean, fresh geotag plan")
    g("geotag/finalize", geotag_executed and not geotag_done,
      "finalized already" if geotag_done else "geotag execute must succeed first")
    g("merge/init-library", True)        # one-time setup, runnable anytime (unless sealed/busy)
    # merge plan needs BOTH geotag finalized AND a blessed library (the phase hard-blocks without the
    # library — §3 precond 5), so gate on both and name whichever is missing. This makes init-library a
    # visible enabler of merge/plan instead of letting it be clicked into a runtime "not a blessed
    # library" failure.
    library_ok = _library_blessed(workspace)
    g("merge/plan", geotag_done and library_ok,
      "finish geotag (finalize) first" if not geotag_done else "bless the library first — run merge init-library")
    g("merge/dry-run", me["plan_exists"], "run merge plan first")
    g("merge/execute", me["executable"], "needs a clean, fresh merge plan")
    return out


def _state(workspace):
    """Transient state for the chrome: workspace flags, lock, current job, per-phase hints (incl.
    staleness) and per-command affordance (`actions`). Cheap, best-effort — never the source of truth."""
    lock = U.WorkspaceLock(workspace)
    try:
        # held_owner (not read_owner): only report a holder if the flock is LIVE. read_owner reflects
        # the last writer and is never cleared, so a finished/interrupted CLI run would otherwise look
        # like an in-progress one and wedge every button (incl. Plan).
        owner = lock.held_owner()
    except Exception:
        owner = None
    sealed = bool(U.is_sealed(workspace))
    initialized = os.path.exists(U.guard_path(workspace))
    cur = _current_fingerprints(workspace)
    phases = {}
    for ph in ("prep", "geotag", "merge"):
        s = _plan_summary(workspace, ph, cur)
        stale = list(s.get("stale", []) or [])
        phases[ph] = {
            "plan_exists": bool(s.get("exists")),
            "plan_id": s.get("plan_id"),
            "blockers": len(s.get("blockers", []) or []),
            "stale": len(stale),
            # executable = a plan exists, parses, has no blockers, and is not stale (mirrors the gate)
            "executable": bool(s.get("exists") and not s.get("blockers")
                               and not s.get("error") and not stale),
        }
    busy = JOBS.running or bool(owner)
    return {
        "workspace": os.path.abspath(workspace),
        "initialized": initialized,
        "default_jobs": _default_jobs(),
        "cpu_count": _cpu_count(),
        "sealed": sealed,
        "lock_owner": owner,
        "job": JOBS.status(),
        "runnable": sorted("/".join(p) for p in _RUNNABLE),
        "actions": _runnable_actions(workspace, phases, sealed, busy, initialized),
        "phases": phases,
    }


class Handler(BaseHTTPRequestHandler):
    workspace = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def _sse_write(self, obj):
        self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
        self.wfile.flush()

    def _serve_events(self):
        q, snapshot = WEB.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._sse_write({"kind": "snapshot", **snapshot})
            while True:
                try:
                    msg = q.get(timeout=15)
                except Exception:
                    self.wfile.write(b": keepalive\n\n")   # heartbeat so proxies/clients hold open
                    self.wfile.flush()
                    continue
                self._sse_write(msg)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ValueError, OSError):
            self.close_connection = True
        finally:
            WEB.unsubscribe(q)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            return self._send(200, _state(self.workspace))
        if path == "/api/plan-summary":
            phase = (parse_qs(urlparse(self.path).query).get("phase") or ["prep"])[0]
            return self._send(200, _plan_summary(self.workspace, phase, _current_fingerprints(self.workspace)))
        if path == "/api/events":
            return self._serve_events()
        # Folded-in decision editor (v2.4): its API is delegated to the editor's own functions on the
        # cwd workspace; its assets are served under /edit/ so the whole thing lives on one origin
        # (the single SSH tunnel still suffices). The editor's /api/* paths don't collide with ours.
        if path == "/api/artifacts":
            return self._send(200, _editor._load_artifacts(self.workspace))
        if path == "/api/photo":
            rel = (parse_qs(urlparse(self.path).query).get("path") or [""])[0]
            data = _editor._photo_preview(self.workspace, rel)
            if data is None:
                return self._send(404, {"error": "no preview available"})
            return self._send(200, data, "image/jpeg")
        if path in ("/edit", "/edit/"):
            data = _read_pkg("cartographer.editor", "web", ["index.html"])
            return self._send(200, data, "text/html; charset=utf-8") if data is not None \
                else self._send(404, {"error": "editor assets missing"})
        if path.startswith("/edit/"):
            parts = [p for p in path[len("/edit/"):].split("/") if p not in ("", ".")]
            data = _read_pkg("cartographer.editor", "web", parts)
            if data is None:
                return self._send(404, {"error": f"not found: {path}"})
            return self._send(200, data, _CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))
        if path == "/":
            path = "/index.html"
        data = _asset(path)
        if data is None:
            return self._send(404, {"error": f"not found: {path}"})
        return self._send(200, data, _CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/api/run", "/api/cancel", "/api/save", "/api/rerun"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError) as e:
            return self._send(400, {"ok": False, "error": f"bad request: {e}"})
        # Folded-in editor writes (decision edits) + its geotag re-run, delegated to the editor.
        if path == "/api/save":
            return self._send(200, _editor._save(self.workspace, payload))
        if path == "/api/rerun":
            return self._send(200, _editor._rerun(self.workspace))
        if path == "/api/cancel":
            # Interrupt the running job (Ctrl-C equivalent). Cancelling a MUTATING execute needs an
            # explicit confirm (mirrors the execute gate); plan/dry-run/etc. stop immediately. The run
            # is journalled/idempotent, so an interrupt leaves nothing partially applied.
            st = JOBS.status()
            if not JOBS.running:
                return self._send(409, {"ok": False, "error": "no run in progress"})
            if (st.get("label") or "").endswith("execute") and not payload.get("confirm"):
                return self._send(409, {"ok": False,
                                        "error": "interrupting a mutating execute requires confirmation"})
            ok = JOBS.cancel()
            return self._send(200 if ok else 409,
                              {"ok": ok, "error": None if ok else "no run in progress"})
        phase, command = payload.get("phase"), payload.get("command")
        if (phase, command) not in _RUNNABLE:
            return self._send(403, {"ok": False,
                                    "error": f"{phase}/{command} not runnable from the console yet"})
        if JOBS.running:
            return self._send(409, {"ok": False, "error": "a run is already in progress"})
        if command == "execute":
            err = _execute_guard(self.workspace, phase, payload)
            if err:
                return self._send(409, {"ok": False, "error": err})
        extra = []
        if command == "init-library":
            p = (payload.get("path") or "").strip()
            if p:
                extra = [p]                  # else: blank → bless the configured library_root
        elif command == "prune-quarantine":
            err = _prune_guard(payload)      # gate the destructive --yes delete (dry-run is free)
            if err:
                return self._send(409, {"ok": False, "error": err})
            extra = _prune_extra(payload)
        # Parallelism: -j lives on each phase's PARENT parser, so it must precede the subcommand — pass
        # it as `pre`, not in `extra`. Sent whenever the client supplies a valid count (clamped); phases
        # that don't parallelize accept-and-ignore it.
        pre = _jobs_argv(payload.get("jobs"))
        started = JOBS.start(f"{phase} {command}", _make_target(phase, command, extra, pre))
        return self._send(200 if started else 409,
                          {"ok": started, "error": None if started else "a run is already in progress"})


CONSOLE_BLURB = (
    "console — run and monitor the pipeline in a browser (over the CURRENT DIRECTORY / workspace).\n\n"
    "Launches a local web server with a live view of each phase: trigger a run, watch its log and "
    "progress stream in real time. Drives the same plan/validate/execute core as the CLI — same "
    "safety (no-clobber, the whole-run lock, plan -> dry-run -> execute). Bound to 127.0.0.1 by "
    "default; for remote use, tunnel over SSH. Open the printed URL; Ctrl-C to stop."
)


def serve(workspace, port, host):
    initialized = os.path.exists(U.guard_path(workspace))
    # An uninitialized cwd is allowed: the console opens with only prep/plan enabled (it is prep's own
    # entry point — see _runnable_actions), so the operator can initialize from the browser. The CLI
    # still prints a heads-up so launching in the wrong directory is obvious.
    if not initialized:
        print(f"note: {os.path.abspath(workspace)} is not initialized yet "
              f"(no {os.path.basename(U.guard_path(workspace))}). Opening the console — only "
              f"`prep plan` is enabled; run it to initialize, then the rest unlocks.", file=sys.stderr)
    # The console's active reporter is the WebSink: phase run()s (and the coordinator) emit through
    # get_reporter() to it, and the browser receives the stream over SSE.
    set_reporter(Reporter([WEB]))
    Handler.workspace = workspace
    server = _bind(host, port, Handler)
    bound = server.server_address[1]
    link_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"operational console — workspace {os.path.abspath(workspace)}")
    if bound != port:
        print(f"  (port {port} was busy — using {bound})")
    print(f"  open  http://{link_host}:{bound}/")
    hint = U.ssh_tunnel_hint(bound, host)
    if hint:
        print("  loopback-only — from your local machine, tunnel then open the URL above:")
        print(f"    {hint}")
    print("  (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        server.server_close()
        print("stopped.")
    return 0


def add_arguments(parser):
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default loopback; tunnel over SSH for remote use)")
    parser.set_defaults(_run=run, _parser=parser)


def run(args):
    return serve(os.getcwd(), args.port, args.host)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cartographer.console",
                                     description=CONSOLE_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
