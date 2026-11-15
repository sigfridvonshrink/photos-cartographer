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

"""Geotag RUL-unanchored_offset_confirmed — GPS-drift validation gate (photos-22).

The highest-danger gap: a (camera group, destination[, date]) bucket whose clock offset is
manual/timezone-derived (NOT a GPX self-anchor) and that has NO native-GPS anchor is placed in
phase 22 purely from its resolved UTC, so a wrong offset silently mis-places the whole batch. 22
flags every such bucket that GPX could validate and BLOCKS until the operator explicitly confirms
each (a zero-scrub "the offset was right" must be actively set — inaction never satisfies the gate).
The validated/corrected offset lives in 22; compute_resolved_utc re-consumes it. From conftest.py.
"""
import json
from _handoff import vouched
from _zone import answer_root_zone, with_root_zone
import os
import sys
from datetime import datetime, timezone

import photos_2_geotag as cal
import photos_utils as utils
import pytest

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


TRIP_SHA = "a" * 64
TRIP = [{"gpx_file": "trip.gpx", "sha256": TRIP_SHA}]      # the tracks a confirmation made by these points names


def _gpx(points=(), sha=TRIP_SHA):
    idx = cal.GPXIndex("")
    idx.points = [cal.GPXPoint(lat, lon, t, "trip.gpx", i) for i, (lat, lon, t) in enumerate(points)]
    idx.file_sha = {"trip.gpx": sha} if points else {}
    return idx


def _file(rel, naive, *, gps=None):
    return {"relative_path": rel, "destination": DEST, "camera_group_key": CAM,
            "native_gps": gps, "has_native_gps": bool(gps), "has_timestamp": True,
            "source_naive_time": naive, "source_time_tag": "DateTimeOriginal"}


def _prior_time(cells):
    """A photos-21 prior carrying per-bucket offset decisions, the zone answered at the root."""
    return with_root_zone({"destinations": {DEST: {"camera_group_time_decisions": cells}}})


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

@pytest.mark.spec("BLD-drift_validation")
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
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"accept_proposal": True, "accepted_offset_seconds": -7200}}})  # tz-derived
    cell0 = art["destinations"][DEST]["camera_group_time_decisions"][CAM]
    assert cell0["effective_time_anchor"]["source"] == "timezone_accepted"
    drift, _ = _drift(wf, files, art, gpx)
    assert CAM in drift["destinations"][DEST]["drift_decisions"]


def test_gpx_anchored_offset_does_not_trigger(tmp_path):
    wf = _wf(tmp_path)
    # native-GPS frame that matches the track -> gpx_self_anchor proposal, accepted -> gpx_anchor_*.
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00", gps={"lat": 50.0, "lon": 4.0})]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"accept_proposal": True, "accepted_offset_seconds": -7200}}})
    src = art["destinations"][DEST]["camera_group_time_decisions"][CAM]["effective_time_anchor"]["source"]
    assert src.startswith("gpx_anchor")
    drift, _ = _drift(wf, files, art, gpx)
    assert drift["destinations"] == {} and drift["status"] == "complete"


@pytest.mark.spec("RUL-unanchored_offset_confirmed",
                  test="TST-drift_validation-an_offset_against_the_cameras_gps_is_checked")
def test_an_offset_the_cameras_own_gps_contradicts_is_checked(tmp_path):
    """An offset set against what the camera's own GPS shows is one its GPS does not support: it is confirmed
    against the tracks like any other, the anchored photo beside it vouching for nothing."""
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00", gps={"lat": 50.0, "lon": 4.0})]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 5}}})
    assert art["destinations"][DEST]["camera_group_time_decisions"][CAM]["effective_time_anchor"]["source"] == "manual"
    drift, _ = _drift(wf, files, art, gpx)
    assert drift["destinations"][DEST]["drift_decisions"][CAM]["requires_user_input"] is True


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


@pytest.mark.spec("RUL-unanchored_offset_confirmed", "RUL-untouched_check_confirms_nothing",
                  test="TST-drift_validation-zero_scrub_must_be_explicit")
def test_zero_scrub_must_be_explicit(tmp_path):
    _, files, _, _, drift, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": "", "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    assert not blk
    cell = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["requires_user_input"] is False
    assert cell["effective_drift_offset"] == {"offset_seconds": 0, "source": "gps_drift_validated"}
    assert drift["status"] == "complete"


@pytest.mark.spec("BLD-drift_validation")
def test_correction_changes_resolved_utc(tmp_path):
    _, files, art, _, drift, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -3600, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    assert not blk
    overrides = cal.drift_offset_overrides(drift)
    assert overrides == {(DEST, CAM): -3600}
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art, overrides)}
    row = rows[f"{DEST}/a.arw"]
    assert row["utc_offset_used"] == -3600
    assert row["resolved_utc"] == "2024-07-03T13:00:00Z"                  # 14:00 naive - 1h
    assert row["resolved_utc_provenance"] == "gps_drift_validated"


def test_zero_scrub_leaves_offset_unchanged(tmp_path):
    _, files, art, _, drift, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": "", "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art, cal.drift_offset_overrides(drift))}
    assert rows[f"{DEST}/a.arw"]["utc_offset_used"] == 0                  # same offset, now validated
    assert rows[f"{DEST}/a.arw"]["resolved_utc_provenance"] == "gps_drift_validated"


# --- Validation of authored input -------------------------------------------

def test_non_numeric_correction_blocks(tmp_path):
    *_, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": "noon", "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    assert blk and "corrected_offset_seconds" in blk[0]


@pytest.mark.spec("BLD-drift_validation", "RUL-checked_clock_offsets",
                  test="TST-drift_validation-a_correction_not_whole_seconds_blocks")
def test_a_correction_not_whole_seconds_blocks(tmp_path):
    *_, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": 12.5, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    assert blk and "whole number of seconds" in blk[0]


# --- Preservation / fingerprint cascade -------------------------------------

@pytest.mark.spec("BLD-drift_validation")
def test_confirmation_preserved_across_rebuild(tmp_path):
    wf, files, art, gpx, drift, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -120, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    # feed the built artifact back as prior -> the confirmation survives a regenerate
    drift2, blk = _drift(wf, files, art, gpx, drift)
    assert not blk
    cell = drift2["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["user_decision"] == {"confirmed": True, "corrected_offset_seconds": -120, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP}
    assert cell["effective_drift_offset"]["offset_seconds"] == -120


def test_correction_shifts_resolved_fingerprint(tmp_path):
    _, files, art, _, d_a, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -3600, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
    _, _, art_b, _, d_b, _ = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": -7200, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP})
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
        default_folder_timezone="Europe/Brussels")
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)                        # the zone answered once at the root (RUL-timezone_auto_resolves)

    def rec(rel, dto):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": False}
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": False,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    files = [rec(f"{BYDEST}/T/a.arw", "2024:07:03 14:00:00"),
             rec(f"{BYDEST}/T/b.arw", "2024:07:03 14:30:00")]
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": files, "cache_fingerprint": "pcf", "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
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


@pytest.mark.spec("RUL-unanchored_offset_confirmed", "BLD-drift_validation", "RUL-untouched_check_confirms_nothing",
                  test="TST-drift_validation-e2e_drift_gate_blocks_then_resumes")
def test_e2e_drift_gate_blocks_then_resumes(tmp_path, monkeypatch):
    ws, ctl = _e2e_ws(tmp_path)
    dvp = ctl / "photos-22-gps-drift-validation.json"
    gdp = ctl / "photos-23-gps-decisions.json"

    _run(monkeypatch, ws, "plan")                                          # photos-21 needs the offset
    _edit(ctl, "photos-21-time-decisions.json", lambda a:
          a["destinations"][f"{BYDEST}/T"]["camera_group_time_decisions"][CAM]["user_decision"]
          .update({"accept_proposal": True, "accepted_offset_seconds": -7200}))                              # tz-derived offset accepted

    _run(monkeypatch, ws, "plan")                                          # photos-21 complete -> 22 GATE
    assert dvp.exists()
    drift = json.load(open(dvp))
    assert drift["status"] == "requires_user_input"
    assert CAM in drift["destinations"][f"{BYDEST}/T"]["drift_decisions"]
    assert not gdp.exists()                                               # phase 22 BLOCKED by the gate

    # Confirm the bucket (zero scrub, explicit) -> the gate opens.
    def confirm(a):
        cell = a["destinations"][f"{BYDEST}/T"]["drift_decisions"][CAM]
        cell["user_decision"].update({"confirmed": True,
                                      "confirmed_offset_seconds": cell["proposal"]["current_offset_seconds"],
                                      "confirmed_against_tracks": cell["proposal"]["tracks"]})
    _edit(ctl, "photos-22-gps-drift-validation.json", confirm)
    _run(monkeypatch, ws, "plan")
    assert json.load(open(dvp))["status"] == "complete"
    assert gdp.exists()                                                   # phase 22 now built


@pytest.mark.spec("RUL-changed_tracks_asked_again", "RUL-stale_confirmation_kept", "BLD-drift_confirmation_tracks",
                  test="TST-drift_validation-e2e_a_changed_track_asks_again")
def test_e2e_a_track_changed_since_the_confirmation_asks_again(tmp_path, monkeypatch):
    """Confirmed as the editor does — naming the tracks the cell shows, by the SHA-256 of their bytes — the check
    passes; the track then replaced by another export of the day, the next plan asks again."""
    ws, ctl = _e2e_ws(tmp_path)
    dvp = ctl / "photos-22-gps-drift-validation.json"
    _run(monkeypatch, ws, "plan")
    _edit(ctl, "photos-21-time-decisions.json", lambda a:
          a["destinations"][f"{BYDEST}/T"]["camera_group_time_decisions"][CAM]["user_decision"]
          .update({"accept_proposal": True, "accepted_offset_seconds": -7200}))
    _run(monkeypatch, ws, "plan")
    track = tmp_path / "gpx" / "t.gpx"
    shown = json.load(open(dvp))["destinations"][f"{BYDEST}/T"]["drift_decisions"][CAM]["proposal"]["tracks"]
    assert shown == [{"gpx_file": "t.gpx", "sha256": utils.sha256_file(str(track))}]

    def confirm(a):
        cell = a["destinations"][f"{BYDEST}/T"]["drift_decisions"][CAM]
        cell["user_decision"].update({"confirmed": True, "confirmed_against_tracks": cell["proposal"]["tracks"],
                                      "confirmed_offset_seconds": cell["proposal"]["current_offset_seconds"]})
    _edit(ctl, "photos-22-gps-drift-validation.json", confirm)
    _run(monkeypatch, ws, "plan")
    assert json.load(open(dvp))["status"] == "complete"
    written = json.load(open(dvp))["destinations"][f"{BYDEST}/T"]["drift_decisions"][CAM]["user_decision"]

    track.write_text(track.read_text().replace("13:00:00Z", "13:05:00Z"))   # another export of the same day
    _run(monkeypatch, ws, "plan")
    drift = json.load(open(dvp))
    cell = drift["destinations"][f"{BYDEST}/T"]["drift_decisions"][CAM]
    assert drift["status"] == "requires_user_input" and cell["stale_user_decision"] is True
    assert cell["user_decision"] == written and cell["confirmed_tracks_changed"] == ["t.gpx"]


@pytest.mark.spec("RUL-confirmation_holds_for_its_offset", "BLD-drift_validation", "RUL-changed_offset_asked_again",
                  test="TST-drift_validation-a_confirmation_holds_only_for_the_offset_it_confirmed")
@pytest.mark.parametrize("corrected", ["", -3600], ids=["zero_scrub", "correction"])
def test_a_confirmation_holds_only_for_the_offset_it_confirmed(tmp_path, corrected):
    # Confirmed against offset 0; the user then changes the offset in photos-21 to -5400. The confirmation was
    # never made against -5400: it is stale, applies to nothing, and the bucket asks again — kept as written.
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]
    gpx = _gpx([(50.0, 4.0, _utc(12))])
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    first, _ = _drift(wf, files, art, gpx, None)
    first["destinations"][DEST]["drift_decisions"][CAM]["user_decision"] = {
        "confirmed": True, "corrected_offset_seconds": corrected, "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP}
    held, _ = _drift(wf, files, art, gpx, first)
    cell = held["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["effective_drift_offset"] and cell["stale_user_decision"] is False      # same offset: holds
    art2 = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": -5400}}})
    after, blk = _drift(wf, files, art2, gpx, held)
    assert not blk
    again, _ = _drift(wf, files, art2, gpx, after)                      # and stays stale on the next run
    assert again["destinations"][DEST]["drift_decisions"][CAM]["stale_user_decision"] is True
    cell = after["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["proposal"]["current_offset_seconds"] == -5400
    assert cell["effective_drift_offset"] == "" and cell["stale_user_decision"] is True
    assert cell["requires_user_input"] is True and after["status"] == "requires_user_input"
    assert cell["user_decision"] == {"confirmed": True, "corrected_offset_seconds": corrected,
                                     "confirmed_offset_seconds": 0, "confirmed_against_tracks": TRIP}
    assert cal.drift_offset_overrides(after) == {}                                         # applied to nothing


@pytest.mark.spec("RUL-unanchored_offset_confirmed", "BLD-drift_validation", "RUL-untouched_check_confirms_nothing",
                  test="TST-drift_validation-a_confirmation_naming_no_offset_confirms_nothing")
def test_a_confirmation_naming_no_offset_confirms_nothing(tmp_path):
    *_, drift, blk = _triggered(tmp_path, {"confirmed": True, "corrected_offset_seconds": "",
                                          "confirmed_against_tracks": TRIP})
    assert drift["status"] == "requires_user_input" and blk == [f"{DEST}: drift_decisions[{CAM}].user_decision.confirmed_offset_seconds must be "
                                     "the offset confirmed — the current one is 0."]


# --- A confirmation rests on the tracks it was made against (RUL-confirmation_rests_on_its_tracks) -----------

CONFIRMED = {"confirmed": True, "corrected_offset_seconds": -120, "confirmed_offset_seconds": 0,
             "confirmed_against_tracks": TRIP}


def _tracks(*files):
    """A GPXIndex of one point by the photo per file named, each `(name, sha256)`."""
    idx = cal.GPXIndex("")
    idx.points = [cal.GPXPoint(50.0, 4.0 + i / 1000, _utc(12), name, 0) for i, (name, _sha) in enumerate(files)]
    idx.file_sha = dict(files)
    return idx


def _rechecked(tmp_path, gpx, ud=CONFIRMED):
    """The drift check built again over `gpx` with the confirmation `ud` made against the trip's track."""
    wf, files, art, _, first, _ = _triggered(tmp_path)
    first["destinations"][DEST]["drift_decisions"][CAM]["user_decision"] = dict(ud)
    return _drift(wf, files, art, gpx, first)


@pytest.mark.spec("BLD-drift_confirmation_tracks",
                  test="TST-drift_validation-the_check_names_the_tracks_it_shows")
def test_the_check_names_the_tracks_it_shows(tmp_path):
    """Each drift cell lists the track files its segment is drawn from, each with its SHA-256 — what the editor writes
    with a confirmation. Unconfirmed, the cell names none and nothing changed."""
    gpx = _tracks(("trip.gpx", TRIP_SHA), ("b.gpx", "b" * 64))
    *_, drift, blk = _triggered(tmp_path)
    cell = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert cell["proposal"]["tracks"] == TRIP
    assert cell["user_decision"]["confirmed_against_tracks"] == [] and cell["confirmed_tracks_changed"] == []
    drift, blk = _rechecked(tmp_path, gpx, {"confirmed": False})
    cell = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert not blk and cell["proposal"]["tracks"] == [{"gpx_file": "b.gpx", "sha256": "b" * 64}, *TRIP]


@pytest.mark.spec("RUL-confirmation_rests_on_its_tracks", "RUL-changed_tracks_asked_again",
                  "RUL-stale_confirmation_kept", "BLD-drift_confirmation_tracks",
                  test="TST-drift_validation-a_confirmation_holds_only_while_its_tracks_stand")
@pytest.mark.parametrize("now", [
    [("trip.gpx", "b" * 64)],                                  # the same file, another export of the day
    [("other.gpx", "c" * 64)],                                 # the track taken out, another put in
], ids=["changed", "removed"])
def test_a_confirmation_holds_only_while_its_tracks_stand(tmp_path, now):
    """Confirmed by scrubbing the photo along trip.gpx; that track then changed or gone, the check asks again, the
    confirmation kept exactly as written and applied to nothing — the day is never placed on a track nobody looked
    at it against."""
    held, blk = _rechecked(tmp_path, _tracks(("trip.gpx", TRIP_SHA)))
    cell = held["destinations"][DEST]["drift_decisions"][CAM]
    assert not blk and cell["effective_drift_offset"] == {"offset_seconds": -120, "source": "gps_drift_validated"}
    assert cell["stale_user_decision"] is False and cell["confirmed_tracks_changed"] == []
    after, blk = _rechecked(tmp_path, _tracks(*now))
    cell = after["destinations"][DEST]["drift_decisions"][CAM]
    assert not blk
    assert cell["effective_drift_offset"] == "" and cell["stale_user_decision"] is True
    assert cell["requires_user_input"] is True and after["status"] == "requires_user_input"
    assert cell["user_decision"] == CONFIRMED and cell["confirmed_tracks_changed"] == ["trip.gpx"]
    assert cal.drift_offset_overrides(after) == {}


@pytest.mark.spec("RUL-confirmation_rests_on_its_tracks", "BLD-drift_confirmation_tracks",
                  test="TST-drift_validation-a_track_put_in_beside_leaves_the_confirmation")
def test_a_track_put_in_beside_the_ones_seen_leaves_the_confirmation(tmp_path):
    """The confirmation rests on the tracks it was made against: another put in beside them leaves those there
    unchanged, and it holds."""
    drift, blk = _rechecked(tmp_path, _tracks(("trip.gpx", TRIP_SHA), ("other.gpx", "c" * 64)))
    cell = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert not blk and cell["effective_drift_offset"]["offset_seconds"] == -120 and not cell["stale_user_decision"]


@pytest.mark.spec("RUL-confirmation_rests_on_its_tracks", "BLD-drift_confirmation_tracks", "BLD-day_offset_kept",
                  test="TST-drift_validation-a_kept_confirmation_rests_on_its_tracks")
def test_a_confirmation_kept_for_later_photos_rests_on_its_tracks(tmp_path):
    """Every photo of the day corrected already, the confirmation is kept for photos arriving later — and rests
    there on the tracks it was made against all the same, though none is shown any more."""
    wf = _wf(tmp_path)
    time_cell = {"camera_group": CAM, "effective_time_anchor": {"offset_seconds": 0, "source": "manual"}}
    prior = {"user_decision": dict(CONFIRMED)}
    for track_sha, holds in (({"trip.gpx": TRIP_SHA}, True), ({"trip.gpx": "b" * 64}, False), ({}, False)):
        blockers = []
        cell = wf._drift_cell(DEST, CAM, time_cell, [], [], prior, blockers, track_sha=track_sha)
        assert not blockers and bool(cell["effective_drift_offset"]) is holds, track_sha
        assert cell["confirmed_tracks_changed"] == ([] if holds else ["trip.gpx"])


@pytest.mark.spec("RUL-trackless_confirmation_holds_while_none", "BLD-drift_confirmation_tracks",
                  test="TST-drift_validation-a_confirmation_made_with_no_track_holds_while_none")
def test_a_confirmation_made_with_no_track_holds_while_there_is_none(tmp_path):
    """A check shown with no track by the photos (a timezone's guess, asked about whatever lies by it) can be
    confirmed naming no track; that holds only while still none lies by them — a track arriving later is one it
    never saw."""
    wf = _wf(tmp_path)
    time_cell = {"camera_group": CAM, "effective_time_anchor": {"offset_seconds": 0, "source": "timezone_unconfirmed"}}
    prior = {"user_decision": {"confirmed": True, "confirmed_offset_seconds": 0, "confirmed_against_tracks": []}}
    gpx = _tracks(("trip.gpx", TRIP_SHA))
    for segment, holds in (([], True), (gpx.points, False)):
        blockers = []
        cell = wf._drift_cell(DEST, CAM, time_cell, segment, [], prior, blockers, track_sha=gpx.file_sha)
        assert not blockers and bool(cell["effective_drift_offset"]) is holds and cell["stale_user_decision"] is not holds
        assert cell["user_decision"]["confirmed_against_tracks"] == []


@pytest.mark.spec("BLD-drift_confirmation_tracks", "RUL-checked_shapes",
                  test="TST-drift_validation-a_confirmation_naming_no_tracks_is_a_blocker")
@pytest.mark.parametrize("named", [None, "trip.gpx", [{"gpx_file": "trip.gpx"}], [{"gpx_file": "", "sha256": "x"}]],
                         ids=["absent", "not_a_list", "no_sha", "no_file"])
def test_a_confirmation_naming_no_tracks_is_a_blocker(tmp_path, named):
    """A confirmation must name the tracks it was made against: saved without them, it is a blocker — never taken
    as made against whatever tracks are there now."""
    ud = {k: v for k, v in CONFIRMED.items() if k != "confirmed_against_tracks"}
    if named is not None:
        ud["confirmed_against_tracks"] = named
    drift, blk = _rechecked(tmp_path, _tracks(("trip.gpx", TRIP_SHA)), ud)
    assert blk == [f"{DEST}: drift_decisions[{CAM}].user_decision.confirmed_against_tracks must name the tracks "
                   "the confirmation was made against, each with its gpx_file and sha256."]
    assert drift["destinations"][DEST]["drift_decisions"][CAM]["effective_drift_offset"] == ""



@pytest.mark.spec("RUL-setting_bounds_one_thing", "BLD-drift_validation",
                  test="TST-drift_validation-the_track_window_is_its_own_setting")
def test_how_much_track_the_check_looks_at_is_its_own_setting(tmp_path, monkeypatch):
    """Which track counts as covering a bucket's photos is the drift check's own setting, not the largest
    clock error an anchor may imply."""
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:00:00")]
    gpx = _gpx([(50.0, 4.0, _utc(12, day=13))])                           # ten days after the photo
    art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": 0}}})
    assert _drift(wf, files, art, gpx)[0]["destinations"] == {}
    monkeypatch.setitem(utils.CONFIG, "gpx_anchor_max_clock_error_seconds", 30 * 86400.0)
    assert _drift(wf, files, art, gpx)[0]["destinations"] == {}
    monkeypatch.setitem(utils.CONFIG, "drift_check_track_window_seconds", 30 * 86400.0)
    assert DEST in _drift(wf, files, art, gpx)[0]["destinations"]


@pytest.mark.spec("RUL-unanchored_offset_confirmed", "BLD-drift_validation",
                  test="TST-drift_validation-an_offset_that_carries_photos_off_their_tracks_is_checked")
def test_an_offset_that_carries_the_photos_away_from_their_tracks_is_still_checked(tmp_path):
    """A manual offset with a slipped digit puts the photos eight days from the tracks recorded the day they
    were taken. No track lies by the times it gives — because of it: the check asks, against the tracks by
    the times the camera recorded."""
    wf = _wf(tmp_path)
    files = [_file(f"{DEST}/a.arw", "2024:07:03 14:10:00")]
    gpx = _gpx([(50.0, 4.0, _utc(12)), (50.001, 4.0, _utc(13))])
    for typed in (-7200, -720000):
        art = _complete_time(wf, files, gpx, {CAM: {"user_decision": {"manual_offset_seconds": typed}}})
        drift, blk = _drift(wf, files, art, gpx)
        cell = drift["destinations"][DEST]["drift_decisions"][CAM]
        assert not blk and cell["requires_user_input"] and len(cell["proposal"]["track_segment"]) == 2
        assert cell["proposal"]["current_offset_seconds"] == typed
