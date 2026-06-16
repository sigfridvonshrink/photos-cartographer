"""Tests for the decision-editor server (`ingest/decision-editor/decision-editor.unbundled`).

Covers the request-independent helpers (port auto-bump, machine-IP detection, the single-editor lock,
JSON read/write, the user_decision-only edit apply, and save round-trip) plus a few end-to-end HTTP
checks of the GET/POST routes. Loaded via tests/conftest.py's SourceFileLoader, like the pipeline
scripts.
"""
import copy
import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

import decision_editor_serve as serve

# Demo fixtures are package data now; in a checkout they're a real dir beside the server module.
EXAMPLES = os.path.join(os.path.dirname(serve.__file__), "examples")
HAVE_MAGICK = bool(shutil.which("magick"))


def _make_jpeg(path):
    subprocess.run(["magick", "-size", "64x48", "xc:navy", str(path)], check=True)


# --------------------------------------------------------------------------- helpers

def _workspace_with_fixtures(tmp_path):
    """A workspace dir whose .photos-ingest/ holds the two requires-input example artifacts."""
    cd = tmp_path / serve.CONTROL
    cd.mkdir(parents=True)
    for src, dst in (("photos-21-time-decisions.requires-input.json", serve.TIME_NAME),
                     ("photos-22-gps-decisions.requires-input.json", serve.GPS_NAME)):
        (cd / dst).write_text((open(os.path.join(EXAMPLES, src))).read())
    return str(tmp_path)


@contextmanager
def _running(workspace):
    """Run the real Handler in a background thread on an OS-assigned port; yield its base URL."""
    old = serve.Handler.workspace
    serve.Handler.workspace = workspace
    httpd = serve._bind("127.0.0.1", 0, serve.Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        serve.Handler.workspace = old


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def _post_json(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# --------------------------------------------------------------------------- _bind (port auto-bump)

def test_bind_uses_a_free_port():
    srv = serve._bind("127.0.0.1", 0, serve.Handler)  # 0 → OS assigns a free port
    try:
        assert srv.server_address[1] != 0
    finally:
        srv.server_close()


def test_bind_bumps_past_a_busy_port():
    held = serve._bind("127.0.0.1", 0, serve.Handler)
    busy = held.server_address[1]
    try:
        moved = serve._bind("127.0.0.1", busy, serve.Handler)
        try:
            assert moved.server_address[1] > busy  # busy port is never an error — it moves up
        finally:
            moved.server_close()
    finally:
        held.server_close()


def test_bind_reraises_non_addrinuse():
    # A non-local address fails to bind with something other than EADDRINUSE; _bind must not swallow it.
    with pytest.raises(OSError):
        serve._bind("203.0.113.1", 0, serve.Handler)  # TEST-NET-3: not an address on this machine


# --------------------------------------------------------------------------- _machine_ip

def test_machine_ip_is_a_valid_ipv4():
    ip = serve._machine_ip()
    assert isinstance(ip, str) and ip
    socket.inet_aton(ip)  # raises if not a dotted-quad IPv4


# --------------------------------------------------------------------------- editor lock

def test_lock_acquire_writes_owner_record(tmp_path):
    lock, owner = serve._acquire_editor_lock(str(tmp_path))
    try:
        assert owner is None and lock is not None
        path = tmp_path / serve.CONTROL / serve.EDITOR_LOCK
        assert path.is_file()
        rec = json.loads(path.read_text())
        assert rec["pid"] == os.getpid()
        assert rec["host"] and rec["started_at"]
    finally:
        lock.close()


def test_lock_creates_control_dir(tmp_path):
    assert not (tmp_path / serve.CONTROL).exists()
    lock, owner = serve._acquire_editor_lock(str(tmp_path))
    try:
        assert lock is not None
        assert (tmp_path / serve.CONTROL).is_dir()
    finally:
        lock.close()


def test_lock_blocks_second_editor(tmp_path):
    first, _ = serve._acquire_editor_lock(str(tmp_path))
    try:
        second, owner = serve._acquire_editor_lock(str(tmp_path))
        assert second is None  # refused while another editor holds it
        assert owner["pid"] == os.getpid()
    finally:
        first.close()


def test_lock_released_after_close(tmp_path):
    first, _ = serve._acquire_editor_lock(str(tmp_path))
    first.close()  # closing the file releases the flock
    again, owner = serve._acquire_editor_lock(str(tmp_path))
    try:
        assert again is not None and owner is None
    finally:
        again.close()


# --------------------------------------------------------------------------- _read_json / _write_json

def test_read_json_missing_returns_none(tmp_path):
    assert serve._read_json(str(tmp_path / "nope.json")) is None


def test_read_json_bad_returns_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    out = serve._read_json(str(p))
    assert isinstance(out, dict) and "_error" in out


def test_write_json_is_deterministic_atomic_and_round_trips(tmp_path):
    p = tmp_path / "out.json"
    serve._write_json(str(p), {"b": 1, "a": {"y": 2, "x": 1}})
    text = p.read_text()
    assert json.loads(text) == {"b": 1, "a": {"y": 2, "x": 1}}
    assert text == json.dumps({"b": 1, "a": {"y": 2, "x": 1}}, indent=2, sort_keys=True)
    assert not (tmp_path / "out.json.tmp").exists()  # temp file renamed away


# --------------------------------------------------------------------------- _load_artifacts

def test_load_artifacts_demo_mode():
    art = serve._load_artifacts(None)
    assert art["demo"] is True and art["workspace"] is None
    assert "destinations" in art["time"] and "destinations" in art["gps"]


def test_load_artifacts_workspace(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    art = serve._load_artifacts(ws)
    assert art["demo"] is False
    assert art["workspace"] == os.path.abspath(ws)
    assert "destinations" in art["time"] and "destinations" in art["gps"]


# --------------------------------------------------------------------------- _apply_edits

def _time_art():
    return json.load(open(os.path.join(EXAMPLES, "photos-21-time-decisions.requires-input.json")))


def _gps_art():
    return json.load(open(os.path.join(EXAMPLES, "photos-22-gps-decisions.requires-input.json")))


def test_apply_edits_timezone_touches_only_user_decision():
    art = _time_art()
    dest = "6-photos-by-dest/Japan"
    cell = art["destinations"][dest]["destination_timezone"]
    proposal_before = copy.deepcopy(cell.get("proposal"))
    n = serve._apply_edits(art, [{"dest": dest, "kind": "timezone",
                                  "user_decision": {"accept_proposed_timezone": False,
                                                    "manual_iana_timezone": "Asia/Tokyo"}}])
    assert n == 1
    assert cell["user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"
    assert cell.get("proposal") == proposal_before  # everything but user_decision is untouched


def test_apply_edits_offset_by_group_key():
    art = _time_art()
    dest, key = "6-photos-by-dest/Japan", "SONY|ILCE-6400|A"
    n = serve._apply_edits(art, [{"dest": dest, "kind": "offset", "key": key,
                                  "user_decision": {"accept_proposal": False,
                                                    "manual_offset_seconds": 42}}])
    assert n == 1
    cell = art["destinations"][dest]["camera_group_time_decisions"][key]
    assert cell["user_decision"]["manual_offset_seconds"] == 42


def test_apply_edits_fallback_and_review():
    art = _gps_art()
    dest = "6-photos-by-dest/Japan"
    review_path = "6-photos-by-dest/Japan/blocked-a.arw"
    n = serve._apply_edits(art, [
        {"dest": dest, "kind": "fallback",
         "user_decision": {"accept_proposal": False, "fallback_lat": 35.0, "fallback_lon": 139.0}},
        {"dest": dest, "kind": "review", "path": review_path,
         "user_decision": {"accept_unlocated": False, "manual_lat": 35.6, "manual_lon": 139.7}},
    ])
    assert n == 2
    d = art["destinations"][dest]
    assert d["folder_fallback"]["user_decision"]["fallback_lat"] == 35.0
    item = next(r for r in d["gps_decisions"]["review_items"] if r["relative_path"] == review_path)
    assert item["user_decision"]["manual_lat"] == 35.6


def test_apply_edits_ignores_unknown_targets():
    art = _time_art()
    n = serve._apply_edits(art, [
        {"dest": "6-photos-by-dest/Nowhere", "kind": "timezone", "user_decision": {"x": 1}},
        {"dest": "6-photos-by-dest/Japan", "kind": "bogus", "user_decision": {"x": 1}},
        {"dest": "6-photos-by-dest/Japan", "kind": "timezone", "user_decision": "not-a-dict"},
    ])
    assert n == 0


# --------------------------------------------------------------------------- _save

def test_save_round_trips_only_user_decision(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    before = json.load(open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME)))
    res = serve._save(ws, {"time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                                     "user_decision": {"accept_proposed_timezone": False,
                                                       "manual_iana_timezone": "Asia/Tokyo"}}]})
    assert res == {"ok": True, "written": [serve.TIME_NAME]}
    after = json.load(open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME)))
    edited = after["destinations"]["6-photos-by-dest/Japan"]["destination_timezone"]
    assert edited["user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"
    # Strip user_decision everywhere and the artifact must be byte-for-byte what it was.
    def _strip(a):
        a = copy.deepcopy(a)
        for d in a["destinations"].values():
            for cell in (d.get("destination_timezone"), d.get("folder_fallback")):
                if isinstance(cell, dict):
                    cell.pop("user_decision", None)
            for cell in (d.get("camera_group_time_decisions") or {}).values():
                cell.pop("user_decision", None)
        return a
    assert _strip(after) == _strip(before)


def test_save_no_edits_writes_nothing(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    assert serve._save(ws, {}) == {"ok": True, "written": []}


def test_save_unreadable_artifact_errors(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    (tmp_path / serve.CONTROL / serve.TIME_NAME).write_text("{broken")
    res = serve._save(ws, {"time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                                     "user_decision": {"x": 1}}]})
    assert res["ok"] is False and "error" in res


# --------------------------------------------------------------------------- HTTP routes

def test_http_get_artifacts_demo():
    with _running(None) as base:
        status, body, ctype = _get(base + "/api/artifacts")
        assert status == 200 and "json" in ctype
        data = json.loads(body)
        assert data["demo"] is True and "destinations" in data["time"]


def test_http_get_static_index_and_404():
    with _running(None) as base:
        status, body, ctype = _get(base + "/")
        assert status == 200 and "html" in ctype and b"Decision editor" in body
        assert _get(base + "/does-not-exist.txt")[0] == 404


def test_http_post_save_is_403_in_demo():
    with _running(None) as base:
        status, data = _post_json(base + "/api/save", {"time": []})
        assert status == 403 and data["ok"] is False


def test_http_post_unknown_route_404():
    with _running(None) as base:
        status, data = _post_json(base + "/api/nope", {})
        assert status == 404


# --------------------------------------------------------------------------- photo preview

def test_safe_workspace_path_blocks_escape(tmp_path):
    ws = str(tmp_path)
    assert serve._safe_workspace_path(ws, "../../etc/passwd") is None
    assert serve._safe_workspace_path(ws, "a/../../b") is None
    inside = serve._safe_workspace_path(ws, "6-photos-by-dest/x.arw")
    assert inside == os.path.join(os.path.abspath(ws), "6-photos-by-dest/x.arw")
    # A leading slash is neutralised to workspace-relative (stays inside, never reaches the real root).
    neutralised = serve._safe_workspace_path(ws, "/etc/passwd")
    assert neutralised.startswith(os.path.abspath(ws) + os.sep)


def test_photo_preview_missing_file_is_none(tmp_path):
    assert serve._photo_preview(str(tmp_path), "nope.jpg") is None


@pytest.mark.skipif(not HAVE_MAGICK, reason="ImageMagick not installed")
def test_photo_preview_returns_jpeg(tmp_path):
    sub = tmp_path / "6-photos-by-dest" / "Japan"
    sub.mkdir(parents=True)
    _make_jpeg(sub / "pic.jpg")
    data = serve._photo_preview(str(tmp_path), "6-photos-by-dest/Japan/pic.jpg")
    assert data and data[:2] == b"\xff\xd8"  # JPEG start-of-image


def test_http_photo_404_in_demo():
    with _running(None) as base:
        assert _get(base + "/api/photo?path=x.jpg")[0] == 404


def test_http_photo_missing_and_escape_404(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    with _running(ws) as base:
        assert _get(base + "/api/photo?path=6-photos-by-dest/Japan/nope.jpg")[0] == 404
        assert _get(base + "/api/photo?path=../../../../etc/passwd")[0] == 404


@pytest.mark.skipif(not HAVE_MAGICK, reason="ImageMagick not installed")
def test_http_photo_serves_jpeg(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    sub = os.path.join(ws, "6-photos-by-dest", "Japan")
    os.makedirs(sub)
    _make_jpeg(os.path.join(sub, "pic.jpg"))
    with _running(ws) as base:
        status, body, ctype = _get(base + "/api/photo?path=6-photos-by-dest/Japan/pic.jpg")
        assert status == 200 and "image/jpeg" in ctype and body[:2] == b"\xff\xd8"


def test_http_serves_vendored_leaflet():
    with _running(None) as base:
        status, body, ctype = _get(base + "/vendor/leaflet/leaflet.js")
        assert status == 200 and "javascript" in ctype and b"Leaflet" in body
        assert _get(base + "/vendor/leaflet/images/marker-icon.png")[2] == "image/png"


# --------------------------------------------------------------------------- re-run calibration
# (calibration now ships in the same package as the editor, so it is always runnable — the old
# "missing pipeline" cases no longer apply; the gpx_root gate below is the remaining dependency.)

def test_rerun_surfaces_calibration_blockers(tmp_path):
    # A bare dir is not an initialized workspace: calibration's preflight blocks (exit 2) and mutates
    # nothing — which is exactly the failure the editor must surface, so this exercises the real plumbing.
    r = serve._rerun(str(tmp_path))
    assert r["ok"] is False and r["returncode"] == 2
    assert "photos-ingest prep" in (r.get("stderr") or "")


# ------------------------------------------------------------ folder-dependency gate (_environment)

def _ws_with_gpx_config(tmp_path, gpx_root):
    cd = tmp_path / serve.CONTROL
    cd.mkdir(parents=True, exist_ok=True)
    (cd / serve.CONFIG_NAME).write_text(json.dumps({"gpx_root": gpx_root}))
    return str(tmp_path)


def test_environment_no_config_does_not_block(tmp_path):
    (tmp_path / serve.CONTROL).mkdir()
    env = serve._environment(str(tmp_path))
    assert env["calibration_present"] is True       # calibration ships in this package — always present
    assert env["gpx_configured"] is False and env["deps_ok"] is True and env["missing"] == []


def test_environment_empty_gpx_root_does_not_block(tmp_path):
    env = serve._environment(_ws_with_gpx_config(tmp_path, ""))
    assert env["gpx_configured"] is False and env["deps_ok"] is True


def test_environment_visible_gpx_root_is_ok(tmp_path):
    gpx = tmp_path / "gpx"; gpx.mkdir()
    env = serve._environment(_ws_with_gpx_config(tmp_path, str(gpx)))
    assert env["gpx_available"] is True and env["deps_ok"] is True
    assert env["gpx_root"] == os.path.realpath(str(gpx))


def test_environment_missing_gpx_root_blocks(tmp_path):
    env = serve._environment(_ws_with_gpx_config(tmp_path, str(tmp_path / "not-here")))
    assert env["gpx_available"] is False and env["deps_ok"] is False
    assert any("gpx_root" in m for m in env["missing"])


def test_load_artifacts_carries_environment(tmp_path):
    art = serve._load_artifacts(_ws_with_gpx_config(tmp_path, str(tmp_path / "not-here")))
    assert art["environment"]["deps_ok"] is False


def test_rerun_refuses_when_gpx_root_off_machine(tmp_path):
    # Re-run must not silently regenerate decisions without the GPX the workspace depends on: the guard
    # short-circuits BEFORE invoking calibration (no returncode), so good GPX-derived decisions survive.
    r = serve._rerun(_ws_with_gpx_config(tmp_path, str(tmp_path / "not-here")))
    assert r["ok"] is False and "gpx_root" in r["error"] and "returncode" not in r


def test_http_rerun_403_in_demo():
    with _running(None) as base:
        status, data = _post_json(base + "/api/rerun", {})
        assert status == 403 and data["ok"] is False


def test_http_rerun_invokes_calibration(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    with _running(ws) as base:
        status, data = _post_json(base + "/api/rerun", {})
    assert status == 200 and data["ok"] is False and data["returncode"] == 2


def test_http_post_save_writes_to_workspace(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    with _running(ws) as base:
        status, data = _post_json(base + "/api/save", {
            "time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                      "user_decision": {"accept_proposed_timezone": False,
                                        "manual_iana_timezone": "Asia/Tokyo"}}]})
        assert status == 200 and data == {"ok": True, "written": [serve.TIME_NAME]}
    saved = json.load(open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME)))
    cell = saved["destinations"]["6-photos-by-dest/Japan"]["destination_timezone"]
    assert cell["user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"
