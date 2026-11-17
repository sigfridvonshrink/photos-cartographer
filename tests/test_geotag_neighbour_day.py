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

"""Geotag — a day with no anchor of its own, offered the day next to it (BLD-neighbour_day_proposal).

A camera left on home time abroad, or a night shoot, has its midnight mid-outing: the half after midnight is a day of
its own, with no anchor, though the half before settled the clock. Such a day is proposed the offset of the day before
or after of the same camera in the same destination, where that day is anchored — asked about once, as a timezone's
guess is: at the drift check where tracks lie by the day's photos, by acceptance where none do. From conftest.py.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils
from _zone import with_root_zone

BYDEST = "6-photos-by-dest"
DEST = f"{BYDEST}/Tokyo"
CAM = "SONY|ILCE-6400|123"
GROUPS = {CAM: {"camera_group_key": CAM, "camera_group_class": "camera"}}
HOME = -3600                         # the camera left on home time (UTC+1) in Japan


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {"night.gpx": "sha"}
    return idx


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _photo(name, naive, lat=None):
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": CAM,
            "native_gps": {"lat": lat, "lon": 139.7} if lat is not None else None, "has_native_gps": lat is not None,
            "has_timestamp": True, "source_naive_time": naive, "content_fingerprint": "fp-" + name}


def _night():
    """An evening walk anchored on the track (camera times 3 July, 22:00 and 22:30 on home time), and the outing's
    photos after the camera's midnight, 4 July, with no position — the track goes on by them."""
    pts = [cal.GPXPoint(35.6 + i * 0.005, 139.7, datetime(2024, 7, 3, 21, tzinfo=timezone.utc) + timedelta(minutes=30 * i),
                        "night.gpx", 0) for i in range(8)]
    files = [_photo("a.arw", "2024:07:03 22:00:00", 35.6), _photo("b.arw", "2024:07:03 22:30:00", 35.605),
             _photo("c.arw", "2024:07:04 00:30:00"), _photo("d.arw", "2024:07:04 01:10:00")]
    return pts, files


def _plan(wf, files, gpx, prior=None):
    utils.CONFIG["camera_time_and_timezone_policy"]["multi_anchor_auto_apply"] = True
    art, blockers = wf.build_time_decisions(files, GROUPS, with_root_zone(prior or {"destinations": {}}, "Asia/Tokyo"),
                                            gpx)
    assert not blockers
    return art


def _cells(art):
    return art["destinations"][DEST]["camera_group_time_decisions"]


@pytest.mark.spec("RUL-neighbour_day_offset_proposed", "RUL-neighbour_day_keeps_its_cell", "BLD-neighbour_day_proposal",
                  test="TST-geotag_neighbour_day-a_day_with_no_anchor_is_proposed_the_day_before")
def test_a_day_with_no_anchor_is_proposed_the_day_before(tmp_path):
    """The half after midnight is offered the offset the evening's anchors settled, in place of the zone's guess —
    its own cell still, with a decision of its own."""
    pts, files = _night()
    art = _plan(_wf(tmp_path), files, _gpx(pts))
    cells = _cells(art)
    before, after = cells[f"{CAM}@2024-07-03"], cells[f"{CAM}@2024-07-04"]
    assert before["effective_time_anchor"] == {"offset_seconds": HOME, "source": "gpx_anchor_auto"}
    assert after["proposal"] == {"proposal_source": "neighbour_day", "proposed_offset_seconds": HOME,
                                 "neighbour_day": {"day": "2024-07-03", "bucket": f"{CAM}@2024-07-03"},
                                 "confidence": "review_required"}
    assert after["day"] == "2024-07-04" and "user_decision" in after and after is not before


@pytest.mark.spec("RUL-neighbour_day_offset_needs_acceptance", "RUL-neighbour_day_offset_drift_checked",
                  "BLD-neighbour_day_proposal", "BLD-drift_validation",
                  test="TST-geotag_neighbour_day-with_tracks_it_is_asked_only_at_the_drift_check")
def test_with_tracks_it_is_asked_only_at_the_drift_check(tmp_path):
    """Tracks lie by the day's photos: the neighbour's offset is asked about once, as a timezone's guess is — photos-21
    asks nothing, the offset going to the drift check unconfirmed, and photos-22 asks it; confirmed there, nothing
    asks any more, in either record, and the photos resolve by it."""
    wf, (pts, files) = _wf(tmp_path), _night()
    gpx = _gpx(pts)
    art = _plan(wf, files, gpx)
    cell = _cells(art)[f"{CAM}@2024-07-04"]
    assert cell["proposal"]["proposal_source"] == "neighbour_day"
    assert cell["effective_time_anchor"] == {"offset_seconds": HOME, "source": "neighbour_day_unconfirmed"}
    assert cell["decision_mode"] == "to_be_confirmed_against_tracks" and cell["requires_user_input"] is False
    assert cell["user_decision"]["accept_proposal"] is False and art["status"] == "complete"
    rows0 = cal.compute_resolved_utc(files, GROUPS, art)
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    asked, blockers = wf.build_drift_validation(files, art, rows0, gpx, None)
    assert not blockers and asked["requires_user_input"] is True
    assert list(asked["destinations"][DEST]["drift_decisions"]) == [f"{CAM}@2024-07-04"]
    check = asked["destinations"][DEST]["drift_decisions"][f"{CAM}@2024-07-04"]
    assert check["requires_user_input"] is True and check["proposal"]["current_offset_seconds"] == HOME
    check["user_decision"] = {"confirmed": True, "corrected_offset_seconds": "", "confirmed_offset_seconds": HOME,
                              "confirmed_against_tracks": [{"gpx_file": "night.gpx", "sha256": "sha"}]}
    drift, blockers = wf.build_drift_validation(files, art, rows0, gpx, asked)
    assert not blockers and drift["status"] == "complete"
    again = _plan(wf, files, gpx, art)
    assert again["status"] == "complete" and not _cells(again)[f"{CAM}@2024-07-04"]["requires_user_input"]
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, again, cal.drift_offset_overrides(drift))}
    assert rows[f"{DEST}/c.arw"]["resolved_utc"] == "2024-07-03T23:30:00Z"


@pytest.mark.spec("RUL-neighbour_day_offset_needs_acceptance", "RUL-neighbour_day_offset_drift_checked",
                  "BLD-neighbour_day_proposal",
                  test="TST-geotag_neighbour_day-without_tracks_it_is_accepted_in_the_time_decisions")
def test_without_tracks_it_is_accepted_in_the_time_decisions(tmp_path):
    """No track at all — the evening's clock settled by its fixes' own times: the neighbour's offset is asked in
    photos-21 instead, taking no effect until accepted there; accepted, it takes effect, and with no track to set it
    against, the drift check asks nothing of it."""
    _, files = _night()
    for f, t in zip(files[:2], ("2024-07-03T21:00:00Z", "2024-07-03T21:30:00Z")):
        f["gps_utc"] = t                                          # the camera's own fixes: camera time less an hour
    wf, gpx = _wf(tmp_path), _gpx([])
    art = _plan(wf, files, gpx)
    assert _cells(art)[f"{CAM}@2024-07-03"]["effective_time_anchor"]["source"] == "gps_time_auto"
    cell = _cells(art)[f"{CAM}@2024-07-04"]
    assert cell["proposal"]["proposal_source"] == "neighbour_day" and cell["proposal"]["proposed_offset_seconds"] == HOME
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"] is True
    prior = copy.deepcopy(art)
    _cells(prior)[f"{CAM}@2024-07-04"]["user_decision"].update(accept_proposal=True, accepted_offset_seconds=HOME)
    art = _plan(wf, files, gpx, prior)
    assert _cells(art)[f"{CAM}@2024-07-04"]["effective_time_anchor"] == {"offset_seconds": HOME,
                                                                         "source": "neighbour_day_accepted"}
    assert art["status"] == "complete"
    rows0 = cal.compute_resolved_utc(files, GROUPS, art)
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    drift, blockers = wf.build_drift_validation(files, art, rows0, gpx, None)
    assert not blockers and drift["status"] == "complete" and not drift["destinations"]


@pytest.mark.spec("RUL-acceptance_holds_for_its_proposal", "BLD-offset_acceptance",
                  test="TST-geotag_neighbour_day-an_accepted_neighbour_s_offset_holds_within_the_tolerance")
def test_an_accepted_neighbour_s_offset_holds_within_the_tolerance(tmp_path):
    """The day before's offset, accepted for the day after; the camera's own GPS then gives the day before an offset
    some seconds from it, within the tolerance: the same finding — the acceptance holds, and the offset accepted is
    the one in effect. Farther, it is another proposal, and asks."""
    _, files = _night()
    for f, t in zip(files[:2], ("2024-07-03T21:00:00Z", "2024-07-03T21:30:00Z")):
        f["gps_utc"] = t
    wf, gpx = _wf(tmp_path), _gpx([])
    art = _plan(wf, files, gpx)
    prior = copy.deepcopy(art)
    tol = utils.CONFIG["gpx_anchor_decision_tolerance_seconds"]
    _cells(prior)[f"{CAM}@2024-07-04"]["user_decision"].update(accept_proposal=True,
                                                                accepted_offset_seconds=HOME + int(tol) // 2)
    cell = _cells(_plan(wf, files, gpx, prior))[f"{CAM}@2024-07-04"]
    assert cell["effective_time_anchor"] == {"offset_seconds": HOME + int(tol) // 2, "source": "neighbour_day_accepted"}
    assert not cell["stale_user_decision"]
    _cells(prior)[f"{CAM}@2024-07-04"]["user_decision"]["accepted_offset_seconds"] = HOME + int(tol) + 1
    cell = _cells(_plan(wf, files, gpx, prior))[f"{CAM}@2024-07-04"]
    assert cell["effective_time_anchor"] == "" and cell["stale_user_decision"]


@pytest.mark.spec("RUL-neighbour_day_offset_proposed", "RUL-neighbour_day_no_gap_bound", "BLD-neighbour_day_proposal",
                  test="TST-geotag_neighbour_day-the_day_after_and_no_bound_on_the_gap")
def test_the_day_after_and_no_bound_on_the_gap(tmp_path):
    """With no anchored day before, the day after is offered, however long lies between the two days' photos; a day
    two days away is no neighbour."""
    pts = [cal.GPXPoint(35.6 + i * 0.005, 139.7, datetime(2024, 7, 5, 22, 10 * i, tzinfo=timezone.utc), "night.gpx", 0)
           for i in range(3)]
    files = [_photo("early.arw", "2024:07:04 00:05:00"),                         # a minute past the camera's midnight
             _photo("x.arw", "2024:07:05 23:10:00", 35.6), _photo("y.arw", "2024:07:05 23:20:00", 35.605),
             _photo("far.arw", "2024:07:07 12:00:00")]
    art = _plan(_wf(tmp_path), files, _gpx(pts))
    cells = _cells(art)
    assert cells[f"{CAM}@2024-07-05"]["effective_time_anchor"]["source"] == "gpx_anchor_auto"
    assert cells[f"{CAM}@2024-07-04"]["proposal"]["neighbour_day"]["day"] == "2024-07-05"
    assert cells[f"{CAM}@2024-07-07"]["proposal"]["proposal_source"] != "neighbour_day"
