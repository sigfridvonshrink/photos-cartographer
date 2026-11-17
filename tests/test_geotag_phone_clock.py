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

"""Geotag — a phone's clock checked against its own GPS (RUL-phone_anchored_like_camera).

A phone takes its time from the network, but a phone set to the wrong zone or hour, or whose tag is missing, would
misplace every photo of the day. Its photos holding their own position are anchored as a camera's are — or read by
their fixes' times — and the offset found is set against the one they are read by: agreeing, nothing; disagreeing,
several photos apply it to the phone's day there, one photo's is a proposal. In-process only.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

PHONE, CAM = "Apple|iPhone 15|", "SONY|ILCE-7M4|42"
GROUPS = {PHONE: {"camera_group_class": "smartphone"}, CAM: {"camera_group_class": "camera"}}
DEST, OTHER = "6-photos-by-dest/Bruges", "6-photos-by-dest/Ghent"
ZONE = {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Brussels"}}}
PRIOR = {"destinations": {DEST: dict(ZONE), OTHER: dict(ZONE)}}


def _gpx(points=()):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {p.source_file: "sha-" + p.source_file for p in points}
    return idx


def _track(*stops):
    """A walk: at each (lat, utc) a point, with one far away between, so each stop is one pass."""
    out = []
    for i, (lat, when) in enumerate(stops):
        out.append(cal.GPXPoint(lat, 3.2, when, "walk.gpx", 2 * i))
        out.append(cal.GPXPoint(lat + 0.05, 3.2, when + timedelta(minutes=10), "walk.gpx", 2 * i + 1))
    return out


def _utc(h, m=0):
    return datetime(2024, 7, 3, h, m, tzinfo=timezone.utc)


def _photo(name, naive, offset="+02:00", pos=None, gps_utc=None, dest=DEST, key=PHONE):
    return {"relative_path": f"{dest}/{name}", "destination": dest, "camera_group_key": key,
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


def _build(wf, files, gpx, prior=PRIOR):
    art, blockers = wf.build_time_decisions(files, GROUPS, prior, gpx)
    assert not blockers, blockers
    return art


def _cells(art, dest=DEST):
    return art["destinations"][dest]["camera_group_time_decisions"]


def _answer(**ud):
    out = json.loads(json.dumps(PRIOR))
    out["destinations"][DEST]["camera_group_time_decisions"] = {PHONE: {"user_decision": ud}}
    return out


# The phone's clock was an hour slow that day: it says 09:00 +02:00 (07:00Z) where the track has it at 08:00Z.
SLOW = [_photo("a.heic", "2024:07:03 09:00:00", pos=(51.0, 3.2)), _photo("b.heic", "2024:07:03 10:00:00", pos=(51.2, 3.2)),
        _photo("c.heic", "2024:07:03 11:00:00")]
SLOW_TRACK = _track((51.0, _utc(8)), (51.2, _utc(9)))


@pytest.mark.spec("RUL-phone_anchored_like_camera", "RUL-phone_agreeing_anchor_changes_nothing", "BLD-phone_offset_cell",
                  test="TST-geotag_phone_clock-agreeing_phone_asks_nothing")
def test_a_phone_whose_track_agrees_asks_nothing(tmp_path):
    """The track has the phone where its tags say, a minute off — within `gpx_anchor_decision_tolerance_seconds`:
    no cell, and its photos are read by their tags as before."""
    files = [_photo("a.heic", "2024:07:03 10:01:00", pos=(51.0, 3.2)), _photo("b.heic", "2024:07:03 11:01:00", pos=(51.2, 3.2))]
    art = _build(_wf(tmp_path), files, _gpx(_track((51.0, _utc(8)), (51.2, _utc(9)))))
    assert _cells(art) == {}
    rows = cal.compute_resolved_utc(files, GROUPS, art)
    assert {r["time_rule_used"] for r in rows} == {"smartphone_native_offset"}


@pytest.mark.spec("RUL-phone_anchored_like_camera", "RUL-phone_disagreeing_anchors_apply", "BLD-phone_offset_cell",
                  "BLD-resolved_utc", test="TST-geotag_phone_clock-several_disagreeing_anchors_apply")
def test_several_photos_disagreeing_with_the_tags_apply_the_anchored_offset(tmp_path):
    """The tags read the photos by −7200; the two on the track agree on −3600: the anchored offset applies itself to
    every photo of the phone's day there, the one with no position included, the cell showing it."""
    art = _build(_wf(tmp_path), SLOW, _gpx(SLOW_TRACK))
    cell = _cells(art)[PHONE]
    assert cell["camera_group_class"] == "smartphone"
    assert cell["proposal"]["proposal_source"] == "gpx_self_anchor" and cell["proposal"]["proposed_offset_seconds"] == -3600
    assert cell["effective_time_anchor"] == {"offset_seconds": -3600, "source": "gpx_anchor_auto"}
    assert cell["phone"] == {"applies_to": "every_photo", "photos": 3, "read_by_offsets": [-7200]}
    assert not cell["requires_user_input"] and not art["requires_user_input"]
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(SLOW, GROUPS, art)}
    assert rows[f"{DEST}/c.heic"]["resolved_utc"] == "2024-07-03T10:00:00Z"
    assert {r["time_rule_used"] for r in rows.values()} == {"camera_group_offset"}


@pytest.mark.spec("RUL-phone_single_anchor_proposed", "BLD-phone_offset_cell",
                  test="TST-geotag_phone_clock-one_photo_is_a_proposal")
def test_one_phone_photo_disagreeing_is_a_proposal(tmp_path, monkeypatch):
    """One photo on the track: proposed, never applied by itself — even with `single_anchor_auto_apply` on; accepted,
    it takes effect."""
    monkeypatch.setitem(utils.CONFIG["camera_time_and_timezone_policy"], "single_anchor_auto_apply", True)
    files = SLOW[:1] + SLOW[2:]
    wf = _wf(tmp_path)
    cell = _cells(_build(wf, files, _gpx(SLOW_TRACK)))[PHONE]
    assert cell["proposal"]["anchor_count"] == 1 and cell["effective_time_anchor"] == "" and cell["requires_user_input"]
    rows = cal.compute_resolved_utc(files, GROUPS, _build(wf, files, _gpx(SLOW_TRACK)))
    assert {r["resolved_utc_status"] for r in rows} == {"unresolved"}          # waits for the answer
    ok = _cells(_build(wf, files, _gpx(SLOW_TRACK), _answer(accept_proposal=True, accepted_offset_seconds=-3600,
                                                          manual_offset_seconds="", keep_as_recorded=False)))[PHONE]
    assert ok["effective_time_anchor"] == {"offset_seconds": -3600, "source": "gpx_anchor_accepted"}


@pytest.mark.spec("RUL-phone_kept_as_recorded", "BLD-phone_offset_cell", test="TST-geotag_phone_clock-kept_as_recorded")
def test_the_user_can_keep_the_phone_as_it_records_itself(tmp_path):
    """The track is someone else's: kept as recorded, the phone's photos are read by their tags, the cell resolved."""
    files = SLOW[:1] + SLOW[2:]
    art = _build(_wf(tmp_path), files, _gpx(SLOW_TRACK), _answer(keep_as_recorded=True, accept_proposal=False,
                                                                  accepted_offset_seconds="", manual_offset_seconds=""))
    cell = _cells(art)[PHONE]
    assert cell["effective_time_anchor"] == {"source": "as_recorded"} and not cell["requires_user_input"]
    assert cell["user_decision"]["keep_as_recorded"] is True
    rows = cal.compute_resolved_utc(files, GROUPS, art)
    assert {r["time_rule_used"] for r in rows} == {"smartphone_native_offset"}
    bad = _answer(keep_as_recorded="yes")
    _art, blockers = _wf(tmp_path).build_time_decisions(files, GROUPS, bad, _gpx(SLOW_TRACK))
    assert any("keep_as_recorded must be true or false" in b for b in blockers)


@pytest.mark.spec("RUL-gps_time_checks_phone", "RUL-phone_disagreeing_anchors_apply", "BLD-phone_offset_cell",
                  test="TST-geotag_phone_clock-fix_times_check_a_phone")
def test_the_fixes_times_check_a_phone_where_no_track_does(tmp_path):
    """No track: two fixes say 08:00Z and 09:00Z where the tags read 07:00Z and 08:00Z — the phone's day is read by
    the fixes' offset."""
    files = [_photo("a.heic", "2024:07:03 09:00:00", pos=(51.0, 3.2), gps_utc="2024-07-03T08:00:00Z"),
             _photo("b.heic", "2024:07:03 10:00:00", pos=(51.2, 3.2), gps_utc="2024-07-03T09:00:00Z")]
    cell = _cells(_build(_wf(tmp_path), files, _gpx()))[PHONE]
    assert cell["proposal"]["proposal_source"] == "gps_time"
    assert cell["effective_time_anchor"] == {"offset_seconds": -3600, "source": "gps_time_auto"}


@pytest.mark.spec("RUL-gps_time_checks_phone", "BLD-phone_offset_cell",
                  test="TST-geotag_phone_clock-every_fix_reading_checks_the_phone")
def test_every_fix_reading_is_set_against_the_phone_past_those_the_record_lists(tmp_path):
    """Twenty-one fixes agree on the phone's clock; the photos' tags agree with it but the last one's, which reads its
    photo an hour off. Every reading is set against the offsets the photos are read by, not only the twenty the
    record lists: the phone's day disagrees, and its cell is made."""
    files = [_photo(f"p{i:02}.heic", f"2024:07:03 {8 + i // 4:02}:{(i % 4) * 15:02}:00",
                    "+03:00" if i == 20 else "+02:00", pos=(51.0 + i / 100, 3.2),
                    gps_utc=f"2024-07-03T{6 + i // 4:02}:{(i % 4) * 15:02}:00Z") for i in range(21)]
    cell = _cells(_build(_wf(tmp_path), files, _gpx()))[PHONE]
    assert cell["proposal"]["proposal_source"] == "gps_time" and len(cell["proposal"]["gps_times"]) == 20
    assert cell["phone"]["applies_to"] == "every_photo" and -10800 in cell["phone"]["read_by_offsets"]


@pytest.mark.spec("RUL-phone_agreeing_anchor_changes_nothing", "BLD-phone_offset_cell",
                  test="TST-geotag_phone_clock-a_photo_read_by_no_offset_does_not_disagree")
def test_a_photo_the_zone_cannot_read_does_not_make_the_phone_disagree(tmp_path):
    """The night the clocks go back: two tagged photos agree with their fixes, and one recording no offset falls in
    the hour the zone repeats, so it is read by no offset. It says nothing either way: the phone agrees, and no cell
    reads its whole day by the fixes."""
    files = [_photo("a.heic", "2024:10:27 10:00:00", "+01:00", pos=(51.0, 3.2), gps_utc="2024-10-27T09:00:00Z"),
             _photo("b.heic", "2024:10:27 11:00:00", "+01:00", pos=(51.1, 3.2), gps_utc="2024-10-27T10:00:00Z"),
             _photo("c.heic", "2024:10:27 02:30:00", None, pos=(51.2, 3.2), gps_utc="2024-10-27T01:30:00Z")]
    cells = _cells(_build(_wf(tmp_path), files, _gpx()))
    assert not [c for c in cells.values() if (c.get("phone") or {}).get("applies_to") == "every_photo"], cells


@pytest.mark.spec("BLD-phone_offset_cell", "BLD-offset_shared_within_day", test="TST-geotag_phone_clock-not_shared")
def test_a_phones_day_offset_is_not_passed_to_another_destination(tmp_path):
    """The phone's anchored offset in Bruges says nothing of its photos in Ghent, where they hold no position: Ghent
    has no phone cell, and its photos are read by their tags."""
    files = SLOW + [_photo("g.heic", "2024:07:03 15:00:00", dest=OTHER)]
    art = _build(_wf(tmp_path), files, _gpx(SLOW_TRACK))
    assert _cells(art, OTHER) == {}
    assert PHONE in _cells(art)
