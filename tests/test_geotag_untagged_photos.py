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

"""Geotag — phone photos with no offset tag, and files naming no camera, are no longer read by the zone unasked
(RUL-untagged_phone_photo_read_as_siblings, RUL-camera_less_files_asked_per_destination).

A phone photo recording no offset is read by the zone unasked only where the phone's tagged photos of that day show
the zone's offset; else its own GPS settles it; with neither it rides the drift check where there are tracks, and is
asked where there are none. Files naming no camera and recording no offset are one question per destination, kept.
In-process only.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

PHONE, NOBODY = "Apple|iPhone 15|", utils.NO_IDENTITY_KEY
GROUPS = {PHONE: {"camera_group_class": "smartphone"}, NOBODY: {"camera_group_class": "unidentified"}}
DEST = "6-photos-by-dest/Bruges"
ZONE = {"destinations": {DEST: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Brussels"}}}}}


def _gpx(points=()):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {p.source_file: "sha-" + p.source_file for p in points}
    return idx


def _photo(name, naive, offset=None, pos=None, key=PHONE):
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": key,
            "native_gps": {"lat": pos[0], "lon": pos[1]} if pos else None, "has_native_gps": bool(pos),
            "gps_utc": None, "has_timestamp": True, "source_naive_time": naive, "content_fingerprint": "fp-" + name,
            "source_time_tag": "EXIF:DateTimeOriginal", "raw_times": {"OffsetTimeOriginal": offset} if offset else {}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True, exist_ok=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _build(wf, files, gpx=None, prior=ZONE):
    art, blockers = wf.build_time_decisions(files, GROUPS, prior, gpx or _gpx())
    assert not blockers, blockers
    return art


def _with(prior, **entries):
    out = json.loads(json.dumps(prior))
    out["destinations"][DEST].update(entries)
    return out


def _rows(files, art):
    return {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art)}


@pytest.mark.spec("RUL-untagged_phone_photo_read_as_siblings", "BLD-phone_offset_cell",
                  test="TST-geotag_untagged_photos-read_as_the_tagged_ones_show")
def test_an_untagged_photo_is_read_by_the_zone_where_its_tagged_siblings_show_the_zone(tmp_path):
    files = [_photo("a.heic", "2024:07:03 10:00:00", "+02:00"), _photo("b.heic", "2024:07:03 11:00:00")]
    art = _build(_wf(tmp_path), files)
    assert art["destinations"][DEST]["camera_group_time_decisions"] == {} and not art["requires_user_input"]
    r = _rows(files, art)[f"{DEST}/b.heic"]
    assert (r["time_rule_used"], r["resolved_utc"]) == ("destination_timezone", "2024-07-03T09:00:00Z")


@pytest.mark.spec("RUL-untagged_phone_photo_asked", "RUL-untagged_phone_photo_read_as_siblings", "BLD-phone_offset_cell",
                  "RUL-proposals_need_acceptance", test="TST-geotag_untagged_photos-asked_where_nothing_settles_it")
def test_an_untagged_photo_with_nothing_to_settle_it_is_asked(tmp_path):
    """No tagged sibling, no position, no track: the zone's reading is proposed for the phone's untagged photos of the
    day and waits for acceptance; accepted, each photo is read by the zone at its own time — the phone's clock follows
    the daylight-saving change of 27 October 2024 (02:30 → +01:00 after, +02:00 before)."""
    wf = _wf(tmp_path)
    files = [_photo("a.heic", "2024:10:27 01:00:00"), _photo("b.heic", "2024:10:27 09:00:00")]
    cell = _build(wf, files)["destinations"][DEST]["camera_group_time_decisions"][PHONE]
    assert cell["phone"] == {"applies_to": "untagged_photos", "photos": 2, "read_by_offsets": []}
    assert cell["proposal"]["proposal_source"] == "timezone_naive" and cell["proposal"]["proposed_offset_seconds"] == -7200
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"]
    prior = _with(ZONE, camera_group_time_decisions={PHONE: {"user_decision": {
        "accept_proposal": True, "accepted_offset_seconds": -7200, "manual_offset_seconds": "", "keep_as_recorded": False}}})
    art = _build(wf, files, prior=prior)
    assert art["destinations"][DEST]["camera_group_time_decisions"][PHONE]["effective_time_anchor"]["source"] == "timezone_accepted"
    rows = _rows(files, art)
    assert rows[f"{DEST}/a.heic"]["resolved_utc"] == "2024-10-26T23:00:00Z"
    assert rows[f"{DEST}/b.heic"]["resolved_utc"] == "2024-10-27T08:00:00Z"


@pytest.mark.spec("RUL-untagged_phone_photo_asked", "RUL-untagged_phone_photo_read_as_siblings", "BLD-phone_offset_cell",
                  "BLD-recorded_offset_proposal",
                  test="TST-geotag_untagged_photos-tagged_siblings_on_another_zone_propose_theirs")
def test_tagged_siblings_on_another_zone_propose_their_offset(tmp_path):
    """The phone's tagged photos record +01:00 where Brussels is at +02:00 (kept despite them): its untagged photo is
    proposed the offset its siblings record, not the zone's."""
    prior = json.loads(json.dumps(ZONE))
    prior["destinations"][DEST]["destination_timezone"]["user_decision"]["confirmed_despite_recorded_offsets"] = [3600]
    files = [_photo("a.heic", "2024:07:03 10:00:00", "+01:00"), _photo("b.heic", "2024:07:03 11:00:00")]
    cell = _build(_wf(tmp_path), files, prior=prior)["destinations"][DEST]["camera_group_time_decisions"][PHONE]
    assert cell["phone"]["applies_to"] == "untagged_photos" and cell["phone"]["photos"] == 1
    assert cell["proposal"]["proposal_source"] == "recorded_offset" and cell["proposal"]["proposed_offset_seconds"] == -3600


@pytest.mark.spec("RUL-untagged_phone_photo_asked", "RUL-timezone_offset_asked_once", "BLD-phone_offset_cell",
                  "BLD-drift_validation", test="TST-geotag_untagged_photos-rides_the_drift_check")
def test_an_untagged_photo_by_the_tracks_rides_the_drift_check(tmp_path):
    """Tracks lie by the untagged photos' times: nothing is asked in photos-21, and the drift check holds the photos
    the cell offsets — the untagged ones alone."""
    wf = _wf(tmp_path)
    prior = json.loads(json.dumps(ZONE))
    prior["destinations"][DEST]["destination_timezone"]["user_decision"]["confirmed_despite_recorded_offsets"] = [3600]
    files = [_photo("a.heic", "2024:07:03 10:00:00", "+01:00"), _photo("b.heic", "2024:07:03 11:00:00")]
    gpx = _gpx([cal.GPXPoint(51.2, 3.2, datetime(2024, 7, 3, 9, 0, tzinfo=timezone.utc), "t.gpx", 0)])
    art = _build(wf, files, gpx, prior)
    cell = art["destinations"][DEST]["camera_group_time_decisions"][PHONE]
    assert cell["effective_time_anchor"]["source"] == "recorded_offset_unconfirmed" and not art["requires_user_input"]
    (tmp_path / "ws" / ".photos-ingest" / "photos-21-time-decisions.json").write_text(json.dumps(art))
    drift, _b = wf.build_drift_validation(files, art, cal.compute_resolved_utc(files, GROUPS, art), gpx, None)
    frames = drift["destinations"][DEST]["drift_decisions"][PHONE]["proposal"]["frames"]
    assert [f["source_file"] for f in frames] == [f"{DEST}/b.heic"]


@pytest.mark.spec("RUL-untagged_phone_photo_settled_by_evidence", "BLD-phone_offset_cell",
                  test="TST-geotag_untagged_photos-settled_by_its_own_gps")
def test_the_phones_own_gps_settles_its_untagged_photos(tmp_path):
    """One untagged photo with its own position lies on the track where the zone reads it: that settles the day's
    untagged photos — the anchored offset applies itself to them, unasked."""
    files = [_photo("a.heic", "2024:07:03 10:00:00", pos=(51.0, 3.2)), _photo("b.heic", "2024:07:03 11:00:00")]
    gpx = _gpx([cal.GPXPoint(51.0, 3.2, datetime(2024, 7, 3, 8, 0, 30, tzinfo=timezone.utc), "t.gpx", 0),
                cal.GPXPoint(51.1, 3.2, datetime(2024, 7, 3, 8, 30, tzinfo=timezone.utc), "t.gpx", 1)])
    art = _build(_wf(tmp_path), files, gpx)
    cell = art["destinations"][DEST]["camera_group_time_decisions"][PHONE]
    assert cell["phone"]["applies_to"] == "untagged_photos"
    assert cell["effective_time_anchor"] == {"offset_seconds": -7170, "source": "gpx_anchor_auto"}
    assert _rows(files, art)[f"{DEST}/b.heic"]["resolved_utc"] == "2024-07-03T09:00:30Z"


NAMELESS = [_photo("shot1.png", "2024:07:03 10:00:00", key=NOBODY), _photo("shot2.png", "2024:07:03 11:00:00", key=NOBODY),
            _photo("tagged.png", "2024:07:03 12:00:00", "+02:00", key=NOBODY)]


@pytest.mark.spec("RUL-camera_less_files_asked_per_destination", "RUL-unidentified_files_solved_alone",
                  "BLD-unidentified_files_question", test="TST-geotag_untagged_photos-camera_less_files_one_question")
def test_files_naming_no_camera_are_one_question_for_the_destination(tmp_path):
    wf = _wf(tmp_path)
    art = _build(wf, NAMELESS)
    q = art["destinations"][DEST]["unidentified_files"]
    assert q == {"files": 2, "examples": [f"{DEST}/shot1.png", f"{DEST}/shot2.png"],
                 "proposed_iana_timezone": "Europe/Brussels",
                 "user_decision": {"accept_proposal": False, "accepted_timezone": ""},
                 "effective_iana_timezone": "", "requires_user_input": True, "stale_user_decision": False}
    assert art["requires_user_input"]
    rows = _rows(NAMELESS, art)
    assert rows[f"{DEST}/shot1.png"]["time_rule_used"] == "local_time_unconfirmed"
    assert rows[f"{DEST}/tagged.png"]["time_rule_used"] == "unidentified_native_offset"   # its own offset needs no word
    yes = _with(ZONE, unidentified_files={"user_decision": {"accept_proposal": True, "accepted_timezone": "Europe/Brussels"}})
    art = _build(wf, NAMELESS, prior=yes)
    assert art["destinations"][DEST]["unidentified_files"]["effective_iana_timezone"] == "Europe/Brussels"
    assert not art["requires_user_input"]
    assert _rows(NAMELESS, art)[f"{DEST}/shot1.png"]["resolved_utc"] == "2024-07-03T08:00:00Z"


@pytest.mark.spec("RUL-camera_less_answer_kept", "BLD-unidentified_files_question",
                  test="TST-geotag_untagged_photos-camera_less_answer_kept")
def test_the_answer_holds_for_later_files_while_the_zone_is_the_one_answered(tmp_path):
    wf = _wf(tmp_path)
    yes = _with(ZONE, unidentified_files={"user_decision": {"accept_proposal": True, "accepted_timezone": "Europe/Brussels"}})
    later = NAMELESS + [_photo("shot3.png", "2024:07:04 09:00:00", key=NOBODY)]
    q = _build(wf, later, prior=yes)["destinations"][DEST]["unidentified_files"]
    assert q["files"] == 3 and q["effective_iana_timezone"] == "Europe/Brussels"
    elsewhere = json.loads(json.dumps(yes))
    elsewhere["destinations"][DEST]["destination_timezone"]["user_decision"]["manual_iana_timezone"] = "Europe/Paris"
    q = _build(wf, later, prior=elsewhere)["destinations"][DEST]["unidentified_files"]
    assert q["stale_user_decision"] and q["requires_user_input"] and q["user_decision"]["accepted_timezone"] == "Europe/Brussels"
    bad = _with(ZONE, unidentified_files={"user_decision": {"accept_proposal": True, "accepted_timezone": ""}})
    _art, blockers = wf.build_time_decisions(NAMELESS, GROUPS, bad, _gpx())
    assert any("accepted_timezone must be the timezone accepted" in b for b in blockers)


@pytest.mark.spec("RUL-checked_timezones", "BLD-unidentified_files_question",
                  test="TST-geotag_untagged_photos-the_timezone_accepted_is_checked")
def test_the_timezone_accepted_for_files_naming_no_camera_is_checked(tmp_path):
    """The timezone written as the one accepted is checked like every timezone the user writes: one that is none of
    the zone database's is a blocker naming where it is, not an answer for another zone."""
    bad = _with(ZONE, unidentified_files={"user_decision": {"accept_proposal": True, "accepted_timezone": "Mars/Olympus"}})
    _art, blockers = _wf(tmp_path).build_time_decisions(NAMELESS, GROUPS, bad, _gpx())
    assert any(f"{DEST}: unidentified_files.user_decision.accepted_timezone 'Mars/Olympus'" in b for b in blockers), blockers
