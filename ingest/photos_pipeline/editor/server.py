# Copyright 2026 sigfridvonshrink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The decision editor's local server — `photos-ingest edit` (operates on the current-directory workspace).

Serves the single-page app and exposes the workspace's decision artifacts as JSON. Stdlib only; its
front-end + demo fixtures are PACKAGE DATA (`photos_pipeline/editor/{web,examples}`) read via
importlib.resources, so it works identically from a checkout and from inside the shipped zipapp.

It launches nothing — it prints a clickable link using the machine's own IP and binds to a reachable
interface (default 0.0.0.0), so you can open the editor in your laptop's browser while SSH'd into the
machine. Ctrl-C stops it cleanly (releasing the port).

It reads `./.photos-ingest/photos-21*/photos-23*` decision JSON from the current-directory workspace
(refusing to run if the cwd is not an initialized workspace); `--demo` runs read-only on the bundled
example fixtures instead. The app edits `user_decision` and saves it back
(POST /api/save writes only `user_decision`, round-tripping the rest; disabled in demo). GET
/api/photo returns a downscaled JPEG preview for the map picker (path-safe; 404 in demo). POST
/api/rerun self-invokes `photos-ingest geotag plan` against the workspace and returns its exit code +
output tail; the client reloads on success. See design-notes.md.
"""
import argparse
import errno
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    import fcntl  # POSIX advisory locking (Linux — the pipeline already relies on it)
except ImportError:
    fcntl = None


def _bind(host, port, handler):
    """Bind to `port`, or the next free port above it if it's in use — so a busy port is never an error,
    the server just moves up. Returns the server (its actual port is server_address[1])."""
    for p in range(port, port + 64):
        try:
            return ThreadingHTTPServer((host, p), handler)
        except OSError as e:
            if e.errno == errno.EADDRINUSE:
                continue          # busy — try the next one
            raise                 # EACCES (privileged port), bad host, etc. — a real problem
    raise OSError(errno.EADDRINUSE, f"no free port in {port}..{port + 63}")


def _machine_ip():
    """The machine's primary outbound IPv4 — the address a remote browser would use. No packets are
    sent (UDP connect just selects the routing interface). Falls back to the hostname, then loopback."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()

# The editor lives inside the photos_pipeline package; geotag re-run self-invokes the combined
# CLI (`python -m photos_pipeline geotag plan`) — works from a checkout and from inside the shipped
# zipapp. PKG_ROOT is the sys.path entry that holds the package: a checkout's ingest/, or the .pyz file
# itself (so a subprocess `python -m photos_pipeline …` imports it).
PKG_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTROL = ".photos-ingest"
TIME_NAME = "photos-21-time-decisions.json"
DRIFT_NAME = "photos-22-gps-drift-validation.json"
GPS_NAME = "photos-23-gps-decisions.json"
CONFIG_NAME = "photos-00-config.json"
GUARD_NAME = "photos-00-workspace-guard"        # root sentinel written once a workspace is initialized
EDITOR_LOCK = "photos-00-decision-editor.lock"  # dotfile lives in CONTROL; flock, fail-fast

_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
                  ".svg": "image/svg+xml", ".png": "image/png"}

PREVIEW_MAX_PX = 1600     # longest edge of a generated photo preview
RERUN_TIMEOUT_S = 3600    # cap on a `photos-ingest geotag plan` invoked from the editor


# Front-end + demo fixtures are PACKAGE DATA (photos_pipeline/editor/{web,examples}), read via
# importlib.resources so they resolve identically from a checkout and from inside the zipapp. The rest
# of the server only ever calls _web_asset(rel) / _example_bytes(name).
import importlib.resources as _res


def _read_data(subdir, parts):
    if not parts or any(p in ("", ".", "..") for p in parts):
        return None                                 # empty or path-escaping -> not found
    try:
        t = _res.files("photos_pipeline.editor").joinpath(subdir, *parts)
        return t.read_bytes() if t.is_file() else None
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None


def _web_asset(rel):
    """Raw bytes of the web asset at relative URL path `rel`, or None if missing / path-escaping."""
    return _read_data("web", [p for p in (rel or "").split("/") if p not in ("", ".")])


def _example_bytes(name):
    """Raw bytes of the demo-mode example fixture `name`, or None if absent."""
    return _read_data("examples", [name] if name else [])


def _acquire_editor_lock(workspace):
    """Take a fail-fast exclusive lock so only one editor edits a workspace's decision JSON at a time.

    Returns (lock_file, None) on success — keep the file open for the session; the OS releases the
    flock when it closes (including on a crash/kill). Returns (None, owner_dict) if another editor
    already holds it. If flock is unavailable (non-POSIX), returns (open_file, None) without locking —
    best effort, never blocks the editor from running."""
    path = os.path.join(workspace, CONTROL, EDITOR_LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+")
    if fcntl is None:
        return f, None
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        try:
            owner = json.loads(f.read() or "null")
        except ValueError:
            owner = None
        f.close()
        return None, owner
    f.seek(0)
    f.truncate(0)
    json.dump({"pid": os.getpid(), "host": socket.gethostname(),
               "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, f)
    f.flush()
    return f, None


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as e:
        return {"_error": f"could not read {os.path.basename(path)}: {e}"}


def _safe_workspace_path(workspace, rel):
    """Resolve a workspace-relative path, refusing anything that escapes the workspace (so a crafted
    `path=` can never read outside it). Returns the absolute path, or None if it escapes."""
    full = os.path.abspath(os.path.join(workspace, (rel or "").lstrip("/")))
    base = os.path.abspath(workspace)
    if full == base or full.startswith(base + os.sep):
        return full
    return None


def _photo_preview(workspace, rel):
    """JPEG bytes of a downscaled preview of the photo at workspace-relative `rel`, or None.

    Prefers an embedded JPEG (exiftool — cheap, no full RAW decode); falls back to an ImageMagick
    downscale (handles JPEG/TIFF/PNG/most RAW). Best-effort: a missing tool or any failure → None, and
    the UI shows a placeholder. Used only for the manual-placement context, never to mutate originals."""
    full = _safe_workspace_path(workspace, rel)
    if not full or not os.path.isfile(full):
        return None
    if shutil.which("exiftool"):
        for tag in ("-PreviewImage", "-JpgFromRaw"):
            try:
                out = subprocess.run(["exiftool", "-b", tag, full], capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                continue
            if out.returncode == 0 and out.stdout[:2] == b"\xff\xd8":  # JPEG start-of-image
                return out.stdout
    if shutil.which("magick"):
        try:
            out = subprocess.run(
                ["magick", full + "[0]", "-auto-orient",
                 "-resize", f"{PREVIEW_MAX_PX}x{PREVIEW_MAX_PX}>", "-quality", "82", "jpeg:-"],
                capture_output=True, timeout=60)
            if out.returncode == 0 and out.stdout[:2] == b"\xff\xd8":
                return out.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _example_json(name):
    """Parsed JSON of demo fixture `name`; None if absent, or {_error} if it won't parse."""
    raw = _example_bytes(name)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError as e:
        return {"_error": f"could not parse {name}: {e}"}


def _geotag_cmd_env():
    """The argv + env to re-run geotag: self-invoke the combined CLI `python -m photos_pipeline
    geotag plan` with PKG_ROOT on PYTHONPATH, so it imports the package whether that root is a
    checkout's ingest/ or the shipped .pyz — and regardless of the editor's cwd."""
    env = os.environ.copy()
    env["PYTHONPATH"] = PKG_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return [sys.executable, "-m", "photos_pipeline", "geotag", "plan"], env


def _environment(workspace):
    """Folder dependencies geotag needs that may live on a different machine than this editor.

    The geotag pipeline ships in the same package as this editor, so it is always runnable. The
    one external dependency is the configured `gpx_root`, which GPX time-anchoring reads and which can
    be a mount visible only on the workspace's own host: re-running without it would regenerate the
    time/GPS decisions as if there were no GPX, silently discarding good offsets/placements. It is
    resolved from the workspace config (`photos-00-config.json`) the way geotag resolves it
    (`photos_utils.selected_gpx_root`); an EMPTY gpx_root means 'no GPX configured' and does not block.
    The Re-run button (and `_rerun`) gate on `deps_ok`; `missing` names each absent dependency."""
    missing = []
    geotag_present = True               # geotag is a sibling module in this package
    cfg = _read_json(os.path.join(workspace, CONTROL, CONFIG_NAME))
    root = (cfg or {}).get("gpx_root") or "" if isinstance(cfg, dict) else ""
    resolved = os.path.realpath(os.path.abspath(root)) if root else ""
    gpx_available = (not resolved) or os.path.isdir(resolved)
    if not gpx_available:
        missing.append(f"gpx_root ({resolved})")
    return {"geotag_present": geotag_present,
            "gpx_root": resolved, "gpx_configured": bool(resolved),
            "gpx_available": gpx_available, "deps_ok": not missing, "missing": missing}


def _load_artifacts(workspace):
    """Return {workspace, demo, time, drift, gps, environment}. Demo mode loads requires-input fixtures."""
    if workspace:
        cd = os.path.join(workspace, CONTROL)
        return {"workspace": os.path.abspath(workspace), "demo": False,
                "time": _read_json(os.path.join(cd, TIME_NAME)),
                "drift": _read_json(os.path.join(cd, DRIFT_NAME)),
                "gps": _read_json(os.path.join(cd, GPS_NAME)),
                "environment": _environment(workspace)}
    return {"workspace": None, "demo": True, "environment": None,
            "time": _example_json("photos-21-time-decisions.requires-input.json"),
            "drift": _example_json("photos-22-gps-drift-validation.requires-input.json"),
            "gps": _example_json("photos-23-gps-decisions.requires-input.json")}


def _write_json(path, obj):
    """Deterministic, atomic write matching the pipeline's write_json_artifact (sorted, indented)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _apply_edits(art, edits):
    """Apply each edit's `user_decision` to the matching cell in `art`, in place. ONLY `user_decision`
    is ever written — every other field is left exactly as geotag produced it, so the round-trip
    conforms regardless of what the client sent. Returns the count applied."""
    applied = 0
    dests = (art or {}).get("destinations") or {}
    for e in edits:
        d = dests.get(e.get("dest"))
        if not isinstance(d, dict):
            continue
        kind = e.get("kind")
        if kind == "timezone":
            cell = d.get("destination_timezone")
        elif kind == "offset":
            cell = (d.get("camera_group_time_decisions") or {}).get(e.get("key"))
        elif kind == "drift":
            cell = (d.get("drift_decisions") or {}).get(e.get("key"))
        elif kind == "fallback":
            cell = d.get("folder_fallback")
        elif kind == "review":
            cell = next((r for r in (d.get("gps_decisions") or {}).get("review_items") or []
                         if r.get("relative_path") == e.get("path")), None)
        else:
            cell = None
        if isinstance(cell, dict) and isinstance(e.get("user_decision"), dict):
            cell["user_decision"] = e["user_decision"]
            applied += 1
    return applied


def _save(workspace, payload):
    """Write the posted user_decision edits back into the workspace's decision artifacts."""
    cd = os.path.join(workspace, CONTROL)
    written = []
    for key, name in (("time", TIME_NAME), ("drift", DRIFT_NAME), ("gps", GPS_NAME)):
        edits = (payload or {}).get(key) or []
        if not edits:
            continue
        art = _read_json(os.path.join(cd, name))
        if not isinstance(art, dict) or "_error" in art:
            return {"ok": False, "error": f"cannot read {name} to update"}
        _apply_edits(art, edits)
        _write_json(os.path.join(cd, name), art)
        written.append(name)
    return {"ok": True, "written": written}


def _rerun(workspace):
    """Re-run `photos-ingest geotag plan` against the workspace, regenerating the authoritative artifacts
    from the saved decisions. Geotag takes the workspace as its CWD and owns its own WorkspaceLock
    (separate from the editor lock), so a concurrent geotag is reported, not forced. Returns the
    process outcome; the client reloads /api/artifacts on success. Mutates nothing here — `run` only
    plans (no writes to originals)."""
    env = _environment(workspace)        # gate: never recalc without the pipeline + its data on this host
    if not env["deps_ok"]:
        return {"ok": False, "error": "geotag cannot run on this machine — missing: "
                + ", ".join(env["missing"]) + ". Run the editor on the host that has the pipeline and its data."}
    cmd, run_env = _geotag_cmd_env()
    try:
        proc = subprocess.run(cmd, cwd=workspace, env=run_env,
                              capture_output=True, text=True, timeout=RERUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"geotag timed out after {RERUN_TIMEOUT_S}s"}
    except OSError as e:
        return {"ok": False, "error": f"could not start geotag: {e}"}
    # Tail the output so a huge log can't bloat the response; the exit code is the source of truth
    # (0 = planned, 2 = blockers/unknown groups, 1 = workspace locked — see photos-2-geotag main()).
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]}


class Handler(BaseHTTPRequestHandler):
    workspace = None

    def log_message(self, *a):
        pass  # quiet

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
            # The client went away mid-response — e.g. the browser cancelled a hover photo-preview
            # request as the mouse moved off before the JPEG finished sending. Harmless: drop the
            # response quietly and end the connection, rather than letting socketserver dump a traceback.
            self.close_connection = True

    def _serve_static(self, rel):
        rel = rel.lstrip("/") or "index.html"
        data = _web_asset(rel)  # None for missing or path-escaping rel — both 404 (never reveals the file tree)
        if data is None:
            return self._send(404, {"error": f"not found: {rel}"})
        ct = _CONTENT_TYPES.get(os.path.splitext(rel)[1], "application/octet-stream")
        self._send(200, data, ct)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/artifacts":
            return self._send(200, _load_artifacts(self.workspace))
        if path == "/api/photo":
            if self.workspace is None:
                return self._send(404, {"error": "no photo previews in demo mode"})
            rel = (parse_qs(urlparse(self.path).query).get("path") or [""])[0]
            data = _photo_preview(self.workspace, rel)
            if data is None:
                return self._send(404, {"error": "no preview available"})
            return self._send(200, data, "image/jpeg")
        if path == "/":
            return self._serve_static("index.html")
        return self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/api/save", "/api/rerun"):
            return self._send(404, {"error": "not found"})
        if self.workspace is None:
            return self._send(403, {"ok": False, "error": "demo mode is read-only — "
                                    "run `photos-ingest edit` inside a workspace to edit and re-run"})
        if path == "/api/rerun":
            return self._send(200, _rerun(self.workspace))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError) as e:
            return self._send(400, {"ok": False, "error": f"bad request: {e}"})
        self._send(200, _save(self.workspace, payload))


EDIT_BLURB = (
    "edit — resolve the open decisions in a browser (between geotag plans).\n\n"
    "Launches a local web server for the decision editor over the CURRENT DIRECTORY (the workspace; "
    "like every other phase, edit operates on the cwd and refuses to run anywhere that is not an "
    "initialized workspace). You confirm/correct the time, GPS and drift decisions geotag surfaced; "
    "Save writes them back; then re-run `photos-ingest geotag plan` in a terminal to regenerate from "
    "your edits and reload. Open the printed URL (reachable over the network so you can use it "
    "from another machine's browser); Ctrl-C to stop.\n\n"
    "  --demo   read-only tour on bundled fixtures (no workspace; nothing is written).\n\n"
    "Loop: geotag plan -> edit -> geotag plan -> ... -> geotag execute."
)


def add_arguments(parser):
    """Register the `edit` phase's arguments. Unlike the workflow phases, `edit` has no subcommands —
    it runs the server directly — so the combined CLI dispatches it the moment `edit` is chosen. Like
    every phase, the workspace is the cwd; there is no workspace-naming argument."""
    parser.add_argument("--demo", action="store_true",
                        help="Read-only tour on bundled example fixtures (no workspace; writes nothing).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address. Default 0.0.0.0 = reachable over the network (e.g. from a "
                             "browser on your laptop while SSH'd into this machine). Use 127.0.0.1 for "
                             "local-only.")
    parser.set_defaults(_run=run, _parser=parser)


def run(args):
    # Workspace = cwd, like every other phase. `--demo` is the only way to run without one (read-only
    # fixtures); there is no positional workspace path.
    return serve(None if args.demo else os.getcwd(), args.port, args.host)


def serve(workspace, port=8765, host="0.0.0.0"):
    # A real (non-demo) workspace must be an initialized workspace — the same bar every phase applies:
    # the root guard sentinel must exist. Refuse anything else rather than serving an empty editor.
    if workspace and not os.path.exists(os.path.join(workspace, CONTROL, GUARD_NAME)):
        print(f"{os.path.abspath(workspace)} is not an initialized workspace "
              f"(no {CONTROL}/{GUARD_NAME}). Run `photos-ingest prep plan` here first, "
              f"or use `photos-ingest edit --demo` for a read-only fixtures tour.", file=sys.stderr)
        sys.exit(2)
    Handler.workspace = workspace

    # Editor lock: refuse to open a second editor on the same workspace, so two people can't edit the
    # decision JSON at once and clobber each other on Save. Demo mode touches no workspace files, so it
    # needs no lock. The lock is held for the whole session and auto-released on exit (even on a kill).
    lock = None
    if workspace:
        lock, owner = _acquire_editor_lock(workspace)
        if lock is None:
            d = owner or {}
            print(f"another decision editor is already editing this workspace "
                  f"(pid {d.get('pid', '?')} on {d.get('host', '?')}, since {d.get('started_at', '?')}). "
                  f"Close it first, or point this one at a different workspace.", file=sys.stderr)
            sys.exit(1)

    srv = _bind(host, port, Handler)
    srv.daemon_threads = True  # don't let an in-flight request block Ctrl-C shutdown
    bound_port = srv.server_address[1]
    # The clickable link uses the machine's real IP (so it works from a remote browser); a specific
    # --host is shown verbatim.
    link_host = _machine_ip() if host in ("0.0.0.0", "", "::") else host
    mode = "demo mode — example fixtures (read-only)" if not workspace \
        else f"workspace {os.path.abspath(workspace)}"
    print(f"decision editor — {mode}")
    if bound_port != port:
        print(f"  (port {port} was busy — using {bound_port})")
    print(f"  open  http://{link_host}:{bound_port}/")
    print("  (Ctrl-C to stop)", flush=True)  # flush so the link shows at once even when piped
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        srv.server_close()  # release the port; daemon worker threads exit with the process
        if lock is not None:
            lock.close()  # releases the flock
        print("stopped.")


def main(argv=None):
    """Standalone entry (`python -m photos_pipeline.editor.server`); the normal path is
    `photos-ingest edit`, which calls run()/serve() directly."""
    parser = argparse.ArgumentParser(prog="photos_pipeline.editor.server", description=EDIT_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
