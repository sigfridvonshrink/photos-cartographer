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

"""The decision editor's local server — `photos-cartographer edit` (operates on the current-directory workspace).

Serves the single-page app and exposes the workspace's decision artifacts as JSON. Stdlib only; its
front-end + demo fixtures are PACKAGE DATA (`cartographer/editor/{web,examples}`) read via
importlib.resources, so it works identically from a checkout and from inside the shipped zipapp.

It launches nothing — it prints a clickable link using the machine's own IP and binds to a reachable
interface (default 0.0.0.0), so you can open the editor in your laptop's browser while SSH'd into the
machine. Ctrl-C stops it cleanly (releasing the port).

It reads `./.photos-ingest/photos-21*/photos-22*/photos-23*` decision JSON, and the fingerprint mismatches of
`photos-25*` (geotag's execution summary), from the current-directory workspace
(refusing to run if the cwd is not an initialized workspace); `--demo` runs read-only on the bundled
example fixtures instead. The app edits `user_decision` and saves it back
(POST /api/save writes only `user_decision`, round-tripping the rest; disabled in demo). GET
/api/photo returns a downscaled JPEG preview for the map picker (path-safe; 404 in demo). The loop
back to geotag is an explicit `photos-cartographer geotag plan` re-run + reload. See design-notes.md.
"""
import argparse
import errno
import hashlib
import fcntl  # POSIX advisory locking for the editor's lock (the pipeline relies on it throughout)
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import photos_utils
from .. import photos_2_geotag


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

CONTROL = ".photos-ingest"
TIME_NAME = "photos-21-time-decisions.json"
DRIFT_NAME = "photos-22-gps-drift-validation.json"
GPS_NAME = "photos-23-gps-decisions.json"
EXECUTION_NAME = "photos-25-execution-summary.json"   # its fingerprint_mismatches ask whether a changed photo stands
CONFIG_NAME = "photos-00-config.json"           # a new camera group's class is written into its device_groups
HANDOFF_NAME = "photos-11-handoff.json"         # prep's record: the photos whose camera groups geotag classes
DEVICE_CLASSES = ("phones", "fixed_clock_cameras")   # the two arrays of camera_time_and_timezone_policy.device_groups
GUARD_NAME = "photos-00-workspace-guard"        # root sentinel written once a workspace is initialized
EDITOR_LOCK = "photos-00-decision-editor.lock"  # dotfile lives in CONTROL; flock, fail-fast

_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
                  ".svg": "image/svg+xml", ".png": "image/png"}

PREVIEW_MAX_PX = 1600     # longest edge of a generated photo preview


# Front-end + demo fixtures are PACKAGE DATA (cartographer/editor/{web,examples}), read via
# importlib.resources so they resolve identically from a checkout and from inside the zipapp. The rest
# of the server only ever calls _web_asset(rel) / _example_bytes(name).
import importlib.resources as _res


def _read_data(subdir, parts):
    if not parts or any(p in ("", ".", "..") for p in parts):
        return None                                 # empty or path-escaping -> not found
    try:
        t = _res.files("cartographer.editor").joinpath(subdir, *parts)
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
    already holds it."""
    path = os.path.join(workspace, CONTROL, EDITOR_LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+")
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


# The records whose `user_decision`s the editor answers (BLD-editor_answers_every_question): the three decision records,
# and geotag's execution summary, whose fingerprint mismatches each ask whether the photo's changed content stands.
_RECORDS = (("time", TIME_NAME), ("drift", DRIFT_NAME), ("gps", GPS_NAME), ("execution", EXECUTION_NAME))


def _read_record(path):
    """(raw bytes, or None when the record is absent) of a decision record — read once, so what is shown and
    what is hashed are the same bytes."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _record_hash(raw):
    """The SHA-256 of a decision record's bytes, or None for a record that is absent."""
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def _parse_record(raw, name):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError as e:
        return {"_error": f"could not read {name}: {e}"}


_HOST_ZONES = None


def _host_zones():
    """The timezone names geotag accepts on this host: every zone its zone database holds that
    `valid_iana_timezone` takes — the very check geotag's plan makes (RUL-checked_timezones). The editor checks a
    zone against this list, never the browser's own, which may know a name the host does not (`US/Eastern` on a
    host without the legacy names) and so let a zone be saved that the plan then refuses."""
    global _HOST_ZONES
    if _HOST_ZONES is None:
        import zoneinfo
        _HOST_ZONES = sorted(z for z in zoneinfo.available_timezones() if photos_utils.valid_iana_timezone(z))
    return _HOST_ZONES


def _device_groups(cfg):
    return ((cfg or {}).get("camera_time_and_timezone_policy") or {}).get("device_groups")


def _camera_question(workspace, raw_config):
    """The camera groups geotag stops on, not classed by the configuration (BLD-editor_lists_new_camera_groups): each with
    its photos' count, the first three of them and the identity prep found, and a `user_decision.device_class` the
    editor answers — `phones` or `fixed_clock_cameras`, the array of `device_groups` it is written into. Found from the
    handoff's photos under photos by destination as geotag finds them (`unclassified_camera_groups`). {_error} when the
    configuration or the handoff cannot be read; no groups without a handoff."""
    if raw_config is None:
        return {"groups": {}}
    cfg = _parse_record(raw_config, CONFIG_NAME)
    if not isinstance(cfg, dict) or "_error" in cfg:
        return cfg if isinstance(cfg, dict) else {"_error": f"{CONFIG_NAME} must be a JSON object"}
    try:
        handoff = _parse_record(_read_record(os.path.join(workspace, CONTROL, HANDOFF_NAME)), HANDOFF_NAME)
    except OSError as e:
        return {"_error": f"could not read {HANDOFF_NAME}: {e}"}
    if isinstance(handoff, dict) and "_error" in handoff:
        return handoff
    facts = {g.get("group_key"): g for g in ((handoff or {}).get("camera_groups") or []) if isinstance(g, dict)}
    groups = {}
    for key, paths in photos_2_geotag.unclassified_camera_groups(handoff, cfg).items():
        groups[key] = {"files": len(paths), "examples": paths[:3],
                       "identity": (facts.get(key) or {}).get("contributing_identity_fields") or {},
                       "user_decision": {"device_class": ""}, "requires_user_input": True,
                       "stale_user_decision": False}
    return {"groups": groups}


def _load_artifacts(workspace):
    """Return {workspace, demo, time, drift, gps, execution, hashes, zones}. `hashes` holds the SHA-256 of each record's bytes
    as loaded (None for one absent); a save carries them back, so it is refused when a record has changed
    since (RUL-save_only_what_was_shown). `zones` is the host's list of timezones geotag accepts (`_host_zones`).
    Demo mode loads requires-input fixtures."""
    if workspace:
        cd = os.path.join(workspace, CONTROL)
        out = {"workspace": os.path.abspath(workspace), "demo": False, "hashes": {}, "zones": _host_zones()}
        for key, name in _RECORDS:
            try:
                raw = _read_record(os.path.join(cd, name))
            except OSError as e:
                out[key], out["hashes"][key] = {"_error": f"could not read {name}: {e}"}, None
                continue
            out[key], out["hashes"][key] = _parse_record(raw, name), _record_hash(raw)
        # the configuration, as the class of a new camera group is written into it: its hash, like a record's
        try:
            raw = _read_record(os.path.join(cd, CONFIG_NAME))
        except OSError as e:
            out["cameras"], out["hashes"]["cameras"] = {"_error": f"could not read {CONFIG_NAME}: {e}"}, None
            return out
        out["cameras"], out["hashes"]["cameras"] = _camera_question(workspace, raw), _record_hash(raw)
        return out
    return {"workspace": None, "demo": True, "hashes": {}, "zones": _host_zones(),
            "time": _example_json("photos-21-time-decisions.requires-input.json"),
            "drift": _example_json("photos-22-gps-drift-validation.requires-input.json"),
            "gps": _example_json("photos-23-gps-decisions.requires-input.json"),
            "execution": None,                          # no execution in the demo: nothing has been written
            "cameras": {"groups": {}}}


def _write_json(path, obj):
    """Deterministic, atomic write matching the pipeline's write_json_artifact (sorted, indented)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    photos_utils.replace_durably(tmp, path)


def _edit_cell(art, e):
    """The cell of `art` the edit `e` is for, or None when the record holds no such cell."""
    kind = e.get("kind")
    if kind == "fingerprint":                   # photos-25: a photo whose content changed after a write, by its path
        cell = next((m for m in (art or {}).get("fingerprint_mismatches") or []
                     if isinstance(m, dict) and m.get("relative_path") == e.get("path")), None)
        return cell if isinstance(cell, dict) else None
    d = ((art or {}).get("destinations") or {}).get(e.get("dest"))
    if not isinstance(d, dict):
        return None
    if kind == "timezone":
        cell = d.get("destination_timezone")
    elif kind == "offset":
        cell = (d.get("camera_group_time_decisions") or {}).get(e.get("key"))
    elif kind == "reading":                     # a photo's time at a daylight-saving change, keyed by its path
        cell = (d.get("local_time_readings") or {}).get(e.get("key"))
    elif kind == "unidentified":                # the destination's files naming no camera
        cell = d.get("unidentified_files")
    elif kind == "changed":                     # a photo's time changed since geotag wrote it, keyed by its path
        cell = (d.get("changed_times") or {}).get(e.get("key"))
    elif kind == "drift":
        cell = (d.get("drift_decisions") or {}).get(e.get("key"))
    elif kind == "fallback":
        cell = d.get("folder_fallback")
    elif kind == "review":
        cell = next((r for r in (d.get("gps_decisions") or {}).get("review_items") or []
                     if r.get("relative_path") == e.get("path")), None)
    else:
        cell = None
    return cell if isinstance(cell, dict) else None


def _unapplicable_edits(art, edits):
    """The edits that name no cell `art` holds, or carry no decision to write — each a reason to refuse the
    save rather than drop the edit (RUL-save_only_what_was_shown)."""
    return [e for e in edits if _edit_cell(art, e) is None or not isinstance(e.get("user_decision"), dict)]


def _edit_label(e):
    what = e.get("path") or e.get("key")
    if e.get("kind") == "fingerprint":
        return f"fingerprint mismatch of {what}"
    return f"the {e.get('kind')} decision of {e.get('dest')}" + (f" ({what})" if what else "")


def _apply_edits(art, edits):
    """Apply each edit's `user_decision` to the matching cell in `art`, in place. ONLY `user_decision`
    is ever written — every other field is left exactly as geotag produced it, so the round-trip
    conforms regardless of what the client sent. Returns the count applied. `_save` refuses an edit this
    would pass over (`_unapplicable_edits`) before calling it."""
    applied = 0
    for e in edits:
        cell = _edit_cell(art, e)
        if cell is not None and isinstance(e.get("user_decision"), dict):
            cell["user_decision"] = e["user_decision"]
            applied += 1
    return applied


def _classed_config(workspace, raw, edits):
    """(the configuration with each named camera group put in the array its edit gives and out of the other, None) — or
    (None, why it is refused): a configuration that cannot be read, a group it classes already, a class that is not one
    of the two arrays, or a result `load_config` would refuse (BLD-editor_writes_device_groups). That setting alone
    changes (RUL-editor_classes_camera_group)."""
    cfg = _parse_record(raw, CONFIG_NAME)
    if not isinstance(cfg, dict) or "_error" in cfg:
        return None, f"cannot read {CONFIG_NAME} to class the camera group(s); nothing was saved"
    dg = _device_groups(cfg)
    if not isinstance(dg, dict) or not all(isinstance(dg.get(a), list) for a in DEVICE_CLASSES):
        return None, f"{CONFIG_NAME} holds no device_groups with its two lists; nothing was saved"
    unclassed = set(_camera_question(workspace, raw).get("groups") or {})
    for e in edits:
        key, cls = e.get("key"), (e.get("user_decision") or {}).get("device_class") \
            if isinstance(e.get("user_decision"), dict) else None
        if e.get("kind") != "camera" or key not in unclassed:
            return None, (f"{CONFIG_NAME} classes no new camera group {key!r} to answer (it may be classed "
                          "already) — reload the editor; nothing was saved")
        if cls not in DEVICE_CLASSES:
            return None, f"the class of camera group {key!r} must be one of {', '.join(DEVICE_CLASSES)}; nothing was saved"
        other = DEVICE_CLASSES[1 - DEVICE_CLASSES.index(cls)]
        if key not in dg[cls]:
            dg[cls].append(key)
        dg[other] = [k for k in dg[other] if k != key]
    try:
        photos_utils.check_config(cfg, workspace)
    except ValueError as e:
        return None, f"{e} — nothing was saved"
    return cfg, None


def _save(workspace, payload):
    """Write the posted user_decision edits back into the workspace's decision artifacts."""
    # A save changes the workspace, so it holds the workspace's lock (BLD-editor_save_locks): a geotag plan
    # running now reads these records and rewrites them, and would overwrite a save landing in between.
    # Fail-fast like every run; the editor's display reads stay unlocked (each file is replaced whole).
    lock = photos_utils.WorkspaceLock(workspace, create=False)
    if not lock.acquire():
        return {"ok": False, "error": "a run is in progress on this workspace — save again when it finishes"}
    try:
        if photos_utils.is_sealed(workspace):   # read under the lock; the console reaches here without serve()'s check
            return {"ok": False, "error": "workspace is sealed (already merged): decisions can no longer change"}
        cd = os.path.join(workspace, CONTROL)
        cfg_path = os.path.join(cd, CONFIG_NAME)
        try:
            raws = {key: _read_record(os.path.join(cd, name)) for key, name in _RECORDS}
            raw_cfg = _read_record(cfg_path)
        except OSError as e:
            return {"ok": False, "error": f"cannot read the decision records ({e}); nothing was saved"}
        current = {key: _record_hash(raw) for key, raw in raws.items()}
        current["cameras"] = _record_hash(raw_cfg)      # the configuration, a camera group's class written into it
        edits = {key: (payload or {}).get(key) or [] for key, _name in _RECORDS}
        cameras = (payload or {}).get("cameras") or []
        if not any(edits.values()) and not cameras:
            return {"ok": True, "written": [], "hashes": current}
        # Save only what was shown (RUL-save_only_what_was_shown): the edits were made against the records as
        # the editor loaded them. Each of them is compared, under the lock, with the hash the page was
        # given for it before any is written — a geotag plan may have rewritten one since, and an edit made
        # against the old one would then land on decisions the user never saw.
        loaded = (payload or {}).get("hashes")
        if not isinstance(loaded, dict):
            return {"ok": False, "error": "this save does not say which decision records it was made from — "
                                          "reload the editor and make your edits again; nothing was saved"}
        changed = [name for key, name in _RECORDS if key not in loaded or loaded[key] != current[key]]
        # A camera group's class is written into the configuration only over the one the editor showed; a
        # configuration edited by hand since does not hold back a save of the decisions alone.
        if cameras and loaded.get("cameras") != current["cameras"]:
            changed.append(CONFIG_NAME)
        if changed:
            return {"ok": False, "error": f"{', '.join(changed)} changed since the editor loaded it (a geotag "
                                          "plan may have rewritten it) — reload the editor to see the decisions "
                                          "as they are now, then make your edits again; nothing was saved"}
        arts = {}
        for key, name in _RECORDS:
            if not edits[key]:
                continue
            art = _parse_record(raws[key], name)
            if not isinstance(art, dict) or "_error" in art:
                return {"ok": False, "error": f"cannot read {name} to update; nothing was saved"}
            missing = _unapplicable_edits(art, edits[key])
            if missing:
                return {"ok": False, "error": f"{name} holds no {_edit_label(missing[0])} to save — reload the "
                                              "editor and make your edits again; nothing was saved"}
            arts[key] = art
        cfg = None
        if cameras:
            cfg, why = _classed_config(workspace, raw_cfg, cameras)
            if cfg is None:
                return {"ok": False, "error": why}
        written = []
        for key, name in _RECORDS:
            if key in arts:
                _apply_edits(arts[key], edits[key])
                _write_json(os.path.join(cd, name), arts[key])
                written.append(name)
                current[key] = _record_hash(_read_record(os.path.join(cd, name)))
        if cfg is not None:
            # the configuration written whole, every other setting keeping its value (BLD-editor_writes_device_groups)
            photos_utils.write_json_artifact(cfg_path, cfg)
            written.append(CONFIG_NAME)
            current["cameras"] = _record_hash(_read_record(cfg_path))
        return {"ok": True, "written": written, "hashes": current}
    finally:
        lock.release()


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
        if path != "/api/save":
            return self._send(404, {"error": "not found"})
        if self.workspace is None:
            return self._send(403, {"ok": False, "error": "demo mode is read-only — "
                                    "run `photos-cartographer edit` inside a workspace to edit"})
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
    "initialized workspace, and on a sealed (already merged) one). You confirm/correct the time, GPS and drift decisions geotag surfaced; "
    "Save writes them back; then re-run `photos-cartographer geotag plan` in a terminal to regenerate from "
    "your edits and reload. Open the printed URL (reachable over the network so you can use it "
    "from another machine's browser); Ctrl-C to stop.\n\n"
    "  --demo   read-only tour on bundled fixtures (no workspace; nothing is written).\n\n"
    "Loop: geotag plan -> edit -> geotag plan -> ... -> geotag execute -> geotag finalize."
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
              f"(no {CONTROL}/{GUARD_NAME}). Run `photos-cartographer prep plan` then `photos-cartographer prep execute` here first, "
              f"or use `photos-cartographer edit --demo` for a read-only fixtures tour.", file=sys.stderr)
        sys.exit(2)
    # A sealed (merged) workspace is final (RUL-editor_refuses_sealed): its decisions may no longer change.
    if workspace and photos_utils.is_sealed(workspace):
        print(f"{os.path.abspath(workspace)} is SEALED (already merged): the decision editor will not "
              f"open it. A sealed workspace is final.", file=sys.stderr)
        if photos_utils.likely_new_dump(workspace):
            print(f"A likely new dump is present (at the workspace root or in "
                  f"{photos_utils.workspace_folders(workspace)['sources']}/). Move it into a fresh workspace by hand — "
                  f"the editor left it exactly where it is.", file=sys.stderr)
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
            # The editor works on the cwd (no workspace argument): the way out is to close the other one, or
            # to run this one from another workspace's folder.
            print(f"another decision editor (or a console whose Edit tab was opened) has this workspace open "
                  f"(pid {d.get('pid', '?')} on {d.get('host', '?')}, since {d.get('started_at', '?')}). "
                  f"Close it, or run this one from another workspace's folder.", file=sys.stderr)
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
    hint = photos_utils.ssh_tunnel_hint(bound_port, host)
    if hint:
        print("  loopback-only — from your local machine, tunnel then open the URL above:")
        print(f"    {hint}")
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
    """Standalone entry (`python -m cartographer.editor.server`); the normal path is
    `photos-cartographer edit`, which calls run()/serve() directly."""
    parser = argparse.ArgumentParser(prog="cartographer.editor.server", description=EDIT_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
