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

"""Phase 3c (geotag) — RUL-offset_from_own_evidence: clock offsets do NOT inherit across destinations.

Each (camera group, destination[, date]) bucket proposes its own offset from GPX self-anchor →
timezone-derived → manual. A child with no self-anchor does NOT adopt an ancestor's resolved offset
(unlike the timezone, which still inherits — see test_geotag_time_decisions.py). Self-anchors
never leak between destinations. From conftest.py.
"""
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
BYDEST = "6-photos-by-dest"


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {p.source_file: "f" * 64 for p in points}
    return idx


def _pt(lat, lon, t):
    return cal.GPXPoint(lat, lon, datetime(2024, 7, 3, t, 0, 0, tzinfo=timezone.utc), "t.gpx", 0)


def _file(rel, dest, *, gps=None, naive="2024:07:03 14:00:00", key=CAM):
    return {"relative_path": rel, "destination": dest, "camera_group_key": key,
            "native_gps": ({"lat": gps[0], "lon": gps[1]} if gps else None),
            "has_native_gps": bool(gps), "has_timestamp": True, "source_naive_time": naive}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _build(wf, files, gpx, prior=None, *, multi=True):
    utils.CONFIG["camera_time_and_timezone_policy"]["multi_anchor_auto_apply"] = multi
    art, blockers = wf.build_time_decisions(files, {CAM: {"camera_group_class": "camera"}}, prior, gpx)
    return art, blockers


def _cell(art, dest):
    return art["destinations"][dest]["camera_group_time_decisions"][CAM]


# A GPX track + two parent frames whose consistent offset (-7200) auto-resolves the parent cell.
TRACK = [_pt(50.0, 4.0, 12), _pt(51.0, 5.0, 13)]
PARENT_FRAMES = [_file(f"{BYDEST}/Trip/a.arw", f"{BYDEST}/Trip", gps=(50.0, 4.0), naive="2024:07:03 14:00:00"),
                 _file(f"{BYDEST}/Trip/b.arw", f"{BYDEST}/Trip", gps=(51.0, 5.0), naive="2024:07:03 15:00:00")]


def test_no_method_named_nearest_ancestor_offset():
    # The offset-inheritance helper was removed with RUL-offset_from_own_evidence; only the timezone still inherits.
    assert not hasattr(cal.GeotagWorkflow, "_nearest_ancestor_offset")


@pytest.mark.spec("RUL-offset_from_own_evidence", test="TST-geotag_offset_no_inheritance-child_does_not_inherit_resolved_parent_offset")
def test_child_does_not_inherit_resolved_parent_offset(tmp_path):
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Trip/Sub/c.arw", f"{BYDEST}/Trip/Sub",
                                   naive="2024:07:04 14:00:00")]              # another day; no GPS, no tz
    art, _ = _build(wf, files, _gpx(TRACK))
    parent = _cell(art, f"{BYDEST}/Trip")
    assert parent["decision_mode"] == "auto_resolved" and parent["effective_time_anchor"]["offset_seconds"] == -7200
    child = _cell(art, f"{BYDEST}/Trip/Sub")
    assert child["proposal"] == {"proposal_source": "manual_required"}    # another day's -7200 does NOT flow down
    assert child["requires_user_input"] is True


@pytest.mark.spec("RUL-offset_shared_within_day", "BLD-offset_shared_within_day",
                  "RUL-anchor_offset_auto_as_configured", "RUL-shared_offset_auto_only_as_there",
                  test="TST-geotag_offset_no_inheritance-the_day_s_offset_is_the_camera_s_wherever_sorted")
def test_the_day_s_offset_is_the_camera_s_wherever_its_photos_were_sorted(tmp_path):
    """Museum in the morning, castle in the afternoon, one camera, one day. The museum's photos have GPS and
    fix the clock; the castle's have none. The castle is not asked to guess from the timezone: it takes the
    offset the camera's own GPS gave that day — by itself where that applied itself, else for the user to
    accept — and says where it came from."""
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Castle/c.arw", f"{BYDEST}/Castle", naive="2024:07:03 17:00:00")]
    art, _ = _build(wf, files, _gpx(TRACK))
    castle = _cell(art, f"{BYDEST}/Castle")
    assert castle["proposal"]["proposal_source"] == "same_day_elsewhere"
    assert castle["proposal"]["shared_from"] == {"destination": f"{BYDEST}/Trip", "bucket": CAM}
    assert castle["effective_time_anchor"] == {"offset_seconds": -7200, "source": "same_day_auto"}
    assert castle["decision_mode"] == "auto_resolved" and not castle["requires_user_input"]
    assert "same_day_auto" not in cal.GeotagWorkflow._DRIFT_TRIGGER_SOURCES     # the camera's own GPS stands behind it
    # where the museum's offset did not apply itself, the castle's is offered, not applied
    art, _ = _build(wf, files, _gpx(TRACK), multi=False)
    castle = _cell(art, f"{BYDEST}/Castle")
    assert castle["proposal"] == {"proposal_source": "manual_required"} and castle["requires_user_input"]
    accepted = {"destinations": {f"{BYDEST}/Trip": {"camera_group_time_decisions": {CAM: {"user_decision": {
        "accept_proposal": True, "accepted_offset_seconds": -7200}}}}}}
    art, _ = _build(wf, files, _gpx(TRACK), accepted, multi=False)
    castle = _cell(art, f"{BYDEST}/Castle")
    assert castle["proposal"]["proposed_offset_seconds"] == -7200 and castle["proposal"]["confidence"] == "review_required"
    assert castle["effective_time_anchor"] == "" and castle["requires_user_input"]
    accepted["destinations"][f"{BYDEST}/Castle"] = {"camera_group_time_decisions": {CAM: {"user_decision": {
        "accept_proposal": True, "accepted_offset_seconds": -7200}}}}
    art, _ = _build(wf, files, _gpx(TRACK), accepted, multi=False)
    assert _cell(art, f"{BYDEST}/Castle")["effective_time_anchor"] == {"offset_seconds": -7200, "source": "same_day_accepted"}


@pytest.mark.spec("RUL-offset_shared_within_day", "BLD-offset_shared_within_day", "RUL-chosen_group_is_anchored",
                  test="TST-geotag_offset_no_inheritance-a_group_the_user_chose_is_shared_within_the_day")
def test_a_group_the_user_chose_is_shared_within_the_day(tmp_path):
    """An offset the user picked from the camera's own GPS groups rests on the camera's own positions: the castle,
    with none of its own, is offered it like any offset the camera's GPS gave that day — for the user to accept, the
    pick not having applied itself. An offset no group supports is the user's alone, and is passed nowhere."""
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Castle/c.arw", f"{BYDEST}/Castle", naive="2024:07:03 17:00:00")]
    def picked(offset):
        prior = {"destinations": {f"{BYDEST}/Trip": {"camera_group_time_decisions": {CAM: {"user_decision": {
            "manual_offset_seconds": offset}}}}}}
        art, _ = _build(wf, files, _gpx(TRACK), prior, multi=False)
        return _cell(art, f"{BYDEST}/Trip"), _cell(art, f"{BYDEST}/Castle")
    trip, castle = picked(-7200)
    assert trip["effective_time_anchor"] == {"offset_seconds": -7200, "source": "gpx_anchor_chosen"}
    assert castle["proposal"]["proposal_source"] == "same_day_elsewhere"
    assert castle["proposal"]["proposed_offset_seconds"] == -7200
    assert castle["proposal"]["shared_from"] == {"destination": f"{BYDEST}/Trip", "bucket": CAM}
    assert castle["effective_time_anchor"] == "" and castle["requires_user_input"]
    trip, castle = picked(-3600)                                                 # no group of the camera's says so
    assert trip["effective_time_anchor"] == {"offset_seconds": -3600, "source": "manual"}
    assert castle["proposal"]["proposal_source"] != "same_day_elsewhere"


@pytest.mark.spec("RUL-same_day_offsets_agree", "BLD-offset_shared_within_day",
                  test="TST-geotag_offset_no_inheritance-one_clock_read_two_ways_takes_no_effect")
def test_one_clock_read_two_ways_on_one_day_takes_no_effect(tmp_path):
    """The camera's GPS fixes its clock at −2 h in one destination and −1 h 50 min in another, the same day:
    one of the two is wrong, and neither is applied until the user says — a hand-written offset being their word."""
    wf = _wf(tmp_path)
    other = [_file(f"{BYDEST}/Other/x.arw", f"{BYDEST}/Other", gps=(50.0, 4.0), naive="2024:07:03 13:50:00"),
             _file(f"{BYDEST}/Other/y.arw", f"{BYDEST}/Other", gps=(51.0, 5.0), naive="2024:07:03 14:50:00")]
    nogps = [_file(f"{BYDEST}/Third/z.arw", f"{BYDEST}/Third", naive="2024:07:03 18:00:00")]
    art, _ = _build(wf, PARENT_FRAMES + other + nogps, _gpx(TRACK))
    a, b = _cell(art, f"{BYDEST}/Trip"), _cell(art, f"{BYDEST}/Other")
    assert a["effective_time_anchor"] == "" and b["effective_time_anchor"] == ""
    assert a["requires_user_input"] and b["requires_user_input"] and art["requires_user_input"]
    assert a["conflicts_with"] == [{"destination": f"{BYDEST}/Other", "bucket": CAM, "offset_seconds": -6600}]
    assert b["conflicts_with"] == [{"destination": f"{BYDEST}/Trip", "bucket": CAM, "offset_seconds": -7200}]
    assert _cell(art, f"{BYDEST}/Third")["proposal"] == {"proposal_source": "manual_required"}   # nothing passed on
    # the user writes which it is, in the one that was wrong: the other stands, and is passed on
    said = {"destinations": {f"{BYDEST}/Other": {"camera_group_time_decisions": {CAM: {"user_decision": {
        "manual_offset_seconds": -7200}}}}}}
    art, _ = _build(wf, PARENT_FRAMES + other + nogps, _gpx(TRACK), said)
    assert _cell(art, f"{BYDEST}/Trip")["effective_time_anchor"] == {"offset_seconds": -7200, "source": "gpx_anchor_auto"}
    assert "conflicts_with" not in _cell(art, f"{BYDEST}/Trip")
    assert _cell(art, f"{BYDEST}/Third")["effective_time_anchor"] == {"offset_seconds": -7200, "source": "same_day_auto"}
    # within the setting's reach the two are one finding
    utils.CONFIG["clock_offset_same_day_max_difference_seconds"] = 900.0
    art, _ = _build(wf, PARENT_FRAMES + other, _gpx(TRACK))
    assert _cell(art, f"{BYDEST}/Trip")["effective_time_anchor"] and _cell(art, f"{BYDEST}/Other")["effective_time_anchor"]


def test_no_ancestor_is_manual_required(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{BYDEST}/Alone/x.arw", f"{BYDEST}/Alone")]              # no GPS, no ancestor, no tz
    art, _ = _build(wf, files, _gpx(TRACK))
    assert _cell(art, f"{BYDEST}/Alone")["proposal"] == {"proposal_source": "manual_required"}


@pytest.mark.spec("RUL-offset_from_own_evidence", test="TST-geotag_offset_no_inheritance-sibling_offset_does_not_leak")
def test_sibling_offset_does_not_leak(tmp_path):
    wf = _wf(tmp_path)
    # Trip/A self-anchors; Trip/B (sibling, no GPS, another day) must NOT adopt A — a day's offset is that day's.
    files = [_file(f"{BYDEST}/Trip/A/a.arw", f"{BYDEST}/Trip/A", gps=(50.0, 4.0)),
             _file(f"{BYDEST}/Trip/A/b.arw", f"{BYDEST}/Trip/A", gps=(51.0, 5.0), naive="2024:07:03 15:00:00"),
             _file(f"{BYDEST}/Trip/B/c.arw", f"{BYDEST}/Trip/B", naive="2024:07:04 15:00:00")]
    art, _ = _build(wf, files, _gpx(TRACK))
    assert _cell(art, f"{BYDEST}/Trip/A")["decision_mode"] == "auto_resolved"
    assert _cell(art, f"{BYDEST}/Trip/B")["proposal"] == {"proposal_source": "manual_required"}


def test_manual_parent_offset_does_not_reroot_children(tmp_path):
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Trip/Sub/c.arw", f"{BYDEST}/Trip/Sub"),
                             _file(f"{BYDEST}/Trip/Sub/Deep/d.arw", f"{BYDEST}/Trip/Sub/Deep")]
    # Sub is given a manual offset; Deep takes the offset the camera's own GPS gave that day (Trip's), never
    # Sub's hand-written -100: only GPS evidence is passed on.
    prior = {"destinations": {f"{BYDEST}/Trip/Sub": {"camera_group_time_decisions":
             {CAM: {"user_decision": {"manual_offset_seconds": -100}}}}}}
    art, _ = _build(wf, files, _gpx(TRACK), prior)
    assert _cell(art, f"{BYDEST}/Trip/Sub")["effective_time_anchor"] == {"offset_seconds": -100, "source": "manual"}
    assert _cell(art, f"{BYDEST}/Trip/Sub/Deep")["effective_time_anchor"] == {"offset_seconds": -7200,
                                                                              "source": "same_day_auto"}


def test_determinism_rerun_byte_identical(tmp_path):
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Trip/Sub/c.arw", f"{BYDEST}/Trip/Sub")]
    import json
    a1, _ = _build(wf, files, _gpx(TRACK))
    a2, _ = _build(wf, files, _gpx(TRACK), a1)
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)


# --- an inherited timezone and the destination's own photos (RUL-inherited_timezone_yields_to_photos) -----------------

PHONE = "APPLE|iPhone|p1"
BOTH = {CAM: {"camera_group_class": "camera"}, PHONE: {"camera_group_class": "smartphone"}}


def _phone(rel, dest, naive, offset):
    return {"relative_path": rel, "destination": dest, "camera_group_key": PHONE, "native_gps": None,
            "has_native_gps": False, "has_timestamp": True, "source_naive_time": naive,
            "source_time_tag": "EXIF:DateTimeOriginal", "raw_times": {"OffsetTimeOriginal": offset}}


def _zones(wf, files, prior=None):
    art, blk = wf.build_time_decisions(files, BOTH, prior, _gpx([]))
    assert not blk, blk
    return {d: v["destination_timezone"] for d, v in art["destinations"].items()}, art


@pytest.mark.spec("RUL-inherited_timezone_yields_to_photos", "BLD-timezone_cell", "RUL-inherited_zone_stops_within",
                  test="TST-geotag_offset_no_inheritance-an_inherited_zone_yields_to_the_destination_s_photos")
def test_an_inherited_timezone_yields_to_the_destination_s_own_photos(tmp_path):
    """Lisbon, Porto, Madrid under one folder answered Europe/Lisbon. A phone's photo in Madrid records
    +02:00, which Lisbon never has in July: Madrid does not take Lisbon's zone unasked — and nor does what
    lies inside Madrid. One photo is enough. The user writes the zone."""
    wf = _wf(tmp_path)
    root = f"{BYDEST}/Iberia"
    files = [_phone(f"{root}/Lisbon/a.jpg", f"{root}/Lisbon", "2024:07:03 10:00:00", "+01:00"),
             _phone(f"{root}/Porto/b.jpg", f"{root}/Porto", "2024:07:04 10:00:00", "+01:00"),
             _phone(f"{root}/Madrid/c.jpg", f"{root}/Madrid", "2024:07:05 10:00:00", "+02:00"),
             _phone(f"{root}/Madrid/d.jpg", f"{root}/Madrid", "2024:07:05 11:00:00", "+02:00"),
             _file(f"{root}/Madrid/Prado/e.arw", f"{root}/Madrid/Prado", naive="2024:07:05 12:00:00")]
    answered = {"destinations": {root: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Lisbon"}}}}}
    tz, art = _zones(wf, files, answered)
    assert tz[f"{root}/Lisbon"]["effective_iana_timezone"] == tz[f"{root}/Porto"]["effective_iana_timezone"] == "Europe/Lisbon"
    madrid = tz[f"{root}/Madrid"]
    assert madrid["effective_iana_timezone"] == "" and madrid["requires_user_input"] and "decision_mode" not in madrid
    assert madrid["proposed_iana_timezone"] == "Europe/Lisbon"
    assert madrid["contradicted_by"] == {"photos": 2, "example": f"{root}/Madrid/c.jpg", "recorded_offset_seconds": 7200,
                                         "recorded_offsets": [7200],
                                         "timezone": "Europe/Lisbon", "timezone_offset_seconds": 3600}
    prado = tz[f"{root}/Madrid/Prado"]                 # inside Madrid: it does not reach past Madrid to Lisbon
    assert prado["effective_iana_timezone"] == "" and prado["requires_user_input"] and prado["proposal_source"] == "none"
    assert art["requires_user_input"]
    # the user answers Madrid: it and what lies in it follow
    answered["destinations"][f"{root}/Madrid"] = {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Madrid"}}}
    tz, _ = _zones(wf, files, answered)
    assert tz[f"{root}/Madrid"]["effective_iana_timezone"] == "Europe/Madrid" and "contradicted_by" not in tz[f"{root}/Madrid"]
    assert tz[f"{root}/Madrid/Prado"]["effective_iana_timezone"] == "Europe/Madrid"


@pytest.mark.spec("RUL-destination_has_one_timezone", "RUL-zone_against_photos_needs_word", "BLD-timezone_cell",
                  test="TST-geotag_offset_no_inheritance-a_destination_has_one_timezone")
def test_a_destination_has_one_timezone_for_all_its_photos(tmp_path):
    """A zone the user writes is set against the destination's photos like one inherited. Photos that record
    another offset stop it: the user picks their zone, moves them to a folder of their own, or keeps the zone
    by an explicit word that names the offsets it is given for — a photo with yet another offset asks again."""
    wf = _wf(tmp_path)
    dest = f"{BYDEST}/Roadtrip"
    files = [_phone(f"{dest}/a.jpg", dest, "2024:07:03 10:00:00", "+01:00"),
             _phone(f"{dest}/b.jpg", dest, "2024:07:05 10:00:00", "+02:00")]         # no one zone fits both
    def zone(tz_name, despite=None):
        ud = {"manual_iana_timezone": tz_name, **({"confirmed_despite_recorded_offsets": despite} if despite is not None else {})}
        art, blk = wf.build_time_decisions(files, BOTH, {"destinations": {dest: {"destination_timezone": {"user_decision": ud}}}}, _gpx([]))
        return (art["destinations"][dest]["destination_timezone"] if art else None), blk
    for name, off in (("Europe/Lisbon", 7200), ("Europe/Madrid", 3600)):             # whichever is written, one photo speaks against it
        cell, blk = zone(name)
        assert cell["effective_iana_timezone"] == "" and cell["requires_user_input"] and not blk
        assert cell["contradicted_by"]["recorded_offsets"] == [off] and cell["user_decision"]["manual_iana_timezone"] == name
    cell, _ = zone("Europe/Lisbon", [7200])                                          # the user's word, for that offset
    assert cell["effective_iana_timezone"] == "Europe/Lisbon" and not cell["requires_user_input"]
    assert cell["contradicted_by"]["confirmed"] is True and not cell["stale_user_decision"]   # ...and the record says so
    files.append(_phone(f"{dest}/c.jpg", dest, "2024:07:06 10:00:00", "+09:00"))     # a photo with yet another offset
    cell, _ = zone("Europe/Lisbon", [7200])
    assert cell["effective_iana_timezone"] == "" and cell["requires_user_input"] and cell["stale_user_decision"]
    assert cell["contradicted_by"]["recorded_offsets"] == [7200, 32400] and "confirmed" not in cell["contradicted_by"]
    assert cell["user_decision"]["confirmed_despite_recorded_offsets"] == [7200]     # kept as written
    _cell_, blk = zone("Europe/Lisbon", "yes")                                       # not a list of offsets
    assert blk and "confirmed_despite_recorded_offsets" in blk[0]


@pytest.mark.spec("BLD-timezone_cell", "RUL-zone_against_photos_needs_word",
                  test="TST-geotag_offset_no_inheritance-a_null_word_for_the_zone_is_no_answer")
def test_a_null_word_for_the_zone_is_no_answer(tmp_path):
    """`confirmed_despite_recorded_offsets: null` reads as no answer, as `null` does in every other field: the zone
    the photos speak against still asks, and nothing blocks."""
    wf = _wf(tmp_path)
    dest = f"{BYDEST}/Roadtrip"
    files = [_phone(f"{dest}/a.jpg", dest, "2024:07:03 10:00:00", "+01:00"),
             _phone(f"{dest}/b.jpg", dest, "2024:07:05 10:00:00", "+02:00")]
    ud = {"manual_iana_timezone": "Europe/Lisbon", "confirmed_despite_recorded_offsets": None}
    art, blk = wf.build_time_decisions(files, BOTH, {"destinations": {dest: {"destination_timezone": {"user_decision": ud}}}}, _gpx([]))
    assert not blk
    cell = art["destinations"][dest]["destination_timezone"]
    assert cell["effective_iana_timezone"] == "" and cell["requires_user_input"] and not cell["stale_user_decision"]
    assert cell["user_decision"]["confirmed_despite_recorded_offsets"] == []


@pytest.mark.spec("RUL-inherited_timezone_yields_to_photos",
                  test="TST-geotag_offset_no_inheritance-a_camera_s_offset_tag_says_nothing_of_the_place")
def test_what_does_not_speak_against_an_inherited_zone(tmp_path):
    """A camera's offset tag says what its clock was set to, not where it was — a camera left on home time
    would stop every destination abroad. A phone's that agrees, or a photo with no offset, says nothing against."""
    wf = _wf(tmp_path)
    root = f"{BYDEST}/Japan"
    cam = dict(_file(f"{root}/Kyoto/a.arw", f"{root}/Kyoto", naive="2024:07:03 10:00:00"),
               source_time_tag="EXIF:DateTimeOriginal", raw_times={"OffsetTimeOriginal": "+02:00"})
    files = [cam, _phone(f"{root}/Kyoto/b.jpg", f"{root}/Kyoto", "2024:07:03 18:00:00", "+09:00"),
             dict(_phone(f"{root}/Kyoto/c.jpg", f"{root}/Kyoto", "2024:07:03 18:00:00", "+09:00"), raw_times={})]
    answered = {"destinations": {root: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}}}
    kyoto = _zones(wf, files, answered)[0][f"{root}/Kyoto"]
    assert kyoto["effective_iana_timezone"] == "Asia/Tokyo" and kyoto["decision_mode"] == "auto_resolved"
    assert "contradicted_by" not in kyoto


# --- a timezone's guess is asked about once (RUL-timezone_offset_asked_once) ------------------------------------------

@pytest.mark.spec("RUL-timezone_offset_asked_once", "BLD-timezone_naive_offset",
                  test="TST-geotag_offset_no_inheritance-a_timezone_s_guess_is_asked_about_once")
def test_a_timezone_s_guess_is_asked_about_once_where_it_can_be_checked(tmp_path):
    """A camera with no GPS, in a destination whose zone is known. With tracks by its photos the timezone's
    guess goes to the check against the tracks as it stands — one question, the confirmation — and nothing
    is resolved for planning until it is answered. With no track to check it against, it is accepted here."""
    wf = _wf(tmp_path)
    dest = f"{BYDEST}/Brussels"
    files = [_file(f"{dest}/a.arw", dest, naive="2024:07:03 14:00:00")]
    zone = {"destinations": {dest: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Brussels"}}}}}
    art, _ = _build(wf, files, _gpx(TRACK), zone)                     # tracks at 12:00–13:00 UTC: by the photo
    cell = _cell(art, dest)
    assert cell["proposal"]["proposal_source"] == "timezone_naive"
    assert cell["effective_time_anchor"] == {"offset_seconds": -7200, "source": "timezone_unconfirmed"}
    assert cell["decision_mode"] == "to_be_confirmed_against_tracks" and not cell["requires_user_input"]
    assert not art["requires_user_input"]                              # photos-21 asks nothing...
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    rows0 = cal.compute_resolved_utc(files, {CAM: {"camera_group_class": "camera"}}, art)
    drift, blk = wf.build_drift_validation(files, art, rows0, _gpx(TRACK), None)
    asked = drift["destinations"][dest]["drift_decisions"][CAM]
    assert not blk and drift["requires_user_input"] and asked["requires_user_input"]   # ...photos-22 does
    assert asked["proposal"]["current_offset_seconds"] == -7200 and asked["effective_drift_offset"] == ""
    # an offset nobody accepted is never passed over, even were the tracks gone between the two steps
    drift, _ = wf.build_drift_validation(files, art, rows0, _gpx([]), None)
    assert drift["destinations"][dest]["drift_decisions"][CAM]["requires_user_input"]
    # no track by the photos: nothing to check it against, so it is accepted here, as before
    art, _ = _build(wf, files, _gpx([]), zone)
    cell = _cell(art, dest)
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"] and art["requires_user_input"]


@pytest.mark.spec("RUL-track_confirmation_is_acceptance",
                  test="TST-geotag_offset_no_inheritance-a_confirmation_against_the_tracks_is_the_acceptance")
def test_a_confirmation_against_the_tracks_is_the_acceptance(tmp_path):
    """The timezone's guess, never accepted in photos-21, is confirmed at the check against the tracks: that
    confirmation is its acceptance. Nothing asks any more — neither file — and the photo resolves under it."""
    wf = _wf(tmp_path)
    dest = f"{BYDEST}/Brussels"
    files = [_file(f"{dest}/a.arw", dest, naive="2024:07:03 14:00:00")]
    groups = {CAM: {"camera_group_class": "camera"}}
    zone = {"destinations": {dest: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Brussels"}}}}}
    art, _ = _build(wf, files, _gpx(TRACK), zone)
    assert _cell(art, dest)["effective_time_anchor"]["source"] == "timezone_unconfirmed"
    assert "accept_proposal" not in {k for k, v in _cell(art, dest)["user_decision"].items() if v}
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), art)
    rows0 = cal.compute_resolved_utc(files, groups, art)
    asked, _ = wf.build_drift_validation(files, art, rows0, _gpx(TRACK), None)
    assert asked["requires_user_input"]
    asked["destinations"][dest]["drift_decisions"][CAM]["user_decision"] = {
        "confirmed": True, "corrected_offset_seconds": "", "confirmed_offset_seconds": -7200,
        "confirmed_against_tracks": [{"gpx_file": "t.gpx", "sha256": "f" * 64}]}
    drift, blk = wf.build_drift_validation(files, art, rows0, _gpx(TRACK), asked)
    cell = drift["destinations"][dest]["drift_decisions"][CAM]
    assert not blk and not drift["requires_user_input"] and drift["status"] == "complete"
    assert not cell["requires_user_input"] and not cell["stale_user_decision"]
    assert cell["effective_drift_offset"] == {"offset_seconds": -7200, "source": "gps_drift_validated"}
    # photos-21, built again with the confirmation in place, still asks for no acceptance of its own
    again, blk = _build(wf, files, _gpx(TRACK), art)
    assert not blk and not again["requires_user_input"] and not _cell(again, dest)["requires_user_input"]
    (row,) = cal.compute_resolved_utc(files, groups, again, cal.drift_offset_overrides(drift))
    assert row["resolved_utc_status"] == "valid" and row["resolved_utc"] == "2024-07-03T12:00:00Z"


# --- a country, chosen once at the top of its tree (RUL-country_chosen_once) ---------------------------------------

def _country(code):
    return {"destination_timezone": {"user_decision": {"country": code}}}


def _tz(zone):
    return {"destination_timezone": {"user_decision": {"manual_iana_timezone": zone}}}


@pytest.mark.parametrize("written", ["ZZ", ["JP"], {"code": "JP"}, 81])
@pytest.mark.spec("BLD-country_choice", test="TST-geotag_offset_no_inheritance-a_country_that_is_none_is_named")
def test_a_country_that_is_none_is_named_not_crashed_on(tmp_path, written):
    """Whatever the user wrote for a destination's country — a code no country has, or a value that is no code at
    all — is named as a blocker at that destination; nothing is taken from it."""
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Japonia"
    art, blk = wf.build_time_decisions([_file(f"{d}/a.arw", d)], BOTH, {"destinations": {d: _country(written)}},
                                       _gpx([]))
    assert len(blk) == 1 and d in blk[0] and "user_decision.country" in blk[0], blk
    cell = art["destinations"][d]["destination_timezone"]
    assert cell.get("country", "") == "" and cell["effective_iana_timezone"] == ""


@pytest.mark.spec("RUL-country_gives_its_timezone", "BLD-country_choice", "RUL-country_of_several_gives_none",
                  "RUL-zone_among_countrys_only",
                  test="TST-geotag_offset_no_inheritance-a_country_gives_its_timezone_or_none")
def test_a_country_of_one_timezone_gives_it_and_one_of_several_gives_none(tmp_path):
    """The user says which country a folder is, whatever it is called. A country of one timezone gives that
    zone to everything inside. One of several gives none: each destination inside answers for itself, among
    that country's zones only — and nothing reaches past it to a zone given above."""
    table = utils.country_table()
    assert table["JP"]["zones"] == ["Asia/Tokyo"] and len(table["US"]["zones"]) > 5 and table["US"]["name"] == "United States"
    wf = _wf(tmp_path)
    y = f"{BYDEST}/2024"
    files = [_file(f"{y}/Japonia/Kyoto/a.arw", f"{y}/Japonia/Kyoto"),
             _file(f"{y}/SUA/Arizona/Canyon/b.arw", f"{y}/SUA/Arizona/Canyon"),
             _file(f"{y}/SUA/Oregon/c.arw", f"{y}/SUA/Oregon")]
    prior = {"destinations": {y: _tz("Europe/Bucharest"),                # the year, given the home zone
                              f"{y}/Japonia": _country("JP"), f"{y}/SUA": _country("US")}}
    art, blk = wf.build_time_decisions(files, BOTH, prior, _gpx([]))
    assert not blk, blk
    tz = {d: v["destination_timezone"] for d, v in art["destinations"].items()}
    kyoto = tz[f"{y}/Japonia/Kyoto"]
    assert kyoto["effective_iana_timezone"] == "Asia/Tokyo" and kyoto["proposal_source"] == "country"
    assert (kyoto["country"], kyoto["country_from"], kyoto["country_zones"]) == ("JP", f"{y}/Japonia", ["Asia/Tokyo"])
    assert kyoto["decision_mode"] == "auto_resolved" and not kyoto["requires_user_input"]
    assert tz[f"{y}/Japonia"]["effective_iana_timezone"] == "Asia/Tokyo" and "country_from" not in tz[f"{y}/Japonia"]
    sua = tz[f"{y}/SUA"]                                                  # several zones: none of its own, none given down
    assert sua["effective_iana_timezone"] == "" and not sua["requires_user_input"]       # a container never waits
    for d in (f"{y}/SUA/Arizona/Canyon", f"{y}/SUA/Oregon"):
        assert tz[d]["effective_iana_timezone"] == "" and tz[d]["requires_user_input"]   # not Bucharest, from above
        assert tz[d]["proposal_source"] == "none" and tz[d]["country"] == "US" and tz[d]["country_from"] == f"{y}/SUA"
        assert "America/Phoenix" in tz[d]["country_zones"]
    assert art["countries"]["US"]["zones"] == table["US"]["zones"]       # what the choice was made from, recorded
    # a zone answered inside the country passes down as ever
    prior["destinations"][f"{y}/SUA/Arizona"] = _tz("America/Phoenix")
    prior["destinations"][f"{y}/SUA/Oregon"] = _tz("America/Los_Angeles")
    art, blk = wf.build_time_decisions(files, BOTH, prior, _gpx([]))
    assert not blk and art["destinations"][f"{y}/SUA/Arizona/Canyon"]["destination_timezone"]["effective_iana_timezone"] == "America/Phoenix"
    # ...and one that is not the country's is refused
    prior["destinations"][f"{y}/SUA/Oregon"] = _tz("Europe/Paris")
    _art, blk = wf.build_time_decisions(files, BOTH, prior, _gpx([]))
    assert len(blk) == 1 and "Europe/Paris" in blk[0] and "not a timezone of US" in blk[0] and f"{y}/SUA" in blk[0]
    # a code that is no country's is refused
    prior["destinations"][f"{y}/SUA/Oregon"] = _tz("America/Los_Angeles")
    prior["destinations"][f"{y}/Japonia"] = _country("Japan")
    _art, blk = wf.build_time_decisions(files, BOTH, prior, _gpx([]))
    assert len(blk) == 1 and "country 'Japan'" in blk[0]


@pytest.mark.spec("RUL-country_chosen_once", "BLD-country_choice", "RUL-country_removal_told",
                  test="TST-geotag_offset_no_inheritance-nothing_inside_a_country_chooses_a_country")
def test_nothing_inside_a_country_chooses_a_country(tmp_path, monkeypatch, capsys):
    """A country is chosen once, at the top of its tree. One chosen inside another is taken out of the
    decision — whichever was written first — and the run says so, and why."""
    wf = _wf(tmp_path)
    root = f"{BYDEST}/SUA"
    files = [_file(f"{root}/Hawaii/Maui/a.arw", f"{root}/Hawaii/Maui")]
    prior = {"destinations": {root: _country("US"), f"{root}/Hawaii": _country("JP"), f"{root}/Hawaii/Maui": _country("US")}}
    art, blk = wf.build_time_decisions(files, BOTH, prior, _gpx([]))
    assert not blk
    hawaii, maui = (art["destinations"][d]["destination_timezone"] for d in (f"{root}/Hawaii", f"{root}/Hawaii/Maui"))
    assert hawaii["user_decision"]["country"] == "" and maui["user_decision"]["country"] == ""     # taken out
    assert hawaii["country"] == "US" and hawaii["country_from"] == root
    assert hawaii["country_removed"] == {"country": "JP", "because": root, "country_there": "US"}
    assert maui["country_removed"] == {"country": "US", "because": root, "country_there": "US"}
    assert maui["effective_iana_timezone"] == "" and maui["requires_user_input"]                   # not Japan's zone
    assert wf.country_removals == [dict(hawaii["country_removed"], destination=f"{root}/Hawaii"),
                                   dict(maui["country_removed"], destination=f"{root}/Hawaii/Maui")]
    # said once: the next run finds nothing to remove
    art2, _ = wf.build_time_decisions(files, BOTH, art, _gpx([]))
    assert wf.country_removals == [] and "country_removed" not in art2["destinations"][f"{root}/Hawaii"]["destination_timezone"]
