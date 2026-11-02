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

"""Geotag (§24.1) — reversible manual GPS overrides. Every plan decides about a pinned photo from its own
values (the original-values ledger, §24.2), so a withdrawn pin is planned like any changed decision:
the photo is placed again from the tracks, or geotag's position is cleared. There is no revert operation
and no store of its own. exiftool-write + fingerprint are mocked. From conftest.py.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
BYDEST = "6-photos-by-dest"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


# --- build_executable_plan: withdrawal planning -----------------------------

def _model(rel, dest, *, native=False):
    return {"relative_path": rel, "destination": dest, "has_native_gps": native,
            "content_fingerprint": "fp-" + rel, "size": 10, "mtime_ns": 1,
            "native_gps": ({"lat": 1.0, "lon": 2.0, "processing_method": "gps"} if native else None)}


def _row(rel):
    return {"relative_path": rel, "resolved_utc": "2024-07-03T12:00:00Z", "resolved_utc_status": "valid"}


def _plan_wf(tmp_path, files, *, manual=None, unlocated=()):
    ws = tmp_path / "ws"; (ws / ".photos-ingest").mkdir(parents=True); ctl = ws / ".photos-ingest"
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"cache_fingerprint": "pcf"}))
    dests = {f["destination"] for f in files}
    reviews = {d: [] for d in dests}
    for rel, (lat, lon) in (manual or {}).items():
        d = next(f["destination"] for f in files if f["relative_path"] == rel)
        reviews[d].append({"relative_path": rel, "user_decision": {"manual_lat": lat, "manual_lon": lon}})
    for rel in unlocated:
        d = next(f["destination"] for f in files if f["relative_path"] == rel)
        reviews[d].append({"relative_path": rel, "user_decision": {"accept_unlocated": True}})
    time_art = {"status": "complete", "destinations": {
        d: {"destination_timezone": {"effective_iana_timezone": "Europe/Brussels"}} for d in dests}}
    gps_art = {"status": "complete", "destinations": {
        d: {"folder_fallback": {"effective_fallback": None},
            "gps_decisions": {"review_items": reviews[d]}} for d in dests}}
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(time_art))
    (ctl / "photos-22-gps-drift-validation.json").write_text(
        json.dumps({"status": "complete", "destinations": {}}))
    (ctl / "photos-23-gps-decisions.json").write_text(json.dumps(gps_art))
    wf = cal.GeotagWorkflow(str(ws)); wf.handoff = {"cache_fingerprint": "pcf"}; wf._gpx_fingerprint = "g"
    gpx = cal.GPXIndex(""); gpx.points = []
    return wf, time_art, gps_art, gpx




def _pinned(rel, dest, held_gps=None, held_method=None):
    """A photo with no GPS of its own, decided from its pinned values, now holding `held_gps` — the
    position an earlier run wrote — under `held_method`."""
    f = dict(_model(rel, dest), from_originals=True, processing_method=None, geotag_marker=None)
    f["held"] = {"DateTimeOriginal": "2024:07:03 14:00:00", "OffsetTimeOriginal": "+02:00",
                 "lat": (held_gps or (None, None))[0], "lon": (held_gps or (None, None))[1], "method": held_method}
    return f


def _ops(plan, rel=None):
    return [o for dd in plan["destinations"].values() for o in dd["operations"]
            if rel is None or o["relative_path"] == rel]


_FORWARD = {"metadata_time_write", "metadata_gps_write", "gps_marker_write", "rename_no_clobber"}


@pytest.mark.spec("geotag-gps-write-complete-fix-1")
def test_a_cleared_position_takes_its_hemisphere_refs_with_it():
    """§28.1: a clear drops the refs with the coordinates — a ref left behind without its coordinate is a
    torn fix."""
    op = cal.time_fixed_marker_op(_model(f"{BYDEST}/T/a.jpg", f"{BYDEST}/T"), "+carto-time", clear_position=True)
    assert op["writes"] == {"GPSLatitude": "", "GPSLatitudeRef": "", "GPSLongitude": "", "GPSLongitudeRef": "",
                            "GPSProcessingMethod": "+carto-time"}


@pytest.mark.spec("geotag-withdraw-revert-1", "geotag-manual-gps-reversible-1", "authored-withdraw-undoes-1", test="TST-geotag_gps_ledger-a_withdrawn_pin_is_cleared")
def test_a_withdrawn_pin_is_cleared(tmp_path):
    """A pin withdrawn from a photo that had no GPS, the photo accepted as unlocated: the plan, deciding
    from its own values, clears geotag's position, and records the position it clears."""
    rel = f"{BYDEST}/T/a.jpg"
    f = _pinned(rel, f"{BYDEST}/T", (48.85, 2.35), "manual_locked")
    wf, t, g, gpx = _plan_wf(tmp_path, [f], unlocated=[rel])
    plan, blockers = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp")
    assert blockers == []
    clear = next(o for o in _ops(plan, rel) if o["type"] == "gps_marker_write")
    assert clear["writes"]["GPSLatitude"] == "" and clear["writes"]["GPSLongitude"] == ""
    assert clear["writes"]["GPSProcessingMethod"] == "+carto-time"
    assert clear["pre_state"] == {"present": True, "GPSLatitude": 48.85, "GPSLongitude": 2.35,
                                  "GPSProcessingMethod": "manual_locked"}
    assert not any(o["type"] == "metadata_gps_write" for o in _ops(plan, rel))


@pytest.mark.spec("geotag-automated-gps-no-revert-1", test="TST-geotag_gps_ledger-a_withdrawn_pin_is_placed_again_from_the_tracks")
def test_a_withdrawn_pin_is_placed_again_from_the_tracks(tmp_path):
    """Withdrawn, the pin gives way to the position the tracks give the photo's own time: recomputed, not
    rolled back to anything stored."""
    rel = f"{BYDEST}/T/a.jpg"
    f = _pinned(rel, f"{BYDEST}/T", (48.85, 2.35), "manual_locked")
    wf, t, g, gpx = _plan_wf(tmp_path, [f])
    gpx.points = [cal.GPXPoint(50.0, 4.0, datetime(2024, 7, 3, 11, 59, tzinfo=timezone.utc), "t.gpx", 0),
                  cal.GPXPoint(50.0, 4.0, datetime(2024, 7, 3, 12, 1, tzinfo=timezone.utc), "t.gpx", 1)]
    plan, blockers = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp")
    assert blockers == []
    w = next(o for o in _ops(plan, rel) if o["type"] == "metadata_gps_write")
    assert (w["writes"]["GPSLatitude"], w["writes"]["GPSLongitude"]) == (50.0, 4.0)
    assert w["gps_origin"] == "recompute_automated"
    assert {o["type"] for o in _ops(plan)} <= _FORWARD


@pytest.mark.spec("geotag-recompute-inplace-1", "time-name-never-reverted-1", test="TST-geotag_gps_ledger-a_withdrawal_never_reverts_time_name_or_destination")
def test_a_withdrawal_never_reverts_time_name_or_destination(tmp_path):
    """Withdrawing a decision changes GPS only as any plan would: geotag has no revert operation at all
    (time writes and renames are forward-idempotent), and it never moves a photo across destinations."""
    rel = f"{BYDEST}/T/a.jpg"
    f = _pinned(rel, f"{BYDEST}/T", (48.85, 2.35), "manual_locked")
    wf, t, g, gpx = _plan_wf(tmp_path, [f], unlocated=[rel])
    plan, _ = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp")
    ops = _ops(plan)
    assert ops and {o["type"] for o in ops} <= _FORWARD
    for o in ops:
        assert os.path.dirname(o["relative_path"]) == f"{BYDEST}/T"       # stays in its destination
        if o["type"] == "rename_no_clobber":
            assert "/" not in o["to"]                                    # basename-only -> in-dest rename


def test_a_pin_still_in_force_writes_nothing_again(tmp_path):
    rel = f"{BYDEST}/T/a.jpg"
    f = _pinned(rel, f"{BYDEST}/T", (10.0, 20.0), "manual_locked")
    wf, t, g, gpx = _plan_wf(tmp_path, [f], manual={rel: (10.0, 20.0)})
    plan, _ = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp")
    assert not any(o["type"] in ("metadata_gps_write", "gps_marker_write") for o in _ops(plan, rel))


def test_a_changed_pin_is_written_over_the_old_one(tmp_path):
    rel = f"{BYDEST}/T/a.jpg"
    f = _pinned(rel, f"{BYDEST}/T", (10.0, 20.0), "manual_locked")
    wf, t, g, gpx = _plan_wf(tmp_path, [f], manual={rel: (11.0, 21.0)})
    plan, _ = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp")
    w = next(o for o in _ops(plan, rel) if o["type"] == "metadata_gps_write")
    assert (w["writes"]["GPSLatitude"], w["gps_origin"]) == (11.0, "apply_manual")
    assert w["pre_state"] == {"present": True, "GPSLatitude": 10.0, "GPSLongitude": 20.0,
                              "GPSProcessingMethod": "manual_locked"}      # the position it replaces


@pytest.mark.spec("geotag-prestate-absent-1")
def test_a_pin_never_overrides_native_gps(tmp_path):
    """Preserve-native wins: a photo carrying its own GPS keeps it, whatever pin it is given."""
    rel = f"{BYDEST}/T/a.jpg"
    f = _model(rel, f"{BYDEST}/T", native=True)
    wf, t, g, gpx = _plan_wf(tmp_path, [f], manual={rel: (11.0, 21.0)})
    plan, _ = wf.build_executable_plan([f], [_row(rel)], t, g, gpx, "rfp")
    assert not any(o["type"] == "metadata_gps_write" for o in _ops(plan, rel))


# --- execute: own values pinned before the first write ---------------------

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
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
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
    files = [rec(f"{BYDEST}/T/2024-07-03--14-00-00.arw", "2024:07:03 14:00:00", (50.0, 4.0)),
             rec(f"{BYDEST}/T/2024-07-03--15-00-00.arw", "2024:07:03 15:00:00", (51.0, 5.0)),
             rec(f"{BYDEST}/T/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00")]            # no GPS -> blocked -> fallback
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))
    return ws, ctl


def _run(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", cmd])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _mock_tools(monkeypatch, ws):
    # the write is content-invariant -> the post-write fingerprint equals the pinned precondition
    # ("fp-<relative path>"); the files already carry their final names, so no rename moves them.
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, tags: True)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image",
                        staticmethod(lambda p: {"value": "fp-" + os.path.relpath(p, str(ws))}))


def _edit(ctl, name, fn):
    p = ctl / name; a = json.load(open(p)); fn(a); p.write_text(json.dumps(a))


def _drive_ready(monkeypatch, ws, ctl):
    """Drive _exec_ws to a ready photos-24 (timezone + folder-fallback accepted), c.arw -> manual."""
    _run(monkeypatch, ws, "plan")
    _edit(ctl, "photos-21-time-decisions.json", lambda a: a["destinations"][f"{BYDEST}/T"]
          ["destination_timezone"]["user_decision"].update({"accept_proposed_timezone": True}))
    _run(monkeypatch, ws, "plan")
    _edit(ctl, "photos-23-gps-decisions.json", lambda b: b["destinations"][f"{BYDEST}/T"]
          ["folder_fallback"]["user_decision"].update({"fallback_lat": 48.85, "fallback_lon": 2.35}))
    _run(monkeypatch, ws, "plan")
    assert (ctl / "photos-24-executable-plan.json").exists()


@pytest.mark.spec("geotag-prestate-before-write-1", test="TST-geotag_gps_ledger-own_values_pinned_before_the_first_write")
def test_own_values_pinned_before_the_first_write(tmp_path, monkeypatch):
    """§29.1a: a photo's own values are committed to the ledger BEFORE geotag's first write to it.
    Order-probe both seams during execute and assert the pin precedes the write."""
    ws, ctl = _exec_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)                                # sets _exiftool_write to a passthrough mock
    _drive_ready(monkeypatch, ws, ctl)
    events = []
    orig_pin = cal.GeotagCache.originals_pin
    orig_write = cal.GeotagWorkflow._exiftool_write             # the mock installed by _mock_tools

    def pin_spy(self, fp, rel, original, at):
        events.append(("pin", rel))
        return orig_pin(self, fp, rel, original, at)

    def write_spy(self, abs_path, tags):
        events.append(("write", os.path.relpath(abs_path, str(ws))))
        return orig_write(self, abs_path, tags)

    monkeypatch.setattr(cal.GeotagCache, "originals_pin", pin_spy)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", write_spy)
    assert _run(monkeypatch, ws, "execute") == 0
    manual = f"{BYDEST}/T/2024-07-03--14-30-00.arw"
    assert ("pin", manual) in events and ("write", manual) in events, events
    assert events.index(("pin", manual)) < events.index(("write", manual)), events


@pytest.mark.spec("geotag-rerunnable-after-execute-1", test="TST-geotag_gps_ledger-a_pin_executed_then_withdrawn_plans_and_executes_again")
def test_a_pin_executed_then_withdrawn_plans_and_executes_again(tmp_path, monkeypatch):
    ws, ctl = _exec_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    _drive_ready(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "execute") == 0
    t1 = json.load(open(ctl / "photos-25-execution-summary.json"))["totals"]
    assert t1["metadata_gps_writes"] == 1
    assert _run(monkeypatch, ws, "execute") == 0                        # idempotent re-execute
    q = ctl / "photos-23-gps-decisions.json"; b = json.load(open(q))
    b["destinations"][f"{BYDEST}/T"]["folder_fallback"]["user_decision"].update({"fallback_lat": "", "fallback_lon": ""})
    b["destinations"][f"{BYDEST}/T"]["gps_decisions"]["review_items"] = [
        {"relative_path": f"{BYDEST}/T/2024-07-03--14-30-00.arw", "user_decision": {"accept_unlocated": True}}]
    q.write_text(json.dumps(b))
    _run(monkeypatch, ws, "plan")
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    assert plan["status"] == "ready"
    assert {o["type"] for dd in plan["destinations"].values() for o in dd["operations"]} <= _FORWARD
    assert _run(monkeypatch, ws, "execute") == 0
