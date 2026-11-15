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

"""Geotag — the tracks ranked by the folder they are filed in (`gpx_track_precedence`): the better device places
and anchors first, a worse one serves where the better recorded nothing, and how far the worse one put each photo
is kept and counted, never asked about."""
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

BYDEST = "6-photos-by-dest"
CFG = dict(utils.DEFAULT_CONFIG)
BASE = datetime(2024, 7, 3, 12, 0, 0, tzinfo=timezone.utc)
KM = 180 / (math.pi * 6371.0)   # one kilometre of latitude, in degrees, on the sphere geotag measures by


def _at(seconds):
    return BASE + timedelta(seconds=seconds)


def _track(src, lat, lon, start, stop, step=10, track=0):
    return [cal.GPXPoint(lat, lon, _at(t), src, i, track, 0) for i, t in enumerate(range(start, stop, step))]


def _gpx(points, precedence=("phone", "receiver")):
    idx = cal.GPXIndex("", precedence=precedence)
    idx.points = list(points)
    return idx


# --- the rank of a track ---------------------------------------------------------------------------------------

@pytest.mark.spec("RUL-tracks_ranked_by_folder", "BLD-track_precedence",
                  test="TST-geotag_track_precedence-a_track_ranks_as_its_folder")
def test_a_track_ranks_as_the_folder_it_is_filed_in():
    """The first folder named ranks first; a track deeper inside it ranks as it; a track in no ranked folder, or
    at the top of the tracks, ranks below every ranked one, all such alike. Nothing ranked: all alike."""
    g = _gpx([])
    assert g.rank("phone/2024/a.gpx") == 0 and g.rank("phone/b.gpx") == 0
    assert g.rank("receiver/a.gpx") == 1
    assert g.rank("friend/a.gpx") == g.rank("loose.gpx") == 2
    assert g.rank("phonex/a.gpx") == 2                         # a folder, not a prefix of a name
    plain = _gpx([], precedence=())
    assert plain.rank("phone/a.gpx") == plain.rank("x.gpx") == 0


@pytest.mark.spec("RUL-ranked_folder_missing_told", "BLD-track_precedence",
                  test="TST-geotag_track_precedence-a_ranked_folder_not_there_is_told")
def test_a_ranked_folder_the_tracks_lack_is_told(tmp_path):
    """A ranked folder that is not under the tracks folder — misspelt, or not made yet — would rank nothing in
    silence: it is warned of, first, and the tracks are read as usual."""
    root = tmp_path / "gpx"
    (root / "phone").mkdir(parents=True)
    (root / "phone" / "a.gpx").write_text(
        '<gpx><trk><trkseg><trkpt lat="50" lon="4"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    idx = cal.GPXIndex(str(root), precedence=["phone", "reciever"]).build()
    assert idx.status == "usable"
    assert len(idx.warnings) == 1 and "'reciever'" in idx.warnings[0] and "gpx_track_precedence" in idx.warnings[0]
    assert cal.GPXIndex(str(root), precedence=["phone"]).build().warnings == []


@pytest.mark.spec("RUL-track_ranking_in_dependencies", "BLD-track_precedence",
                  test="TST-geotag_track_precedence-the_ranking_enters_the_tracks_fingerprint")
def test_the_ranking_enters_the_tracks_fingerprint(tmp_path):
    """The same files ranked another way are other evidence: the tracks' fingerprint — which every record geotag
    derives from them depends on — changes with the ranking, and only with it."""
    root = tmp_path / "gpx"
    for d in ("phone", "receiver"):
        (root / d).mkdir(parents=True)
        (root / d / "t.gpx").write_text(
            '<gpx><trk><trkseg><trkpt lat="50" lon="4"><time>2024-07-03T12:00:00Z</time></trkpt>'
            '</trkseg></trk></gpx>')
    fp = lambda prec: cal.GPXIndex(str(root), precedence=prec).build().fingerprint
    assert fp(["phone", "receiver"]) == fp(["phone", "receiver"])
    assert len({fp([]), fp(["phone", "receiver"]), fp(["receiver", "phone"])}) == 3


@pytest.mark.spec("BLD-track_precedence", test="TST-geotag_track_precedence-the_ranking_setting_is_checked")
@pytest.mark.parametrize("bad", ["phone", ["phone", "phone"], ["a/b"], [""], [".hidden"], [3]])
def test_the_ranking_setting_is_checked(bad):
    """The ranking names folders directly under the tracks folder, each once."""
    with pytest.raises(ValueError, match="gpx_track_precedence"):
        utils.validate_config({"gpx_track_precedence": bad})
    utils.validate_config({"gpx_track_precedence": ["phone", "receiver"]})


# --- placing ---------------------------------------------------------------------------------------------------

@pytest.mark.spec("RUL-highest_ranked_track_places", "RUL-disagreeing_tracks_place_nothing", "BLD-track_placement",
                  test="TST-geotag_track_precedence-the_higher_ranked_track_places")
def test_the_higher_ranked_track_places_whatever_the_lower_says():
    """Phone and receiver both cover the photo's time, five kilometres apart: unranked, that is two people and
    nothing is placed; ranked, the phone places it — even by a point between two, against the receiver's point at
    the very second — and the receiver's distance is kept with the position."""
    phone = [cal.GPXPoint(50.0, 4.0, _at(0), "phone/p.gpx", 0), cal.GPXPoint(50.0, 4.0, _at(600), "phone/p.gpx", 1)]
    receiver = _track("receiver/r.gpx", 50.0 + 5 * KM, 4.0, 0, 700)
    assert cal.place_gps(_at(300), _gpx(phone + receiver, precedence=()), CFG) is None
    got = cal.place_gps(_at(300), _gpx(phone + receiver), CFG)
    assert (got["lat"], got["lon"], got["method"], got["gpx_file"]) == (50.0, 4.0, "interpolated", "phone/p.gpx")
    assert got["lower_tracks"] == [{"gpx_file": "receiver/r.gpx", "apart_meters": 5000}]


@pytest.mark.spec("RUL-highest_ranked_track_places", "BLD-track_placement",
                  test="TST-geotag_track_precedence-a_lower_track_serves_where_the_higher_recorded_nothing")
def test_a_lower_track_serves_where_the_higher_recorded_nothing():
    """The phone stopped at noon; the receiver ran on. A photo of the afternoon is placed by the receiver, with
    nothing to compare. A photo a minute past the phone's end, which the phone could only project to: the receiver
    covers the instant and places it — a projection is no witness against a track that recorded the time."""
    phone = _track("phone/p.gpx", 50.0, 4.0, -600, 1)
    receiver = _track("receiver/r.gpx", 50.0 + 0.2 * KM, 4.0, -600, 4000)
    g = _gpx(phone + receiver)
    later = cal.place_gps(_at(3600), g, CFG)
    assert later["gpx_file"] == "receiver/r.gpx" and "lower_tracks" not in later
    edge = cal.place_gps(_at(90), g, CFG)
    assert edge["gpx_file"] == "receiver/r.gpx" and edge["method"] == "direct_match"


@pytest.mark.spec("RUL-disagreeing_tracks_place_nothing", "RUL-disagreeing_tracks_named", "BLD-track_placement",
                  test="TST-geotag_track_precedence-tracks_of_one_rank_that_disagree_place_nothing")
def test_tracks_of_one_rank_that_disagree_still_place_nothing():
    """A companion's track filed in no ranked folder, with another unranked one: two of one rank five kilometres
    apart are still two people, named, and the photo is not placed. A ranked track above both settles it."""
    a = _track("friend/a.gpx", 50.0, 4.0, 0, 700)
    b = _track("loose.gpx", 50.0 + 5 * KM, 4.0, 0, 700)
    why = {}
    assert cal.place_gps(_at(300), _gpx(a + b), CFG, why) is None
    assert why["reason"] == "tracks_disagree" and why["gpx_files"] == ["friend/a.gpx", "loose.gpx"]
    mine = _track("phone/p.gpx", 50.0, 4.0, 0, 700)
    got = cal.place_gps(_at(300), _gpx(a + b + mine), CFG)
    assert got["gpx_file"] == "phone/p.gpx"
    assert got["lower_tracks"] == [{"gpx_file": "friend/a.gpx", "apart_meters": 0},
                                   {"gpx_file": "loose.gpx", "apart_meters": 5000}]


# --- anchoring -------------------------------------------------------------------------------------------------

def _frame(lat, lon, seconds):
    return {"native_gps": {"lat": lat, "lon": lon}, "source_naive_time": _at(seconds).strftime("%Y:%m:%d %H:%M:%S"),
            "relative_path": f"{BYDEST}/B/x.arw"}


@pytest.mark.spec("RUL-lower_track_anchors_where_higher_absent", "BLD-anchor_matching",
                  test="TST-geotag_track_precedence-a_lower_track_anchors_only_where_the_higher_recorded_nothing")
def test_a_lower_track_anchors_only_where_the_higher_recorded_nothing():
    """A camera photo taken where the receiver passed at 12:05 — when the phone, recording, was 5 km away: the
    receiver anchors nothing then. Where the phone recorded nothing, the receiver anchors."""
    phone = _track("phone/p.gpx", 50.0 + 5 * KM, 4.0, 0, 700)
    receiver = _track("receiver/r.gpx", 50.0, 4.0, 0, 700)
    photo = _frame(50.0, 4.0, 300)
    assert cal.frame_candidates(photo, _gpx(phone + receiver), CFG) == []
    assert [c["gpx_file"] for c in cal.frame_candidates(photo, _gpx(receiver), CFG)] == ["receiver/r.gpx"]
    unranked = cal.frame_candidates(photo, _gpx(phone + receiver, precedence=()), CFG)
    assert [c["gpx_file"] for c in unranked] == ["receiver/r.gpx"]
    late_phone = _track("phone/p.gpx", 50.0 + 5 * KM, 4.0, 5000, 6000)        # recording only later
    got = cal.frame_candidates(photo, _gpx(late_phone + receiver), CFG)
    assert [c["gpx_file"] for c in got] == ["receiver/r.gpx"]


# --- what is recorded and told ---------------------------------------------------------------------------------

def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "gfp"
    return wf


@pytest.mark.spec("RUL-lower_track_disagreements_told", "BLD-lower_tracks_recorded",
                  test="TST-geotag_track_precedence-lower_tracks_that_disagree_are_counted")
def test_lower_tracks_that_disagree_are_counted(tmp_path):
    """Three photos the phone placed: at two the receiver lay 5 km off, at one 20 m. The GPS decisions count the
    two, by track, and nothing asks about them."""
    d = f"{BYDEST}/T"
    phone = _track("phone/p.gpx", 50.0, 4.0, 0, 2000)
    receiver = (_track("receiver/r.gpx", 50.0 + 5 * KM, 4.0, 0, 700)
                + _track("receiver/r.gpx", 50.0 + 0.02 * KM, 4.0, 1000, 2000))
    files = [{"relative_path": f"{d}/{n}.arw", "destination": d, "has_native_gps": False} for n in "abc"]
    rows = [{"relative_path": f"{d}/{n}.arw", "resolved_utc": _at(t).strftime("%Y-%m-%dT%H:%M:%SZ")}
            for n, t in zip("abc", (100, 300, 1500))]
    art, blockers = _wf(tmp_path).build_gps_decisions(files, rows, _gpx(phone + receiver), None, "rfp")
    assert not blockers and art["status"] == "complete"
    assert art["destinations"][d]["gps_decisions"]["summary"]["automatic_gpx_interpolation"] == 3
    assert art["lower_track_disagreements"] == [{"gpx_file": "receiver/r.gpx", "outranked_by": "phone/p.gpx",
                                                 "photos": 2}]
    assert "track_disagreements" not in art


@pytest.mark.spec("RUL-lower_track_distance_recorded", "BLD-lower_tracks_recorded",
                  test="TST-geotag_track_precedence-the_position_is_recorded_with_the_lower_tracks")
def test_the_position_is_recorded_with_how_far_the_lower_tracks_put_it(tmp_path):
    """The plan's position write keeps, beside the track that placed the photo, how far the receiver put it."""
    ws = tmp_path / "ws"; ctl = ws / ".photos-ingest"; ctl.mkdir(parents=True)
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps(
        {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "cache_fingerprint": "pcf"}))
    d, rel = f"{BYDEST}/T", f"{BYDEST}/T/a.jpg"
    f = {"relative_path": rel, "destination": d, "has_native_gps": False, "content_fingerprint": "fp-a",
         "size": 10, "mtime_ns": 1, "native_gps": None}
    t = {"status": "complete", "destinations": {d: {"destination_timezone": {"effective_iana_timezone": "Europe/Brussels"}}}}
    g = {"status": "complete", "destinations": {d: {"folder_fallback": {"effective_fallback": None},
                                                   "gps_decisions": {"review_items": []}}}}
    for name, art in (("photos-21-time-decisions.json", t), ("photos-23-gps-decisions.json", g),
                      ("photos-22-gps-drift-validation.json", {"status": "complete", "destinations": {}})):
        (ctl / name).write_text(json.dumps(art))
    wf = cal.GeotagWorkflow(str(ws)); wf.handoff = {"cache_fingerprint": "pcf"}; wf._gpx_fingerprint = "g"
    gpx = _gpx(_track("phone/p.gpx", 50.0, 4.0, 0, 700) + _track("receiver/r.gpx", 50.0 + 0.03 * KM, 4.0, 0, 700))
    row = {"relative_path": rel, "resolved_utc": _at(300).strftime("%Y-%m-%dT%H:%M:%SZ"), "resolved_utc_status": "valid"}
    plan, blockers = wf.build_executable_plan([f], [row], t, g, gpx, "rfp")
    assert blockers == []
    w = next(o for dd in plan["destinations"].values() for o in dd["operations"] if o["type"] == "metadata_gps_write")
    assert w["provenance"]["gpx_file"] == "phone/p.gpx"
    assert w["provenance"]["lower_tracks"] == [{"gpx_file": "receiver/r.gpx", "apart_meters": 30}]
