"""Operational console server (web-console design, v2.1).

A local web server that drives the SAME plan/validate/execute core the CLI drives — it only triggers
phase runs (in-process, single-slot via JobRunner) and streams their status to the browser over SSE
(via WebSink). One mutation path: every action calls the phase's own ``run()``; the web layer never
re-implements a move/plan. Operates on the cwd workspace, like every other phase.

v2.1 scope: prep ``plan`` / ``dry-run`` (both non-mutating) + live monitoring. ``execute`` and the
2-step gate land in v2.2; geotag/merge tabs and the folded-in editor follow.

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

from .. import photos_utils as U
from ..reporting import Reporter, WebSink, set_reporter
from .jobs import JobRunner

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png",
}

# v2.1: only these (phase, command) pairs may be triggered — both non-mutating. execute is gated to v2.2.
_ALLOWED = {("prep", "plan"), ("prep", "dry-run")}

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


def _make_target(phase, command):
    """Build the zero-arg job callable for (phase, command): parse the phase's own argv so defaults
    match the CLI exactly, then call its run(). run() reads cwd as the workspace and may sys.exit()
    (the JobRunner catches that)."""
    mod = _phase_module(phase)
    parser = argparse.ArgumentParser()
    mod.add_arguments(parser)
    args = parser.parse_args([command])

    def target():
        mod.run(args)
    return target


def _state(workspace):
    """Transient state for the dashboard chrome: workspace flags, lock, current job, per-phase hints.
    Cheap, best-effort — never the source of truth."""
    prep_plan = U.prep_plan_path(workspace)
    lock = U.WorkspaceLock(workspace)
    owner = None
    try:
        owner = lock.read_owner()
    except Exception:
        owner = None
    return {
        "workspace": os.path.abspath(workspace),
        "sealed": bool(U.is_sealed(workspace)),
        "lock_owner": owner,
        "job": JOBS.status(),
        "allowed": sorted("/".join(p) for p in _ALLOWED),
        "phases": {
            "prep": {"plan_exists": os.path.exists(prep_plan)},
        },
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
        if path == "/api/events":
            return self._serve_events()
        if path == "/":
            path = "/index.html"
        data = _asset(path)
        if data is None:
            return self._send(404, {"error": f"not found: {path}"})
        return self._send(200, data, _CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/run":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError) as e:
            return self._send(400, {"ok": False, "error": f"bad request: {e}"})
        phase, command = payload.get("phase"), payload.get("command")
        if (phase, command) not in _ALLOWED:
            return self._send(403, {"ok": False,
                                    "error": f"{phase}/{command} not runnable from the console yet"})
        if JOBS.running:
            return self._send(409, {"ok": False, "error": "a run is already in progress"})
        started = JOBS.start(f"{phase} {command}", _make_target(phase, command))
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
    if not os.path.exists(U.guard_path(workspace)):
        print(f"{os.path.abspath(workspace)} is not an initialized workspace "
              f"(no {os.path.basename(U.guard_path(workspace))}). Run `photos-cartographer prep plan` "
              f"to initialize it first.", file=sys.stderr)
        return 2
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
