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

"""Geotag — a photo whose own position its camera's agreed clock offset contradicts (BLD-contradicted_position).

Among photos that agree on the camera's offset, one whose own GPS position agrees with none most likely carries a wrong
position — GPS jitter, a fix from minutes before. Once the offset is in effect, its position is set against the
track's at its corrected time: farther apart than the anchor distance, it is a GPS review item proposing the track's
position, the photo's own kept unless the user takes it. From conftest.py.
"""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils
from _zone import with_root_zone

BYDEST = "6-photos-by-dest"
DEST = f"{BYDEST}/Ghent"
CAM = "SONY|ILCE-6400|123"
GROUPS = {CAM: {"camera_group_key": CAM, "camera_group_class": "camera"}}
OFF = -7200                                         # the camera two hours ahead of UTC


def _t(m):
    return datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=m)


def _gpx():
    """A walk north, a point every ten minutes from 10:00 to 10:50 UTC, each about 560 m from the last."""
    idx = cal.GPXIndex("")
    idx.points = [cal.GPXPoint(51.0 + i * 0.005, 3.7, _t(10 * i), "walk.gpx", 0) for i in range(6)]
    idx.file_sha = {"walk.gpx": "sha"}
    return idx


def _photo(name, minute, lat, gps=True):
    naive = (_t(minute) - timedelta(seconds=OFF)).strftime("%Y:%m:%d %H:%M:%S")
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": CAM,
            "native_gps": {"lat": lat, "lon": 3.7} if gps else None, "has_native_gps": gps, "has_timestamp": True,
            "source_naive_time": naive, "content_fingerprint": "fp-" + name, "size": 1, "mtime_ns": 1}


def _files(stray_minute=25):
    """Five photos taken at the track's points, and one — `stray` — taken at `stray_minute` holding the position of the
    walk's last point, 50 minutes in: a stale fix."""
    return [_photo(f"p{i}.arw", 10 * i, 51.0 + i * 0.005) for i in range(5)] + [_photo("stray.arw", stray_minute, 51.025)]


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    wf.handoff = {"cache_fingerprint": "pcf"}
    return wf


def _time(wf, files, groups=GROUPS):
    """photos-21 with the day's proposal accepted, as the user accepts it."""
    gpx = _gpx()
    art, _ = wf.build_time_decisions(files, groups, with_root_zone({"destinations": {}}), gpx)
    prior = copy.deepcopy(art)
    cell = prior["destinations"][DEST]["camera_group_time_decisions"][CAM]
    cell["user_decision"].update(accept_proposal=True, accepted_offset_seconds=cell["proposal"]["proposed_offset_seconds"])
    art, blockers = wf.build_time_decisions(files, groups, prior, gpx)
    assert not blockers
    return art


def _gps(wf, files, art, prior=None):
    rows = cal.compute_resolved_utc(files, GROUPS, art)
    gps, blockers = wf.build_gps_decisions(files, rows, _gpx(), prior, "rfp", cal.contradicted_positions(art))
    return gps, blockers, rows


def _item(gps, name="stray.arw"):
    return next((ri for ri in gps["destinations"][DEST]["gps_decisions"]["review_items"]
                 if ri["relative_path"] == f"{DEST}/{name}"), None)


@pytest.mark.spec("RUL-contradicted_position_reviewed", "RUL-contradicted_position_kept_unless_taken",
                  "BLD-contradicted_position", "BLD-track_window",
                  test="TST-geotag_contradicted_position-a_scattered_position_is_offered_the_tracks")
def test_a_scattered_position_is_offered_the_tracks(tmp_path):
    """The day's offset agreed by five photos, the stray one agreeing with none: photos-21 names it, and photos-23 makes
    it a review item proposing where the track was at its corrected time — about 1.4 km from its own position — asking
    nothing, its own position kept. The tracks' window reaches its corrected time."""
    wf, files = _wf(tmp_path), _files()
    art = _time(wf, files)
    cell = art["destinations"][DEST]["camera_group_time_decisions"][CAM]
    assert cell["effective_time_anchor"]["source"] == "gpx_anchor_accepted"
    assert cell["positions_contradicted"] == [f"{DEST}/stray.arw"]
    gps, blockers, rows = _gps(wf, files, art)
    assert not blockers and gps["status"] == "complete"
    item = _item(gps)
    assert item["reason"] == "own_position_contradicted" and item["requires_user_input"] is False
    assert item["own_position"] == {"lat": 51.025, "lon": 3.7}
    assert item["proposed_position"]["lat"] == pytest.approx(51.0125) and item["proposed_position"]["gpx_file"] == "walk.gpx"
    assert item["apart_meters"] > utils.CONFIG["gpx_anchor_max_point_distance_meters"]
    assert item["user_decision"] == {"manual_lat": "", "manual_lon": ""}
    summary = gps["destinations"][DEST]["gps_decisions"]["summary"]
    assert summary["preserve_native_gps"] == 6 and summary["manual_review_required"] == 0
    assert _item(gps, "p1.arw") is None                                     # a photo that agrees is not doubted
    stray = next(r for r in rows if r["relative_path"] == f"{DEST}/stray.arw")
    window = cal.GeotagWorkflow.placement_window(files, rows, cal.contradicted_positions(art))
    t = cal._parse_utc(stray["resolved_utc"]).timestamp()
    assert any(lo <= t <= hi for lo, hi in window)
    assert not any(lo <= t <= hi for lo, hi in cal.GeotagWorkflow.placement_window(files, rows))   # native: not reached


@pytest.mark.spec("RUL-own_position_replaced_on_answer", "RUL-own_position_kept", "RUL-replaced_own_position_logged",
                  "BLD-contradicted_position", "BLD-placement_order",
                  test="TST-geotag_contradicted_position-the_users_answer_replaces_the_own_position_and_is_logged")
def test_the_users_answer_replaces_the_own_position_and_is_logged(tmp_path):
    """The user takes the track's position: the photo is placed there by their answer, a position write planned with
    the position it replaces as its pre-state; unanswered, its own position is never written over."""
    wf, files = _wf(tmp_path), _files()
    art = _time(wf, files)
    gps, _, rows = _gps(wf, files, art)
    prior = copy.deepcopy(gps)
    item = _item(prior)
    item["user_decision"].update(manual_lat=item["proposed_position"]["lat"], manual_lon=item["proposed_position"]["lon"])
    taken, blockers, _ = _gps(wf, files, art, prior)
    assert not blockers
    assert taken["destinations"][DEST]["gps_decisions"]["summary"]["manual_locked"] == 1
    ctl = tmp_path / "ws" / ".photos-ingest"
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    for name, rec in (("photos-21-time-decisions.json", art), ("photos-23-gps-decisions.json", taken),
                      ("photos-22-gps-drift-validation.json", {"status": "complete", "destinations": {}})):
        (ctl / name).write_text(json.dumps(rec))
    plan, _ = wf.build_executable_plan(files, rows, art, taken, _gpx(), "rfp")
    ops = [o for o in plan["destinations"][DEST]["operations"] if o["relative_path"] == f"{DEST}/stray.arw"]
    write = next(o for o in ops if o["type"] == "metadata_gps_write")
    assert write["gps_origin"] == "apply_manual" and write["writes"]["GPSLatitude"] == pytest.approx(51.0125)
    assert write["pre_state"] == {"present": True, "GPSLatitude": 51.025, "GPSLongitude": 3.7, "GPSProcessingMethod": ""}
    assert write["provenance"]["because"].startswith(f"photos-23 destinations.{DEST}.gps_decisions.review_items")
    unanswered, _ = wf.build_executable_plan(files, rows, art, gps, _gpx(), "rfp")
    assert not [o for o in unanswered["destinations"][DEST]["operations"]
                if o["relative_path"] == f"{DEST}/stray.arw" and o["type"] == "metadata_gps_write"]
    # an answer given stays while the user keeps it, though the offset no longer contradicts the photo
    kept, _, _ = _gps(wf, files, dict(art, destinations={}), prior)
    assert _item(kept)["user_decision"]["manual_lat"] == pytest.approx(51.0125)


@pytest.mark.spec("RUL-contradicted_position_without_track_noted", "BLD-contradicted_position",
                  test="TST-geotag_contradicted_position-with_no_track_the_photo_keeps_its_own_noted")
def test_with_no_track_the_photo_keeps_its_own_noted(tmp_path):
    """Contradicted, at a corrected time no track covers: nothing to propose — the photo keeps its own position, and
    photos-23 notes it."""
    wf, files = _wf(tmp_path), _files(stray_minute=240)
    art = _time(wf, files)
    assert art["destinations"][DEST]["camera_group_time_decisions"][CAM]["positions_contradicted"] == [f"{DEST}/stray.arw"]
    gps, _, _ = _gps(wf, files, art)
    assert _item(gps) is None
    assert gps["destinations"][DEST]["gps_decisions"]["contradicted_without_track"] == [
        {"relative_path": f"{DEST}/stray.arw", "content_fingerprint": "fp-stray.arw"}]


@pytest.mark.spec("RUL-several_bodies_positions_not_doubted", "BLD-contradicted_position",
                  test="TST-geotag_contradicted_position-several_bodies_photos_are_never_doubted")
def test_several_bodies_photos_are_never_doubted(tmp_path):
    """For a group the configuration names several bodies, a photo disagreeing with the offset is the other body's: its
    position is never read as wrong."""
    wf, files = _wf(tmp_path), _files()
    art = _time(wf, files, {CAM: dict(GROUPS[CAM], several_bodies=True)})
    assert "positions_contradicted" not in art["destinations"][DEST]["camera_group_time_decisions"][CAM]
    assert cal.contradicted_positions(art) == []
