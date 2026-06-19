"""Geotag §22a — GPS-drift validation gate (photos-22).

The highest-danger gap: a (camera group, destination[, date]) bucket whose clock offset is
manual/timezone-derived (NOT a GPX self-anchor) and that has NO native-GPS anchor is placed in
phase 22 purely from its resolved UTC, so a wrong offset silently mis-places the whole batch. 22
flags every such bucket that GPX could validate and BLOCKS until the operator explicitly confirms
each (a zero-scrub "the offset was right" must be actively set — inaction never satisfies the gate).
The validated/corrected offset lives in 22; compute_resolved_utc re-consumes it. From conftest.py.
"""
import json
import os
import sys
from datetime import datetime, timezone

import photos_2_geotag as cal
import photos_utils as utils

BYDEST = "6-photos-by-dest"
CAM = "SONY|ILCE-6400|123"
DEST = f"{BYDEST}/D"
GROUPS = {CAM: {"camera_group_class": "camera"}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True, exist_ok=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _utc(h, m=0, day=3, mon=7):
    return datetime(2024, mon, day, h, m, 0, tzinfo=timezone.utc)


def _gpx(points=()):
    idx = cal.GPXIndex("")
    idx.points = [cal.GPXPoint(lat, lon, t, "trip.gpx", i) for i, (lat, lon, t) in enumerate(points)]
    return idx


def _file(rel, naive, *, gps=None):
    return {"relative_path": rel, "destination": DEST, "camera_group_key": CAM,
            "native_gps": gps, "has_native_gps": bool(gps), "has_timestamp": True,
            "source_naive_time": naive, "source_time_tag": "DateTimeOriginal", "camera_identity": {}}


def _prior_time(cells):
    """A photos-21 prior that accepts the destination tz and carries per-bucket offset decisions."""
    return {"destinations": {DEST: {
        "destination_timezone": {"user_decision": {"accept_proposed_timezone": True}},
        "camera_group_time_decisions": cells}}}


def _complete_time(wf, files, gpx, cells):
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    art, blk = wf.build_time_decisions(files, GROUPS, _prior_time(cells), gpx)
    assert not blk, blk
    # build_drift_validation hashes the on-disk photos-21 (as in the real run, which writes it first).
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    return art


def _drift(wf, files, time_art, gpx, prior=None):
    rows0 = cal.compute_resolved_utc(files, GROUPS, time_art)
    return wf.build_drift_validation(files, time_art, rows0, gpx, prior)


# --- Trigger matrix ---------------------------------------------------------

def test_manual_offset_no_anchor_with_coverage_triggers(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]               # no native gps
    gpx = _gpx([(50.0, 4.0, _utc(12))])                                   # within the 2-day window
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    drift, blk = _drift(wf, files, art, gpx)
    assert not blk
    cell = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["requires_user_input"] is True
    assert cell["proposal"]["proposal_source"] == "manual"
    assert cell["proposal"]["current_offset_seconds"] == 0
    assert len(cell["proposal"]["track_segment"]) == 1                    # the covering point as evidence
    assert cell["proposal"]["frames"] == [                               # the photo(s) the editor scrubs
        {"source_file": f"{DEST}/a.arw", "camera_naive": "2024:07:03 14:00:00"}]
    assert drift["status"] == "requires_user_input"


def test_frames_listed_earliest_first(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/late.arw", "2024:07:03 16:00:00"),
             _file(f"{DEST}/early.arw", "2024:07:03 14:00:00")]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    drift, _ = _drift(wf, files, art, gpx)
    frames = drift["destinations"][DEST]["drift_decisions"][CAM]["proposal"]["frames"]
    assert [f["source_file"] for f in frames] == [f"{DEST}/early.arw", f"{DEST}/late.arw"]


def test_timezone_derived_offset_triggers(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"accept_proposal": True}}})  # tz-derived
    cell0 = art["destinations"][DEST]["camera_group_time_decisions"][CAM]
    assert cell0["effective_time_anchor"]["source"] == "timezone_accepted"
    drift, _ = _drift(wf, files, art, gpx)
    assert CAM in drift["destinations"][DEST]["drift_decisions"]


def test_gpx_anchored_offset_does_not_trigger(tmp_path):
    wf = _wf(tmp_path)
    # native-GPS frame that matches the track -> gpx_self_anchor proposal, accepted -> gpx_anchor_*.
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00", gps={"lat": 50.0, "lon": 4.0})]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"accept_proposal": True}}})
    src = art["destinations"][DEST]["camera_group_time_decisions"][CAM]["effective_time_anchor"]["source"]
    assert src.startswith("gpx_anchor")
    drift, _ = _drift(wf, files, art, gpx)
    assert drift["destinations"] == {} and drift["status"] == "complete"


def test_manual_offset_but_native_anchor_present_does_not_trigger(tmp_path):
    wf = _wf(tmp_path)
    # manual override even though a native-GPS anchor exists -> reliably placeable, so NOT a 22 case.
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00", gps={"lat": 50.0, "lon": 4.0})]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 5}}})
    assert art["destinations"][DEST]["camera_group_time_decisions"][CAM]["effective_time_anchor"]["source"] == "manual"
    drift, _ = _drift(wf, files, art, gpx)
    assert drift["destinations"] == {}


def test_no_gpx_coverage_does_not_trigger(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]
    gpx = _gpx([(50.0, 4.0, datetime(2020, 1, 1, tzinfo=timezone.utc))])  # years away -> outside window
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    drift, _ = _drift(wf, files, art, gpx)
    assert drift["destinations"] == {} and drift["status"] == "complete"


def test_empty_gpx_does_not_trigger(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]
    art = _complete_time(wf, files, _gpx(), {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    drift, _ = _drift(wf, files, art, _gpx())
    assert drift["destinations"] == {}


def test_unresolvable_bucket_not_flagged(tmp_path):
    # A manual-offset bucket whose only frame has an unparseable naive time never resolves to a UTC,
    # so there is no interval to validate against -> not a drift case (the no-coverage guard).
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/x.arw", "not-a-date")]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    assert art["destinations"][DEST]["camera_group_time_decisions"][CAM]["effective_time_anchor"]["source"] == "manual"
    drift, _ = _drift(wf, files, art, gpx)
    assert drift["destinations"] == {}


def test_per_date_buckets_each_validated(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00"),
             _file(f"{DEST}/b.arw", "2024:01:03 14:00:00")]               # two naive dates -> split
    gpx = _gpx([(50.0, 4.0, _utc(12)), (50.0, 4.0, _utc(12, day=3, mon=1))])
    cells = {f"{CAM}@2024-07-03": {"user_decision": {"manual_offset_seconds": 0}},
             f"{CAM}@2024-01-03": {"user_decision": {"manual_offset_seconds": 0}}}
    art = _complete_time(wf, files, gpx, cells)
    drift, _ = _drift(wf, files, art, gpx)
    buckets = drift["destinations"][DEST]["drift_decisions"]
    assert set(buckets) == {f"{CAM}@2024-07-03", f"{CAM}@2024-01-03"}
    assert buckets[f"{CAM}@2024-07-03"]["date"] == "2024-07-03"


# --- Confirmation / consume -------------------------------------------------

def _triggered(tmp_path, drift_ud=None):
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    prior = {"destinations": {DEST: {"drift_decisions": {CAM: {"user_decision": drift_ud}}}}} if drift_ud else None
    drift, blk = _drift(wf, files, art, gpx, prior)
    return wf, files, art, gpx, drift, blk


def test_unconfirmed_bucket_blocks(tmp_path):
    *_, drift, blk = _triggered(tmp_path)
    assert not blk
    assert drift["requires_user_input"] is True                          # inaction blocks


def test_zero_scrub_must_be_explicit(tmp_path):
    _, files, _, _, drift, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": ""})
    assert not blk
    cell = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["requires_user_input"] is False
    assert cell["effective_drift_offset"] == {"offset_seconds": 0, "source": "gps_drift_validated"}
    assert drift["status"] == "complete"


def test_correction_changes_resolved_utc(tmp_path):
    _, files, art, _, drift, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -3600})
    assert not blk
    overrides = cal.drift_offset_overrides(drift)
    assert overrides == {(DEST, CAM): -3600}
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art, overrides)}
    row = rows[f"{DEST}/a.arw"]
    assert row["utc_offset_used"] == -3600
    assert row["resolved_utc"] == "2024-07-03T13:00:00Z"                  # 14:00 naive - 1h
    assert row["resolved_utc_provenance"] == "gps_drift_validated"


def test_zero_scrub_leaves_offset_unchanged(tmp_path):
    _, files, art, _, drift, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": ""})
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art, cal.drift_offset_overrides(drift))}
    assert rows[f"{DEST}/a.arw"]["utc_offset_used"] == 0                  # same offset, now validated
    assert rows[f"{DEST}/a.arw"]["resolved_utc_provenance"] == "gps_drift_validated"


# --- Validation of authored input -------------------------------------------

def test_non_numeric_correction_blocks(tmp_path):
    *_, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": "noon"})
    assert blk and "corrected_offset_seconds" in blk[0]


def test_out_of_range_correction_blocks(tmp_path):
    *_, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": 99999})
    assert blk


# --- Preservation / fingerprint cascade -------------------------------------

def test_confirmation_preserved_across_rebuild(tmp_path):
    wf, files, art, gpx, drift, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -120})
    # feed the built artifact back as prior -> the confirmation survives a regenerate
    drift2, blk = _drift(wf, files, art, gpx, drift)
    assert not blk
    cell = drift2["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["user_decision"] == {"confirmed": True, "corrected_offset_seconds": -120}
    assert cell["effective_drift_offset"]["offset_seconds"] == -120


def test_correction_shifts_resolved_fingerprint(tmp_path):
    _, files, art, _, d_a, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -3600})
    _, _, art_b, _, d_b, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -7200})
    rows_a = cal.compute_resolved_utc(files, GROUPS, art, cal.drift_offset_overrides(d_a))
    rows_b = cal.compute_resolved_utc(files, GROUPS, art_b, cal.drift_offset_overrides(d_b))
    fps = {"x": 1}
    assert cal.resolved_utc_fingerprint(rows_a, fps) != cal.resolved_utc_fingerprint(rows_b, fps)


# --- end-to-end: the `run` gate stops before phase 22, then resumes ---------

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _e2e_ws(tmp_path):
    """A workspace with a manual/tz-derived camera offset and NO native-GPS anchor, but GPX coverage
    over its window — exactly the 22 trigger. Photos-21 only needs its timezone + offset accepted."""
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir(); (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        default_folder_timezone="Europe/Brussels", write_corrected_filename_times=False)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))

    def rec(rel, dto):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": False}
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": False,
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec(f"{BYDEST}/T/a.arw", "2024:07:03 14:00:00"),
             rec(f"{BYDEST}/T/b.arw", "2024:07:03 14:30:00")]
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))
    return ws, ctl


def _run(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", cmd])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _edit(ctl, name, fn):
    p = ctl / name; a = json.load(open(p)); fn(a); p.write_text(json.dumps(a))


def test_e2e_drift_gate_blocks_then_resumes(tmp_path, monkeypatch):
    ws, ctl = _e2e_ws(tmp_path)
    dvp = ctl / "photos-22-gps-drift-validation.json"
    gdp = ctl / "photos-23-gps-decisions.json"

    _run(monkeypatch, ws, "plan")                                          # photos-21 needs tz + offset
    _edit(ctl, "photos-21-time-decisions.json", lambda a: (
        a["destinations"][f"{BYDEST}/T"]["destination_timezone"]["user_decision"]
        .update({"accept_proposed_timezone": True}),
        a["destinations"][f"{BYDEST}/T"]["camera_group_time_decisions"][CAM]["user_decision"]
        .update({"accept_proposal": True})))                              # tz-derived offset accepted

    _run(monkeypatch, ws, "plan")                                          # photos-21 complete -> 22 GATE
    assert dvp.exists()
    drift = json.load(open(dvp))
    assert drift["status"] == "requires_user_input"
    assert CAM in drift["destinations"][f"{BYDEST}/T"]["drift_decisions"]
    assert not gdp.exists()                                               # phase 22 BLOCKED by the gate

    # Confirm the bucket (zero scrub, explicit) -> the gate opens.
    _edit(ctl, "photos-22-gps-drift-validation.json", lambda a: a["destinations"][f"{BYDEST}/T"]
          ["drift_decisions"][CAM]["user_decision"].update({"confirmed": True}))
    _run(monkeypatch, ws, "plan")
    assert json.load(open(dvp))["status"] == "complete"
    assert gdp.exists()                                                   # phase 22 now built
