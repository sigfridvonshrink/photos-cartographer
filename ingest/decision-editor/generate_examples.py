#!/usr/bin/env python3
"""Generate example decision artifacts (fixtures) for the decision editor.

These are produced by the REAL calibration decision builders (`build_time_decisions`,
`compute_resolved_utc`, `build_gps_decisions` in `ingest/photos-2-time-gps`) and written with the
real `write_json_artifact` serializer — they are guaranteed byte-identical to what a calibration run
would emit, not hand-authored. The *inputs* are a small synthetic photo set chosen to exercise the
interesting decision cases; the *outputs* are authentic.

It produces four fixtures under examples/, covering both files in both states:
  photos-21-time-decisions.requires-input.json   photos-21-time-decisions.complete.json
  photos-22-gps-decisions.requires-input.json     photos-22-gps-decisions.complete.json

The `complete` variants are produced exactly as the operator would: take the `requires-input`
artifact, fill in `user_decision` fields, and re-run the builder with it as the prior (the real
preservation/validation path).

Run from the repo root:  python3 ingest/decision-editor/generate_examples.py
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


def _load(name, filename):
    path = os.path.join(ING, filename)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


utils = _load("photos_utils", "photos_utils.py")
cal = _load("photos_2_time_gps", "photos-2-time-gps")

CAM_A = "SONY|ILCE-6400|A"          # fixed-clock camera, geotagged in Japan -> gpx self-anchor
CAM_B = "NIKON|D750|B"              # fixed-clock camera, no GPX -> manual-required offset
PHONE = "APPLE|iPhone15|P"          # smartphone -> no offset cell

BD = "6-photos-by-dest"
JP, KY, BE = f"{BD}/Japan", f"{BD}/Japan/Kyoto", f"{BD}/Belgium"


def _utc(h, m, s=0):
    return datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc)


def _gpx():
    # A short track 12:00:00Z..12:10:00Z, one point per minute, drifting east 4.000->4.002.
    idx = cal.GPXIndex("")
    idx.points = [cal.GPXPoint(50.0, round(4.0 + 0.0002 * m, 6), _utc(12, m), "trip-2024-07-03.gpx", m)
                  for m in range(11)]
    return idx


def _file(rel, key, naive, *, gps=None, raw_times=None):
    """One by-dest photo in the in-memory file-model shape build_file_model produces."""
    return {
        "relative_path": rel, "destination": os.path.dirname(rel), "media_class": "raw",
        "content_fingerprint": "fp-" + rel, "size": 100, "mtime_ns": 1,
        "camera_group_key": key, "source_naive_time": naive, "source_time_tag": "DateTimeOriginal",
        "has_timestamp": True, "native_gps": gps, "has_native_gps": bool(gps),
        "raw_times": raw_times or {},
    }


def _files():
    return [
        # Japan / CAM_A: two geotagged anchors (consistent -2h offset) -> gpx self-anchor, auto-resolved.
        _file(f"{JP}/2024-anchor-1.arw", CAM_A, "2024:07:03 14:00:00", gps={"lat": 50.0, "lon": 4.0}),
        _file(f"{JP}/2024-anchor-2.arw", CAM_A, "2024:07:03 14:10:00", gps={"lat": 50.0, "lon": 4.002}),
        # Japan / CAM_A: no GPS, resolves to 12:05Z (inside the track) -> gpx interpolation.
        _file(f"{JP}/2024-interp.arw", CAM_A, "2024:07:03 14:05:00"),
        # Japan / CAM_A: no GPS, resolves far from the track -> blocked (review item).
        _file(f"{JP}/2024-blocked-a.arw", CAM_A, "2024:07:03 22:00:00"),
        _file(f"{JP}/2024-blocked-b.arw", CAM_A, "2024:07:03 23:00:00"),
        # Japan/Kyoto / CAM_A: no own anchor -> inherits Japan's offset; geotagged -> preserve native.
        _file(f"{KY}/2024-kyoto.arw", CAM_A, "2024:07:03 14:30:00", gps={"lat": 50.1, "lon": 4.05}),
        # Belgium / CAM_B: no GPX anchor -> manual-required offset; no GPS -> folder fallback (once set).
        _file(f"{BE}/2024-belgium.arw", CAM_B, "2024:07:03 13:00:00"),
        # Belgium / phone: native EXIF offset resolves time; geotagged -> preserve native. No offset cell.
        _file(f"{BE}/2024-phone.jpg", PHONE, "2024:07:03 13:30:00",
              gps={"lat": 51.0, "lon": 4.3}, raw_times={"OffsetTimeOriginal": "+02:00"}),
    ]


GROUPS = {CAM_A: {"camera_group_class": "camera"}, CAM_B: {"camera_group_class": "camera"},
          PHONE: {"camera_group_class": "phone"}}


def _set_config():
    pol = dict(utils.CONFIG["camera_time_and_timezone_policy"],
               device_groups={"fixed_clock_cameras": [CAM_A, CAM_B], "phones": [PHONE]},
               default_folder_timezone="Europe/Brussels")
    utils.CONFIG["camera_time_and_timezone_policy"] = pol


def _fill_time_decisions(art):
    """Resolve every open time decision, exactly as a human editing user_decision would."""
    d = art["destinations"]
    d[JP]["destination_timezone"]["user_decision"]["manual_iana_timezone"] = "Asia/Tokyo"
    d[KY]["destination_timezone"]["user_decision"]["manual_iana_timezone"] = "Asia/Tokyo"
    d[BE]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True      # Europe/Brussels
    d[KY]["camera_group_time_decisions"][CAM_A]["user_decision"]["accept_proposal"] = True  # accept inherited
    d[BE]["camera_group_time_decisions"][CAM_B]["user_decision"]["manual_offset_seconds"] = 3600
    return art


def _fill_gps_decisions(art):
    """Resolve the GPS fallback + every blocked review item (manual coords for one, accept-unlocated
    for the other), as a human editing user_decision would."""
    d = art["destinations"]
    d[BE]["folder_fallback"]["user_decision"]["fallback_lat"] = 50.8503
    d[BE]["folder_fallback"]["user_decision"]["fallback_lon"] = 4.3517
    for ri in d[JP]["gps_decisions"]["review_items"]:
        if ri["relative_path"].endswith("blocked-a.arw"):
            ri["user_decision"]["manual_lat"] = 35.0116
            ri["user_decision"]["manual_lon"] = 135.7681
        elif ri["relative_path"].endswith("blocked-b.arw"):
            ri["user_decision"]["accept_unlocated"] = True
    return art


def main():
    _set_config()
    os.makedirs(OUT, exist_ok=True)
    files, gpx = _files(), _gpx()

    with tempfile.TemporaryDirectory() as ws:
        os.makedirs(os.path.join(ws, ".photos-ingest"), exist_ok=True)
        # _time_depends_on / _gps_depends_on read the handoff for a dependency fingerprint.
        utils.write_json_artifact(utils.handoff_path(ws), {"files": [], "content_fingerprint": "example"})
        wf = cal.CalibrationWorkflow(ws)
        wf._gpx_fingerprint = "example-gpx-fingerprint"
        rfp = "example-resolved-utc-fingerprint"

        # photos-21 — time decisions: first run (requires input), then the filled-in re-run (complete).
        time_req, blk = wf.build_time_decisions(files, GROUPS, None, gpx)
        assert not blk, blk
        assert time_req["status"] == "requires_user_input", time_req["status"]
        time_complete, blk = wf.build_time_decisions(
            files, GROUPS, _fill_time_decisions(json.loads(json.dumps(time_req))), gpx)
        assert not blk, blk
        assert time_complete["status"] == "complete", time_complete["status"]

        # photos-22 — GPS decisions are built on RESOLVED times (so calibration only reaches GPS once
        # time is complete): use the completed time decisions for the resolved-UTC rows.
        rows = cal.compute_resolved_utc(files, GROUPS, time_complete)
        gps_req, blk = wf.build_gps_decisions(files, rows, gpx, None, rfp)
        assert not blk, blk
        assert gps_req["status"] == "requires_user_input", gps_req["status"]
        gps_complete, blk = wf.build_gps_decisions(
            files, rows, gpx, _fill_gps_decisions(json.loads(json.dumps(gps_req))), rfp)
        assert not blk, blk
        assert gps_complete["status"] == "complete", gps_complete["status"]

    for name, art in [
        ("photos-21-time-decisions.requires-input.json", time_req),
        ("photos-21-time-decisions.complete.json", time_complete),
        ("photos-22-gps-decisions.requires-input.json", gps_req),
        ("photos-22-gps-decisions.complete.json", gps_complete),
    ]:
        utils.write_json_artifact(os.path.join(OUT, name), art)
        print(f"wrote examples/{name}  (status={art['status']})")


if __name__ == "__main__":
    main()
