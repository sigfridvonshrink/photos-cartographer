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

"""Geotag — a camera's clock offset proposed from the offset its photos record (RUL-recorded_offset_proposed).

A camera that writes `OffsetTimeOriginal` with its time says which zone its clock was on: a body left on home time
in Japan records +01:00. Where its photos agree on one offset, that is proposed ahead of the destination's zone; where
they record different ones, none is proposed from them. The camera's own GPS still comes first. In-process only.
"""
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-7M4|42"
GROUPS = {CAM: {"camera_group_class": "camera"}}
BYDEST = "6-photos-by-dest"
DEST = f"{BYDEST}/Japan/Kyoto"
TOKYO = {"destinations": {DEST: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}}}


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {p.source_file: "sha-" + p.source_file for p in points}   # what a read of the files records
    return idx


def _pt(lat, lon, hour, minute=0):
    return cal.GPXPoint(lat, lon, datetime(2024, 7, 3, hour, minute, 0, tzinfo=timezone.utc), "t.gpx", 0)


def _photo(name, naive="2024:07:03 10:00:00", offset="+01:00", gps=None, dest=DEST):
    raw = {"OffsetTimeOriginal": offset} if offset is not None else {}
    return {"relative_path": f"{dest}/{name}", "destination": dest, "camera_group_key": CAM,
            "native_gps": ({"lat": gps[0], "lon": gps[1]} if gps else None), "has_native_gps": bool(gps),
            "has_timestamp": True, "source_naive_time": naive, "source_time_tag": "EXIF:DateTimeOriginal",
            "raw_times": raw}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _build(wf, files, gpx, prior=TOKYO):
    art, blockers = wf.build_time_decisions(files, GROUPS, prior, gpx)
    assert not blockers, blockers
    return art


def _cell(art, dest=DEST):
    return art["destinations"][dest]["camera_group_time_decisions"][CAM]


def _answer(prior, dest, **ud):
    out = {"destinations": {d: dict(v) for d, v in prior["destinations"].items()}}
    out["destinations"].setdefault(dest, {})["camera_group_time_decisions"] = {CAM: {"user_decision": ud}}
    return out


@pytest.mark.spec("RUL-recorded_offset_proposed", "BLD-recorded_offset_proposal", "RUL-proposals_need_acceptance",
                  "RUL-offset_from_own_evidence", test="TST-geotag_recorded_offset-proposed_ahead_of_the_zone")
def test_the_recorded_offset_is_proposed_ahead_of_the_zone(tmp_path):
    """A body left on home time in Kyoto: its photos record +01:00, the zone is at +09:00. The proposal is the clock
    the photos record — −3600, not the zone's −32400 — and, with no track to check it against, it waits for the
    user's acceptance; accepted, it takes effect as the recorded offset accepted."""
    wf = _wf(tmp_path)
    files = [_photo("a.arw", "2024:07:03 10:00:00"), _photo("b.arw", "2024:07:03 11:30:00"),
             _photo("c.arw", "2024:07:03 12:00:00", offset=None)]          # one recording none says nothing
    cell = _cell(_build(wf, files, _gpx([])))
    p = cell["proposal"]
    assert p["proposal_source"] == "recorded_offset" and p["proposed_offset_seconds"] == -3600
    assert p["recorded_offset_seconds"] == 3600 and p["recorded_by"] == 2 and p["example"] == f"{DEST}/a.arw"
    assert p["proposed_real_utc"] == "2024-07-03T09:00:00Z"
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"]
    assert cell["representative"] == {"source_file": f"{DEST}/a.arw", "camera_source_naive_time": "2024:07:03 10:00:00"}
    accepted = _cell(_build(wf, files, _gpx([]), _answer(TOKYO, DEST, accept_proposal=True,
                                                         accepted_offset_seconds=-3600, manual_offset_seconds="")))
    assert accepted["effective_time_anchor"] == {"offset_seconds": -3600, "source": "recorded_offset_accepted"}
    assert not accepted["requires_user_input"] and "decision_mode" not in accepted
    # it needs no timezone: the photos say which zone the clock was on
    bare = _cell(_build(wf, files, _gpx([]), None))
    assert bare["proposal"]["proposal_source"] == "recorded_offset" and bare["proposal"]["proposed_offset_seconds"] == -3600


@pytest.mark.spec("BLD-recorded_offset_proposal", test="TST-geotag_recorded_offset-an_offset_that_is_none_is_none")
def test_a_recorded_value_that_is_no_offset_is_none(tmp_path):
    """A value in the offset tag that is no offset is read as none, never loosely: with it only, the zone proposes."""
    wf = _wf(tmp_path)
    for junk in ("+25:00", "local", "", "9"):
        cell = _cell(_build(wf, [_photo("a.arw", offset=junk)], _gpx([])))
        assert cell["proposal"]["proposal_source"] == "timezone_naive", junk
        assert "recorded_offsets_differ" not in cell
    # and one such value beside a real one does not make two
    cell = _cell(_build(wf, [_photo("a.arw", offset="garbage"), _photo("b.arw", offset="+01:00")], _gpx([])))
    assert cell["proposal"]["proposal_source"] == "recorded_offset" and cell["proposal"]["recorded_by"] == 1


@pytest.mark.spec("RUL-differing_recorded_offsets_propose_none", "BLD-recorded_offset_proposal",
                  test="TST-geotag_recorded_offset-different_offsets_propose_none")
def test_photos_recording_different_offsets_propose_none(tmp_path):
    """Photos of one day recording +01:00 and +09:00: no offset is proposed from either — the zone's guess is made as
    it would be with none recorded — and the cell names the offsets it saw, with a count and a photo of each."""
    wf = _wf(tmp_path)
    files = [_photo("a.arw", offset="+01:00"), _photo("b.arw", "2024:07:03 11:00:00", offset="+09:00"),
             _photo("c.arw", "2024:07:03 12:00:00", offset="+09:00")]
    cell = _cell(_build(wf, files, _gpx([])))
    assert cell["proposal"]["proposal_source"] == "timezone_naive"
    assert cell["proposal"]["proposed_offset_seconds"] == -32400
    assert cell["recorded_offsets_differ"] == [
        {"recorded_offset_seconds": 3600, "photos": 1, "example": f"{DEST}/a.arw"},
        {"recorded_offset_seconds": 32400, "photos": 2, "example": f"{DEST}/b.arw"}]
    # with no zone either, nothing is proposed at all
    bare = _cell(_build(wf, files, _gpx([]), None))
    assert bare["proposal"]["proposal_source"] == "manual_required" and bare["recorded_offsets_differ"]


@pytest.mark.spec("RUL-timezone_offset_asked_once", "RUL-track_confirmation_is_acceptance", "BLD-recorded_offset_proposal",
                  test="TST-geotag_recorded_offset-asked_once_against_the_tracks")
def test_the_recorded_offset_is_asked_once_against_the_tracks(tmp_path):
    """Tracks lie by the photos: the recorded offset goes to the drift check as it stands, photos-21 asking nothing;
    the confirmation there is its acceptance, and the photo resolves under it."""
    wf = _wf(tmp_path)
    files = [_photo("a.arw", "2024:07:03 10:00:00")]
    track = [_pt(35.0, 135.7, 8), _pt(35.1, 135.8, 10)]
    art = _build(wf, files, _gpx(track))
    cell = _cell(art)
    assert cell["effective_time_anchor"] == {"offset_seconds": -3600, "source": "recorded_offset_unconfirmed"}
    assert cell["decision_mode"] == "to_be_confirmed_against_tracks" and not art["requires_user_input"]
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    rows0 = cal.compute_resolved_utc(files, GROUPS, art)
    drift, blk = wf.build_drift_validation(files, art, rows0, _gpx(track), None)
    asked = drift["destinations"][DEST]["drift_decisions"][CAM]
    assert not blk and asked["requires_user_input"] and asked["proposal"]["current_offset_seconds"] == -3600
    # never passed over, whatever track lies by it
    gone, _ = wf.build_drift_validation(files, art, rows0, _gpx([]), None)
    assert gone["destinations"][DEST]["drift_decisions"][CAM]["requires_user_input"]
    asked["user_decision"] = {"confirmed": True, "corrected_offset_seconds": "", "confirmed_offset_seconds": -3600,
                              "confirmed_against_tracks": asked["proposal"]["tracks"]}    # as the editor copies them
    done, blk = wf.build_drift_validation(files, art, rows0, _gpx(track), drift)
    assert not blk and done["status"] == "complete"
    (row,) = cal.compute_resolved_utc(files, GROUPS, art, cal.drift_offset_overrides(done))
    assert row["resolved_utc"] == "2024-07-03T09:00:00Z"


@pytest.mark.spec("RUL-recorded_offset_proposed", "RUL-offset_shared_within_day",
                  test="TST-geotag_recorded_offset-the_camera_s_gps_comes_first")
def test_the_camera_s_own_gps_comes_before_the_recorded_offset(tmp_path):
    """The offset the camera's own positions give — here, or the same day in another destination — is proposed
    before the one its photos record: GPS measures the clock, the tag states a setting."""
    wf = _wf(tmp_path)
    track = [_pt(35.0, 135.7, 8), _pt(35.1, 135.8, 9)]
    # the camera's clock is really on +09:00 (its GPS matches the track at 08:00Z for a 17:00 camera time),
    # while its tag says +01:00
    here = [_photo("a.arw", "2024:07:03 17:00:00", gps=(35.0, 135.7)), _photo("b.arw", "2024:07:03 18:00:00", gps=(35.1, 135.8))]
    cell = _cell(_build(wf, here, _gpx(track)))
    assert cell["proposal"]["proposal_source"] == "gpx_self_anchor"
    assert cell["proposal"]["proposed_offset_seconds"] == -32400
    other = f"{BYDEST}/Japan/Nara"
    there = [_photo("c.arw", "2024:07:03 19:00:00", dest=other)]
    prior = {"destinations": {d: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}
                              for d in (DEST, other)}}
    art = _build(wf, here + there, _gpx(track), prior)
    nara = _cell(art, other)
    assert nara["proposal"]["proposal_source"] == "same_day_elsewhere"
    assert nara["proposal"]["proposed_offset_seconds"] == -32400
