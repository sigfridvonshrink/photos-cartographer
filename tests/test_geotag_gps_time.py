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

"""Geotag — the time a photo's own GPS fix recorded is evidence of its clock (RUL-gps_time_is_clock_evidence).

A camera with its own GPS writes the fix's UTC beside the position. Less the camera's time it is the clock offset —
below a track anchor, above the offset the photos record and the zone's guess. Readings count only while their GPS
times all differ (a stale fix repeats its time while the camera's moves on) and agree; two or more apply themselves,
one is a proposal. In-process only.
"""
import json
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM, PHONE = "SONY|ILCE-7M4|42", "Apple|iPhone 15|"
GROUPS = {CAM: {"camera_group_class": "camera"}, PHONE: {"camera_group_class": "smartphone"}}
DEST = "6-photos-by-dest/Japan/Kyoto"
TOKYO = {"destinations": {DEST: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}}}


def _gpx(points=()):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {p.source_file: "sha-" + p.source_file for p in points}
    return idx


def _photo(name, naive, gps_utc=None, offset="+01:00", pos=(35.0, 135.7), key=CAM):
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": key,
            "native_gps": {"lat": pos[0], "lon": pos[1]} if pos else None, "has_native_gps": bool(pos),
            "gps_utc": gps_utc, "has_timestamp": True, "source_naive_time": naive,
            "source_time_tag": "EXIF:DateTimeOriginal", "raw_times": {"OffsetTimeOriginal": offset} if offset else {}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True, exist_ok=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _cell(wf, files, prior=TOKYO, gpx=None, key=CAM):
    art, blockers = wf.build_time_decisions(files, GROUPS, prior, gpx or _gpx())
    assert not blockers, blockers
    return art["destinations"][DEST]["camera_group_time_decisions"][key]


def _answer(**ud):
    out = json.loads(json.dumps(TOKYO))
    out["destinations"][DEST]["camera_group_time_decisions"] = {CAM: {"user_decision": ud}}
    return out


# The camera says 10:00 and its clock was on +01:00 (it records so); its fix says 00:59:30 UTC: the clock was 9 h 30 s
# ahead of UTC, and only the fix says by how much.
TWO = [_photo("a.arw", "2024:07:03 10:00:00", "2024-07-03T00:59:30Z"),
       _photo("b.arw", "2024:07:03 11:00:00", "2024-07-03T01:59:31Z")]


@pytest.mark.spec("BLD-gps_time_proposal", test="TST-geotag_gps_time-fix_time_read")
def test_the_fix_time_is_read_from_the_composite_or_the_two_fields():
    """The composite `GPSDateTime` (zone `Z`, or an offset, a fraction dropped), else the date stamp with the time
    stamp; anything that is no time is none."""
    assert cal.gps_fix_utc({"GPSDateTime": "2024:07:03 00:59:30.5Z"}) == "2024-07-03T00:59:30Z"
    assert cal.gps_fix_utc({"GPSDateTime": "2024:07:03 09:59:30+09:00"}) == "2024-07-03T00:59:30Z"
    assert cal.gps_fix_utc({"GPSDateStamp": "2024:07:03", "GPSTimeStamp": "0:59:30"}) == "2024-07-03T00:59:30Z"
    for junk in ({}, {"GPSDateTime": "soon"}, {"GPSDateStamp": "2024:07:03"},
                 {"GPSDateStamp": "0000:00:00", "GPSTimeStamp": "00:00:00"}, {"GPSDateTime": 12}):
        assert cal.gps_fix_utc(junk) is None, junk


@pytest.mark.spec("BLD-gps_time_proposal", test="TST-geotag_gps_time-only_own_position_has_a_fix_time")
def test_the_file_model_reads_a_fix_time_only_with_the_photos_own_position(tmp_path):
    def rec(rel, gps):
        parsed = {"DateTimeOriginal": "2024:07:03 10:00:00", "selected_source_naive_timestamp": "2024:07:03 10:00:00",
                  "selected_source_timestamp_tag": "EXIF:DateTimeOriginal", "camera_group_key": CAM,
                  "GPSDateTime": "2024:07:03 00:59:30Z"}
        if gps:
            parsed.update(GPSLatitude=35.0, GPSLongitude=135.7)
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest", "size": 1,
                "mtime_ns": 1, "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    wf = cal.GeotagWorkflow(str(tmp_path))
    wf.handoff = {"files": [rec(f"{DEST}/a.arw", True), rec(f"{DEST}/b.arw", False)]}
    got = {f["relative_path"]: f["gps_utc"] for f in wf.build_file_model()}
    assert got == {f"{DEST}/a.arw": "2024-07-03T00:59:30Z", f"{DEST}/b.arw": None}


@pytest.mark.spec("RUL-gps_time_is_clock_evidence", "RUL-gps_time_rank", "RUL-gps_times_agreeing_apply", "BLD-gps_time_proposal",
                  "BLD-offset_buckets", test="TST-geotag_gps_time-two_fixes_apply_themselves")
def test_two_fixes_agreeing_apply_themselves_ahead_of_the_recorded_offset(tmp_path):
    """No track: the two fixes' times agree on −32430 — the earliest's — and apply themselves, where the photos'
    recorded +01:00 and the zone's +09:00 are only guesses."""
    cell = _cell(_wf(tmp_path), TWO)
    p = cell["proposal"]
    assert p["proposal_source"] == "gps_time" and p["proposed_offset_seconds"] == -32430
    assert p["gps_time_count"] == 2 and p["proposed_real_utc"] == "2024-07-03T00:59:30Z"
    assert [r["offset_seconds"] for r in p["gps_times"]] == [-32430, -32429]
    assert cell["effective_time_anchor"] == {"offset_seconds": -32430, "source": "gps_time_auto"}
    assert cell["decision_mode"] == "auto_resolved" and not cell["requires_user_input"]


@pytest.mark.spec("RUL-gps_times_agreeing_apply", "BLD-auto_apply_settings",
                  test="TST-geotag_gps_time-applies_only_as_configured")
def test_two_fixes_apply_themselves_only_as_the_setting_for_several_anchors_allows(tmp_path, monkeypatch):
    monkeypatch.setitem(utils.CONFIG["camera_time_and_timezone_policy"], "multi_anchor_auto_apply", False)
    cell = _cell(_wf(tmp_path), TWO)
    assert cell["proposal"]["proposal_source"] == "gps_time" and cell["effective_time_anchor"] == ""


@pytest.mark.spec("RUL-single_gps_time_proposed", "BLD-gps_time_proposal", "BLD-offset_acceptance",
                  test="TST-geotag_gps_time-one_fix_is_a_proposal")
def test_one_fix_is_a_proposal_to_accept(tmp_path):
    """One photo with a fix time: proposed, never applied by itself — `single_anchor_auto_apply` set or not. An
    acceptance holds within the decision tolerance, as one of a GPS proposal does."""
    wf = _wf(tmp_path)
    one = TWO[:1]
    cell = _cell(wf, one)
    assert cell["proposal"]["proposal_source"] == "gps_time" and cell["proposal"]["confidence"] == "review_required"
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"]
    accepted = _cell(wf, one, _answer(accept_proposal=True, accepted_offset_seconds=-32400, manual_offset_seconds=""))
    assert accepted["effective_time_anchor"] == {"offset_seconds": -32400, "source": "gps_time_accepted"}
    far_off = _cell(wf, one, _answer(accept_proposal=True, accepted_offset_seconds=-3600, manual_offset_seconds=""))
    assert far_off["stale_user_decision"] and far_off["effective_time_anchor"] == ""


@pytest.mark.spec("RUL-repeated_gps_time_not_counted", "BLD-gps_time_proposal",
                  test="TST-geotag_gps_time-a_repeated_fix_time_counts_for_nothing")
def test_a_repeated_fix_time_counts_for_nothing(tmp_path):
    """A stale fix: the GPS says 00:59:30 for two photos an hour apart. Nothing is proposed from the fixes — the
    photos' recorded offset is — and the cell says why. A burst (same fix time, same camera time) is one reading."""
    stale = [TWO[0], _photo("b.arw", "2024:07:03 11:00:00", "2024-07-03T00:59:30Z")]
    cell = _cell(_wf(tmp_path), stale)
    assert cell["proposal"]["proposal_source"] == "recorded_offset"
    assert cell["gps_time_set_aside"] == {"reason": "repeated_gps_time", "gps_time_count": 2,
                                          "example": f"{DEST}/a.arw"}
    burst = [TWO[0], _photo("a2.arw", "2024:07:03 10:00:00", "2024-07-03T00:59:30Z"), TWO[1]]
    cell = _cell(_wf(tmp_path), burst)
    assert cell["proposal"]["proposal_source"] == "gps_time" and cell["proposal"]["gps_time_count"] == 2


@pytest.mark.spec("RUL-repeated_gps_time_not_counted", "BLD-gps_time_proposal",
                  test="TST-geotag_gps_time-disagreeing_fixes_count_for_nothing")
def test_fixes_whose_offsets_disagree_count_for_nothing(tmp_path):
    apart = [TWO[0], _photo("b.arw", "2024:07:03 11:00:00", "2024-07-03T02:09:30Z")]   # 10 min off the first
    cell = _cell(_wf(tmp_path), apart)
    assert cell["proposal"]["proposal_source"] == "recorded_offset"
    assert cell["gps_time_set_aside"]["reason"] == "offsets_disagree"
    assert cell["gps_time_set_aside"]["offsets_seconds"] == [-32430, -31830]


@pytest.mark.spec("RUL-gps_time_is_clock_evidence", "RUL-gps_time_rank", "BLD-offset_buckets",
                  test="TST-geotag_gps_time-a_track_anchor_comes_first")
def test_a_track_anchor_comes_before_the_fix_time(tmp_path):
    """A track passes where both photos were taken, at 00:30 and 01:30 UTC: the track's −34200 is proposed, the
    fixes' times not read."""
    pts = [cal.GPXPoint(35.0, 135.7, datetime(2024, 7, 3, 0, 30, tzinfo=timezone.utc), "t.gpx", 0),
           cal.GPXPoint(35.1, 135.9, datetime(2024, 7, 3, 1, 0, tzinfo=timezone.utc), "t.gpx", 1),
           cal.GPXPoint(35.0, 135.7, datetime(2024, 7, 3, 1, 30, tzinfo=timezone.utc), "t.gpx", 2)]
    cell = _cell(_wf(tmp_path), TWO, gpx=_gpx(pts))
    assert cell["proposal"]["proposal_source"] == "gpx_self_anchor"
    assert cell["proposal"]["proposed_offset_seconds"] == -34200 and "gps_time_set_aside" not in cell


@pytest.mark.spec("RUL-gps_time_far_from_evidence_withheld", "BLD-offset_far_from_evidence",
                  test="TST-geotag_gps_time-far_from_evidence_withheld")
def test_fixes_far_from_every_other_device_are_withheld(tmp_path):
    """A camera writing its local time into the GPS field: its fixes say 10:00 UTC, three days from the phone's
    photo of the same visit. The offset is shown, and the cell asks for one of the user's own."""
    wrong = [_photo("a.arw", "2024:07:03 10:00:00", "2024-07-06T10:00:00Z"),
             _photo("b.arw", "2024:07:03 11:00:00", "2024-07-06T11:00:00Z")]
    phone = [_photo("p.heic", "2024:07:03 10:30:00", None, "+09:00", None, PHONE)]
    cell = _cell(_wf(tmp_path), wrong + phone)
    assert cell["proposal"]["proposal_source"] == "gps_time" and cell["proposal"]["far_from_evidence"]
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"]


@pytest.mark.spec("BLD-gps_time_proposal", "BLD-drift_validation", test="TST-geotag_gps_time-no_drift_check")
def test_an_offset_from_the_fixes_is_not_drift_checked(tmp_path):
    """Tracks lie by the photos' times but not by their places: the fixes' offset is the camera's own GPS's, and no
    drift cell follows it."""
    wf = _wf(tmp_path)
    near = [cal.GPXPoint(10.0, 10.0, datetime(2024, 7, 3, 1, 0, tzinfo=timezone.utc), "t.gpx", 0)]
    gpx = _gpx(near)
    art, _b = wf.build_time_decisions(TWO, GROUPS, TOKYO, gpx)
    assert art["destinations"][DEST]["camera_group_time_decisions"][CAM]["effective_time_anchor"]["source"] == "gps_time_auto"
    rows0 = cal.compute_resolved_utc(TWO, GROUPS, art)
    (tmp_path / "ws" / ".photos-ingest" / "photos-21-time-decisions.json").write_text(json.dumps(art))
    drift, _b = wf.build_drift_validation(TWO, art, rows0, gpx, None)
    assert drift["destinations"] == {}
    assert {r["resolved_utc"] for r in rows0} == {"2024-07-03T00:59:30Z", "2024-07-03T01:59:30Z"}
