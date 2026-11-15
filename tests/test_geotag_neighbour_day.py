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
or after of the same camera in the same destination, where that day is anchored — a proposal to accept, then checked
on the tracks by the drift check. From conftest.py.
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
    its own cell still, asking."""
    pts, files = _night()
    art = _plan(_wf(tmp_path), files, _gpx(pts))
    cells = _cells(art)
    before, after = cells[f"{CAM}@2024-07-03"], cells[f"{CAM}@2024-07-04"]
    assert before["effective_time_anchor"] == {"offset_seconds": HOME, "source": "gpx_anchor_auto"}
    assert after["proposal"] == {"proposal_source": "neighbour_day", "proposed_offset_seconds": HOME,
                                 "neighbour_day": {"day": "2024-07-03", "bucket": f"{CAM}@2024-07-03"},
                                 "confidence": "review_required"}
    assert after["day"] == "2024-07-04" and after["requires_user_input"] is True


@pytest.mark.spec("RUL-neighbour_day_offset_needs_acceptance", "RUL-neighbour_day_offset_drift_checked",
                  "BLD-neighbour_day_proposal", "BLD-drift_validation",
                  test="TST-geotag_neighbour_day-accepted_it_is_checked_on_the_tracks")
def test_accepted_it_is_checked_on_the_tracks(tmp_path):
    """Unaccepted, the neighbour's offset takes no effect; accepted, it does, and the drift check asks for it to be
    confirmed on the tracks that lie by the day's photos."""
    wf, (pts, files) = _wf(tmp_path), _night()
    gpx = _gpx(pts)
    art = _plan(wf, files, gpx)
    assert _cells(art)[f"{CAM}@2024-07-04"]["effective_time_anchor"] == ""
    prior = copy.deepcopy(art)
    _cells(prior)[f"{CAM}@2024-07-04"]["user_decision"].update(accept_proposal=True, accepted_offset_seconds=HOME)
    art = _plan(wf, files, gpx, prior)
    cell = _cells(art)[f"{CAM}@2024-07-04"]
    assert cell["effective_time_anchor"] == {"offset_seconds": HOME, "source": "neighbour_day_accepted"}
    assert art["status"] == "complete"
    rows0 = cal.compute_resolved_utc(files, GROUPS, art)
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    drift, blockers = wf.build_drift_validation(files, art, rows0, gpx, None)
    assert not blockers
    assert list(drift["destinations"][DEST]["drift_decisions"]) == [f"{CAM}@2024-07-04"]
    assert drift["destinations"][DEST]["drift_decisions"][f"{CAM}@2024-07-04"]["requires_user_input"] is True


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
