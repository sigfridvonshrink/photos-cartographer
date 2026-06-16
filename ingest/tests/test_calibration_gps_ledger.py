"""Phase 6c-2 (calibration) — the reversible manual-GPS pre-state ledger + revert ops (§24.1).

The revert target is prep's recorded original GPS (the handoff's native_gps), pinned once; a withdrawn
manual override plans + applies a revert that restores it (or clears added GPS), then consumes the
pin. Manual-GPS only. exiftool-write + fingerprint are mocked. From conftest.py.
"""
import json
import os
import sys

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
BYDEST = "6-photos-by-dest"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


# --- pure helpers -----------------------------------------------------------

def test_handoff_pre_state():
    assert cal._handoff_pre_state({"lat": 50.0, "lon": 4.0, "processing_method": "gps"}) == {
        "present": True, "GPSLatitude": 50.0, "GPSLongitude": 4.0, "GPSProcessingMethod": "gps"}
    assert cal._handoff_pre_state(None) == {"present": False}
    assert cal._handoff_pre_state({"lat": None, "lon": None}) == {"present": False}


def test_revert_tags():
    assert cal._revert_tags({"present": True, "GPSLatitude": 1, "GPSLongitude": 2, "GPSProcessingMethod": "m"}) == {
        "GPSLatitude": 1, "GPSLongitude": 2, "GPSProcessingMethod": "m"}
    assert cal._revert_tags({"present": False}) == {
        "GPSLatitude": "", "GPSLongitude": "", "GPSProcessingMethod": ""}     # clears the added GPS


def test_ledger_cache_pin_once_get_consume(tmp_path):
    (tmp_path / ".photos-ingest").mkdir()
    c = cal.CalibrationCache(str(tmp_path))
    c.ledger_pin("fp1", "a.jpg", {"present": False}, "t0")
    c.ledger_pin("fp1", "a.jpg", {"present": True, "GPSLatitude": 9}, "t1")     # pin-once -> ignored
    assert c.ledger_get("fp1")["pre_state"] == {"present": False}              # the original stands
    assert c.ledger_get("fp1")["captured_at"] == "t0"
    assert len(c.ledger_all()) == 1
    c.ledger_consume("fp1")
    assert c.ledger_get("fp1") is None
    c.close()


# --- build_executable_plan: revert-op planning ------------------------------

def _model(rel, dest, *, native=False):
    return {"relative_path": rel, "destination": dest, "has_native_gps": native,
            "content_fingerprint": "fp-" + rel, "size": 10, "mtime_ns": 1,
            "native_gps": ({"lat": 1.0, "lon": 2.0, "processing_method": "gps"} if native else None)}


def _row(rel):
    return {"relative_path": rel, "resolved_utc": "2024-07-03T12:00:00Z", "resolved_utc_status": "valid"}


def _plan_wf(tmp_path, files, *, manual=None):
    ws = tmp_path / "ws"; (ws / ".photos-ingest").mkdir(parents=True); ctl = ws / ".photos-ingest"
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"cache_fingerprint": "pcf"}))
    dests = {f["destination"] for f in files}
    reviews = {d: [] for d in dests}
    for rel, (lat, lon) in (manual or {}).items():
        d = next(f["destination"] for f in files if f["relative_path"] == rel)
        reviews[d].append({"relative_path": rel, "user_decision": {"manual_lat": lat, "manual_lon": lon}})
    time_art = {"status": "complete", "destinations": {
        d: {"destination_timezone": {"effective_iana_timezone": "Europe/Brussels"}} for d in dests}}
    gps_art = {"status": "complete", "destinations": {
        d: {"folder_fallback": {"effective_fallback": None},
            "gps_decisions": {"review_items": reviews[d]}} for d in dests}}
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(time_art))
    (ctl / "photos-21a-gps-drift-validation.json").write_text(
        json.dumps({"status": "complete", "destinations": {}}))
    (ctl / "photos-22-gps-decisions.json").write_text(json.dumps(gps_art))
    wf = cal.CalibrationWorkflow(str(ws)); wf.handoff = {"cache_fingerprint": "pcf"}; wf._gpx_fingerprint = "g"
    gpx = cal.GPXIndex(""); gpx.points = []
    return wf, time_art, gps_art, gpx


def _reverts(plan):
    return [o for dd in plan["destinations"].values() for o in dd["operations"]
            if o["type"] == "revert_manual_gps"]


def test_withdrawn_override_plans_revert(tmp_path):
    f = _model(f"{BYDEST}/T/a.jpg", f"{BYDEST}/T", native=True)        # now preserve_native (non-manual)
    wf, t, g, gpx = _plan_wf(tmp_path, [f])
    ledger = [{"content_fingerprint": "fp-" + f["relative_path"], "relative_path": f["relative_path"],
               "pre_state": {"present": False}, "captured_at": "t0"}]
    plan, _ = wf.build_executable_plan([f], [_row(f["relative_path"])], t, g, gpx, "rfp", ledger)
    rv = _reverts(plan)
    assert len(rv) == 1 and rv[0]["content_fingerprint"] == "fp-" + f["relative_path"]
    assert rv[0]["writes"] == {"GPSLatitude": "", "GPSLongitude": "", "GPSProcessingMethod": ""}  # clear


def test_still_manual_no_revert(tmp_path):
    rel = f"{BYDEST}/T/a.jpg"
    f = _model(rel, f"{BYDEST}/T")                                     # no native GPS
    wf, t, g, gpx = _plan_wf(tmp_path, [f], manual={rel: (10.0, 20.0)})  # still a manual lock
    ledger = [{"content_fingerprint": "fp-" + rel, "relative_path": rel,
               "pre_state": {"present": False}, "captured_at": "t0"}]
    plan, _ = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp", ledger)
    assert _reverts(plan) == []                                        # re-asserted, not reverted


def test_vanished_file_kept_no_revert(tmp_path):
    f = _model(f"{BYDEST}/T/a.jpg", f"{BYDEST}/T", native=True)
    wf, t, g, gpx = _plan_wf(tmp_path, [f])
    ledger = [{"content_fingerprint": "fp-gone", "relative_path": f"{BYDEST}/T/gone.jpg",
               "pre_state": {"present": True, "GPSLatitude": 5, "GPSLongitude": 6}, "captured_at": "t0"}]
    plan, _ = wf.build_executable_plan([f], [_row(f["relative_path"])], t, g, gpx, "rfp", ledger)
    assert _reverts(plan) == []                                        # missing file -> no op (entry kept elsewhere)


# --- execute: capture pins from prep, revert applies + consumes -------------

def _exec_ws(tmp_path, monkeypatch):
    """A workspace whose blocked no-GPS photo is resolved via an accepted folder fallback (-> a manual
    GPS apply), plus two native-GPS anchors that auto-resolve the camera offset. Driven to a ready
    photos-23 via `run` (timezone + fallback accepted)."""
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir(); (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True,
        write_corrected_filename_times=False)   # no renames -> re-plan after execute works without re-prep
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))

    def rec(rel, dto, gps=None):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": bool(gps)}
        if gps:
            parsed.update({"GPSLatitude": gps[0], "GPSLongitude": gps[1]})
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": bool(gps),
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec(f"{BYDEST}/T/a.arw", "2024:07:03 14:00:00", (50.0, 4.0)),
             rec(f"{BYDEST}/T/b.arw", "2024:07:03 15:00:00", (51.0, 5.0)),
             rec(f"{BYDEST}/T/c.arw", "2024:07:03 14:30:00")]            # no GPS -> blocked -> fallback
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))
    return ws, ctl


def _run(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-time-gps", cmd])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _mock_tools(monkeypatch, ws):
    # the write is content-invariant -> the post-write fingerprint equals the pinned precondition
    # ("fp-<relative path>"); no renames in this test, so the path is stable.
    monkeypatch.setattr(cal.CalibrationWorkflow, "_exiftool_write", lambda self, p, tags: True)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image",
                        staticmethod(lambda p: {"value": "fp-" + os.path.relpath(p, str(ws))}))


def _edit(ctl, name, fn):
    p = ctl / name; a = json.load(open(p)); fn(a); p.write_text(json.dumps(a))


def test_full_pin_then_withdraw_reverts_and_consumes(tmp_path, monkeypatch):
    ws, ctl = _exec_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    _run(monkeypatch, ws, "plan")                                       # photos-21: timezone needs input
    _edit(ctl, "photos-21-time-decisions.json", lambda a: a["destinations"][f"{BYDEST}/T"]
          ["destination_timezone"]["user_decision"].update({"accept_proposed_timezone": True}))
    _run(monkeypatch, ws, "plan")                                       # now photos-22 exists (c blocked)
    _edit(ctl, "photos-22-gps-decisions.json", lambda b: b["destinations"][f"{BYDEST}/T"]
          ["folder_fallback"]["user_decision"].update({"fallback_lat": 48.85, "fallback_lon": 2.35}))
    _run(monkeypatch, ws, "plan")                                       # c.arw now manual_fallback -> photos-23
    assert (ctl / "photos-23-executable-plan.json").exists()
    assert _run(monkeypatch, ws, "execute") == 0
    # pre-state pinned (c had no native GPS -> absent), manual GPS written
    db = cal.CalibrationCache(str(ws)); pinned = {e["relative_path"]: e["pre_state"] for e in db.ledger_all()}; db.close()
    assert pinned == {f"{BYDEST}/T/c.arw": {"present": False}}
    t1 = json.load(open(ctl / "photos-24-execution-summary.json"))["totals"]
    assert t1["metadata_gps_writes"] == 1 and t1["manual_gps_pre_states_captured"] == 1

    # idempotent re-execute (c still manual): pin-once -> not re-captured, ledger unchanged
    assert _run(monkeypatch, ws, "execute") == 0
    t2 = json.load(open(ctl / "photos-24-execution-summary.json"))["totals"]
    assert t2["manual_gps_pre_states_captured"] == 0                   # already pinned, skipped
    db = cal.CalibrationCache(str(ws)); assert len(db.ledger_all()) == 1; db.close()

    # WITHDRAW: drop the fallback, accept c as unlocated -> non-manual -> revert planned
    q = ctl / "photos-22-gps-decisions.json"; b = json.load(open(q))
    b["destinations"][f"{BYDEST}/T"]["folder_fallback"]["user_decision"].update({"fallback_lat": "", "fallback_lon": ""})
    b["destinations"][f"{BYDEST}/T"]["gps_decisions"]["review_items"] = [
        {"relative_path": f"{BYDEST}/T/c.arw", "user_decision": {"accept_unlocated": True}}]
    q.write_text(json.dumps(b))
    _run(monkeypatch, ws, "plan")
    plan = json.load(open(ctl / "photos-23-executable-plan.json"))
    assert any(o["type"] == "revert_manual_gps" for dd in plan["destinations"].values() for o in dd["operations"])
    assert _run(monkeypatch, ws, "execute") == 0
    s = json.load(open(ctl / "photos-24-execution-summary.json"))
    assert s["totals"]["manual_gps_reverts"] == 1
    db = cal.CalibrationCache(str(ws)); assert db.ledger_all() == []; db.close()   # consumed on restore
