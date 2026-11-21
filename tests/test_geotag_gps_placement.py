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

"""Phase 5a (geotag) — GPS placement from the GPX track at a photo's resolved UTC (BLD-track_placement).
GPS math, so the engine gets full branch coverage: direct match, time-fraction
interpolation (gap/distance/speed gates), and velocity extrapolation past either end. From
conftest.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CFG = {"gpx_direct_match_max_seconds": 60.0, "gpx_interpolation_max_gap_seconds": 120.0,
       "gpx_interpolation_max_distance_meters": 1000.0, "gpx_interpolation_max_speed_kmh": 150.0,
       "gpx_extrapolation_max_seconds": 120.0, "gpx_extrapolation_heading_seconds": 60.0,
       "gpx_extrapolation_max_distance_meters": 1000.0, "gpx_extrapolation_max_speed_kmh": 150.0,
       "gpx_tracks_agree_max_distance_meters": 1000.0}


def _utc(h, m, s):
    return datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc)


def _pt(lat, lon, h, m, s, src="t.gpx"):
    return cal.GPXPoint(lat, lon, _utc(h, m, s), src, 0)


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    return idx


def _cfg(**over):
    return {**CFG, **over}


# --- direct match ------------------------------------------------------------

def test_direct_match_boundary():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(51.0, 5.0, 13, 0, 0)])
    on = cal.place_gps(_utc(12, 1, 0), g, CFG)                       # exactly 60 s from pt0
    assert on["method"] == "direct_match" and (on["lat"], on["lon"]) == (50.0, 4.0)
    # just past 60 s -> not direct; the pair is 1 h apart (> max_gap), so the recording stopped at pt0:
    # that is an end of the track, and the photo is placed past it while within the extrapolation window
    assert cal.place_gps(_utc(12, 1, 1), g, CFG)["method"] == "extrapolated"
    why = {}
    assert cal.place_gps(_utc(12, 30, 0), g, CFG, why) is None      # 30 min from either side of the gap
    assert why == {"reason": "track_gap", "seconds_from_track": 1800, "gap_seconds": 3600}


# --- interpolation -----------------------------------------------------------

def test_interpolation_midpoint():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.002, 12, 1, 40)])   # 100 s apart, ~140 m
    r = cal.place_gps(_utc(12, 0, 50), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and r["lon"] == pytest.approx(4.001, abs=1e-6)  # ratio 0.5


@pytest.mark.spec("RUL-track_placement_bounded", test="TST-geotag_gps_placement-each_interpolation_gate_blocks")
def test_interpolation_each_gate_blocks():
    near = _cfg(gpx_direct_match_max_seconds=1.0)                    # force the interp path
    gap_fail = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.0001, 12, 5, 0)])    # 300 s > 120
    assert cal.place_gps(_utc(12, 2, 30), gap_fail, _cfg(gpx_direct_match_max_seconds=1.0,
                                                         gpx_extrapolation_max_seconds=60.0)) is None
    dist_fail = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.1, 4.0, 12, 1, 30)])     # ~11 km > 1000 m
    assert cal.place_gps(_utc(12, 0, 45), dist_fail, near) is None
    # speed gate: ~900 m in 30 s = 108 km/h passes; tighten the speed cap to force a fail
    speed = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.005, 12, 0, 30)])       # ~357 m / 30 s
    assert cal.place_gps(_utc(12, 0, 15), speed, _cfg(gpx_direct_match_max_seconds=1.0,
                                                      gpx_interpolation_max_speed_kmh=5.0)) is None


# --- extrapolation -----------------------------------------------------------

def test_extrapolation_forward_projects_velocity():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.001, 12, 1, 0)])   # heading east
    r = cal.place_gps(_utc(12, 2, 30), g, CFG)                         # 90 s past last (>60, <=120)
    assert r["method"] == "extrapolated" and r["lon"] > 4.001          # projected further east


def test_extrapolation_backward_projects_velocity():
    g = _gpx([_pt(50.0, 4.001, 12, 5, 0), _pt(50.0, 4.002, 12, 6, 0)])
    r = cal.place_gps(_utc(12, 3, 30), g, CFG)                         # 90 s before first
    assert r["method"] == "extrapolated" and r["lon"] < 4.001          # projected back west


@pytest.mark.spec("RUL-track_placement_bounded", test="TST-geotag_gps_placement-extrapolation_past_window_blocked")
def test_extrapolation_past_window_blocked():
    g = _gpx([_pt(50.0, 4.0, 12, 5, 0), _pt(50.0, 4.001, 12, 6, 0)])
    assert cal.place_gps(_utc(12, 9, 0), g, CFG) is None               # 180 s past last > 120 (forward)
    assert cal.place_gps(_utc(12, 0, 0), g, CFG) is None               # 300 s before first > 120 (backward)


@pytest.mark.spec("BLD-coordinate_precision", test="TST-geotag_gps_placement-coordinates_to_six_decimal_places")
def test_coordinates_to_six_decimal_places():
    """A position placed between two points, or projected past an end, is rounded to six decimal places; a direct
    match is the track point as the track gives it; and a photo already holding a position to six places, under the
    marker the write would carry, is written no position."""
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.001, 4.001, 12, 1, 0)])
    r = cal.place_gps(_utc(12, 0, 20), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and (r["lat"], r["lon"]) == (50.000333, 4.000333)
    r = cal.place_gps(_utc(12, 1, 20), _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.001, 12, 1, 0)]),
                      _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "extrapolated" and r["lon"] == 4.001333
    r = cal.place_gps(_utc(12, 0, 0), _gpx([_pt(50.12345678, 4.98765432, 12, 0, 0)]), CFG)
    assert r["method"] == "direct_match" and (r["lat"], r["lon"]) == (50.12345678, 4.98765432)
    coord = {"lat": 50.000333, "lon": 4.000333, "method": "interpolated"}
    f = {"relative_path": "a.jpg", "content_fingerprint": "fp", "size": 1, "mtime_ns": 1,
         "held": {"lat": 50.0003334, "lon": 4.0003334, "method": "interpolated"}}
    assert cal.plan_file_ops(f, None, None, "gpx_interpolation", coord, None) == []          # held to six places
    f["held"]["lat"] = 50.0003336
    assert "metadata_gps_write" in [o["type"] for o in cal.plan_file_ops(f, None, None, "gpx_interpolation", coord, None)]


@pytest.mark.spec("BLD-projection_without_heading", "RUL-track_placement_bounded",
                  test="TST-geotag_gps_placement-a_projection_with_no_heading_point_lands_on_the_end")
def test_a_projection_with_no_heading_point_lands_on_the_end():
    """Past an end whose nearest other point lies outside the heading stretch, there is nothing to take a heading
    over: the photo is placed on the end itself, still `extrapolated` — never projected from a point that far."""
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.001, 12, 1, 30)])   # 90 s apart: more than the 60 s stretch
    r = cal.place_gps(_utc(12, 3, 0), g, CFG)                          # 90 s past the last point
    assert r["method"] == "extrapolated" and (r["lat"], r["lon"]) == (50.0, 4.001)
    r = cal.place_gps(_utc(11, 58, 30), g, CFG)                        # 90 s before the first
    assert r["method"] == "extrapolated" and (r["lat"], r["lon"]) == (50.0, 4.0)
    near = _gpx([_pt(50.0, 4.0, 12, 0, 40), _pt(50.0, 4.001, 12, 1, 30)])   # 50 s apart: a heading
    assert cal.place_gps(_utc(12, 3, 0), near, CFG)["lon"] > 4.001


@pytest.mark.spec("BLD-projection_without_heading", test="TST-geotag_gps_placement-extrapolation_single_point_uses_endpoint")
def test_extrapolation_single_point_uses_endpoint():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0)])
    fwd = cal.place_gps(_utc(12, 1, 30), g, CFG)                       # 90 s after the only point
    assert fwd["method"] == "extrapolated" and (fwd["lat"], fwd["lon"]) == (50.0, 4.0)
    back = cal.place_gps(_utc(11, 58, 30), g, CFG)                     # 90 s before the only point
    assert back["method"] == "extrapolated" and (back["lat"], back["lon"]) == (50.0, 4.0)


@pytest.mark.spec("BLD-projection_without_heading", test="TST-geotag_gps_placement-extrapolation_zero_span_vector_uses_endpoint")
def test_extrapolation_zero_span_vector_uses_endpoint():
    # two end points at the same instant -> no velocity vector -> fall back to the endpoint coords
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.0, 12, 0, 0)])
    r = cal.place_gps(_utc(12, 1, 30), g, CFG)                        # 90 s past (beyond direct match)
    assert r["method"] == "extrapolated" and (r["lat"], r["lon"]) == (50.0, 4.0)


# --- no placement ------------------------------------------------------------

def test_empty_track_is_none():
    assert cal.place_gps(_utc(12, 0, 0), _gpx([]), CFG) is None


# --- pure helpers ------------------------------------------------------------

def test_interp_zero_span_returns_first():
    a = _pt(50.0, 4.0, 12, 0, 0)
    assert cal._interp(a, a, _utc(12, 0, 0)) == (50.0, 4.0)           # span 0 -> a's coords


def test_interp_extrapolates_outside_range():
    a, b = _pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.001, 12, 1, 0)
    lat, lon = cal._interp(a, b, _utc(12, 2, 0))                      # ratio 2.0
    assert lon == pytest.approx(4.002, abs=1e-9)


def test_config_extrapolation_threshold_rejects_negative():
    with pytest.raises(ValueError, match="gpx_extrapolation_max_seconds"):
        utils.validate_config({"gpx_extrapolation_max_seconds": -1})


# --- several tracks, and a track's own ends ----------------------------------

def _run_of(lat, lon, start_s, n, step, src, dlon=0.0):
    return [cal.GPXPoint(lat, lon + i * dlon, _utc(12, 0, 0) + timedelta(seconds=start_s + i * step), src, i)
            for i in range(n)]


@pytest.mark.spec("RUL-tracks_never_joined", "BLD-track_placement",
                  test="TST-geotag_gps_placement-two_tracks_are_never_joined")
def test_two_tracks_are_never_joined():
    """Two loggers a few metres apart, their points interleaved in time: the photo is placed on one of them,
    between two of ITS points — never between a point of one and a point of the other."""
    a = _run_of(50.0, 4.0, 0, 4, 100, "a.gpx")              # 12:00:00, 01:40, 03:20, 05:00
    b = _run_of(50.0002, 4.0, 50, 4, 100, "b.gpx")          # 12:00:50, 02:30, ...
    r = cal.place_gps(_utc(12, 1, 15), _gpx(a + b), _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and r["lat"] in (50.0, 50.0002)   # wholly one track's
    assert r["gpx_file"] in ("a.gpx", "b.gpx") and "gpx_after_file" not in r


@pytest.mark.spec("RUL-tracks_never_joined", test="TST-geotag_gps_placement-a_photo_between_two_files_is_not_bridged")
def test_a_photo_between_two_files_is_never_placed_across_them():
    """One file ends at 12:00:00, another starts 100 s later, both heading east: a photo at 12:00:50 falls in the gap
    between them. Joined, the two would place it between a's last point and b's first; apart, it is carried past the end
    of one of them — never interpolated across the two."""
    cfg = _cfg(gpx_direct_match_max_seconds=5.0)
    a = _run_of(50.0, 4.0, -60, 7, 10, "a.gpx", dlon=0.0001)                   # 11:59:00..12:00:00
    b = _run_of(50.0, 4.0012, 100, 7, 10, "b.gpx", dlon=0.0001)                # 12:01:40..12:02:40
    r = cal.place_gps(_utc(12, 0, 50), _gpx(a + b), cfg)
    assert r is not None and r["method"] == "extrapolated"
    assert r in (cal.place_gps(_utc(12, 0, 50), _gpx(a), cfg), cal.place_gps(_utc(12, 0, 50), _gpx(b), cfg))


@pytest.mark.spec("RUL-tracks_never_joined",
                  test="TST-geotag_gps_placement-a_heading_is_never_taken_across_two_tracks")
def test_a_heading_past_a_track_s_end_is_never_taken_across_two_tracks():
    """A photo past the end of a track is carried on along THAT track's heading: a point of another file
    lying within the heading stretch — before the end, or as the last point of all — gives it none."""
    cfg = _cfg(gpx_direct_match_max_seconds=5.0)
    # a.gpx is one point; b.gpx stood 55 m north of it during the minute before. Joined, b's points would
    # give a's end a heading south and carry the photo ~80 m on; alone, a's end has no heading at all.
    a = [cal.GPXPoint(50.0, 4.0, _utc(12, 1, 0), "a.gpx", 0)]
    b = _run_of(50.0005, 4.0, 0, 5, 10, "b.gpx")                               # 12:00:00..12:00:40
    r = cal.place_gps(_utc(12, 2, 30), _gpx(a + b), cfg)
    assert r == cal.place_gps(_utc(12, 2, 30), _gpx(a), cfg)
    assert r == {"lat": 50.0, "lon": 4.0, "method": "extrapolated", "gpx_file": "a.gpx"}
    # day.gpx heads east and ends 12:01:00; late.gpx is one point five seconds later, 30 m north of that
    # end. The last two points of all span the two files: late's own end is still a point with no heading,
    # and day's heading is still due east — neither is bent towards the other.
    day = _run_of(50.0, 4.0, 0, 7, 10, "day.gpx", dlon=0.0001)
    late = [cal.GPXPoint(50.00027, 4.0006, _utc(12, 1, 5), "late.gpx", 0)]
    r = cal.place_gps(_utc(12, 2, 30), _gpx(day + late), cfg)
    assert r == {"lat": 50.00027, "lon": 4.0006, "method": "extrapolated", "gpx_file": "late.gpx"}
    # the same stray point five seconds BEFORE day's end: day's last two points of all are then late's and
    # its own, and its heading is still the one its own points give
    stray = [cal.GPXPoint(50.00027, 4.0006, _utc(12, 0, 55), "late.gpx", 0)]
    r = cal.place_gps(_utc(12, 2, 30), _gpx(day + stray), cfg)
    assert r == cal.place_gps(_utc(12, 2, 30), _gpx(day), cfg)
    assert r["lat"] == 50.0 and r["lon"] > 4.0006 and r["gpx_file"] == "day.gpx"


@pytest.mark.spec("RUL-disagreeing_tracks_place_nothing", "BLD-track_placement", "RUL-disagreeing_tracks_named",
                  test="TST-geotag_gps_placement-tracks_in_two_places_place_nothing")
def test_tracks_in_two_places_place_nothing():
    """Two tracks cover the photo's time five kilometres apart — two people, and nothing says which carried
    the camera: the tracks place nothing, and say which of them disagree."""
    alice = _run_of(48.0, 11.0, 0, 30, 10, "alice.gpx")
    bob = _run_of(48.05, 11.0, 5, 30, 10, "bob.gpx")
    why = {}
    assert cal.place_gps(_utc(12, 1, 43), _gpx(alice + bob), CFG, why) is None
    assert why["reason"] == "tracks_disagree" and why["gpx_files"] == ["alice.gpx", "bob.gpx"]
    assert why["apart_meters"] > 5000
    # the same two a street apart are one party: the nearer in time places the photo
    near = _run_of(48.001, 11.0, 5, 30, 10, "bob.gpx")
    assert cal.place_gps(_utc(12, 1, 43), _gpx(alice + near), CFG)["gpx_file"] == "bob.gpx"


@pytest.mark.spec("RUL-disagreeing_tracks_place_nothing", "BLD-track_placement",
                  test="TST-geotag_gps_placement-every_two_tracks_of_one_rank_are_compared")
def test_every_two_tracks_of_one_rank_are_compared():
    """Three tracks cover the photo's time: the best between the two others, each of them within reach of it but
    farther than tracks may differ from each other. Two of them are in two places: the photo is not placed."""
    a = _run_of(48.0, 11.0, 0, 30, 10, "a.gpx")
    b = _run_of(48.006, 11.0, 0, 30, 10, "b.gpx")                 # some 670 m north of a
    c = _run_of(47.994, 11.0, 0, 30, 10, "c.gpx")                 # some 670 m south of a, 1.3 km from b
    why = {}
    assert cal.place_gps(_utc(12, 1, 40), _gpx(a + b + c), CFG, why) is None
    assert why["reason"] == "tracks_disagree" and why["gpx_files"] == ["b.gpx", "c.gpx"]
    assert cal.place_gps(_utc(12, 1, 40), _gpx(a + b), CFG)["gpx_file"] == "a.gpx"     # two that agree place it


@pytest.mark.spec("RUL-track_evidence_order", "BLD-track_placement",
                  test="TST-geotag_gps_placement-a_track_s_end_is_its_own")
def test_a_track_s_end_is_its_own_whatever_other_tracks_exist():
    """A photo two minutes after the day's track stops is placed past that track's end — whether or not a
    track of another day, a thousand kilometres off, exists: a track's end is where ITS recording stops."""
    day = _run_of(50.0, 4.0, 0, 7, 10, "day.gpx", dlon=0.0001)                 # ends 12:01:00, heading east
    later = [cal.GPXPoint(60.0, 10.0, _utc(12, 0, 0) + timedelta(days=30), "later.gpx", 0)]
    alone = cal.place_gps(_utc(12, 2, 50), _gpx(day), CFG)
    among = cal.place_gps(_utc(12, 2, 50), _gpx(day + later), CFG)
    assert alone == among and alone["method"] == "extrapolated" and alone["gpx_file"] == "day.gpx"
    assert alone["lon"] > 4.0006                                               # carried on along its heading


@pytest.mark.spec("RUL-track_placement_bounded", "BLD-track_placement",
                  test="TST-geotag_gps_placement-a_projection_is_bounded")
def test_a_projection_past_an_end_is_bounded():
    """The heading at a track's end is read over its last stretch, never its last two points alone, and a
    projection farther or faster than points are joined across puts the photo at the end itself."""
    # the last two points jitter 20 m apart in one second; the stretch before stood still
    still = _run_of(50.0, 4.0, 0, 13, 5, "t.gpx")                              # 12:00:00..12:01:00, one place
    jitter = [cal.GPXPoint(50.00018, 4.0, _utc(12, 1, 1), "t.gpx", 99)]
    r = cal.place_gps(_utc(12, 3, 0), _gpx(still + jitter), CFG)               # 119 s past the end
    assert r["method"] == "extrapolated"
    assert cal.haversine(50.00018, 4.0, r["lat"], r["lon"]) < 100              # not 2.4 km up the jitter
    # a real 130 km/h heading would carry the photo 4 km on: beyond the cap, so it stays at the end
    car = _run_of(50.0, 4.0, 0, 7, 10, "car.gpx", dlon=0.005)                  # ~360 m per 10 s
    r = cal.place_gps(_utc(12, 2, 50), _gpx(car), CFG)
    assert (r["lat"], r["lon"]) == (50.0, 4.03) and r["method"] == "extrapolated"


@pytest.mark.spec("RUL-track_placement_bounded", test="TST-geotag_gps_placement-across_the_antimeridian")
def test_interpolation_across_the_antimeridian_goes_the_short_way():
    """Two points 200 m apart either side of longitude 180: the photo between them is at 180, not at 0."""
    g = _gpx([_pt(-16.8, 179.999, 12, 0, 0), _pt(-16.8, -179.999, 12, 1, 40)])
    r = cal.place_gps(_utc(12, 0, 50), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and abs(abs(r["lon"]) - 180.0) < 1e-6
    assert cal.haversine(0, 0, 0, 0) == 0.0 and cal.haversine(10, 20, -10, -160) > 2e7   # antipodes: no domain error


@pytest.mark.spec("RUL-unplaced_photo_listed", "RUL-unplaced_photo_says_why",
                  test="TST-geotag_gps_placement-why_the_tracks_placed_nothing")
def test_why_the_tracks_placed_nothing_is_said():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.2, 4.0, 12, 1, 40)])            # 22 km in 100 s
    why = {}
    assert cal.place_gps(_utc(12, 0, 50), g, _cfg(gpx_direct_match_max_seconds=5.0), why) is None
    assert why["reason"] == "track_jump" and why["jump_meters"] > 20000
    why = {}
    assert cal.place_gps(_utc(15, 0, 0), g, CFG, why) is None
    assert why == {"reason": "outside_track", "seconds_from_track": 10700}
    why = {}
    assert cal.place_gps(_utc(15, 0, 0), _gpx([]), CFG, why) is None and why == {"reason": "no_tracks"}


# --- each setting bounds one thing --------------------------------------------------------------------------

@pytest.mark.spec("RUL-setting_bounds_one_thing", "BLD-track_placement",
                  test="TST-geotag_gps_placement-the_heading_stretch_is_its_own_setting")
def test_the_heading_stretch_is_its_own_setting():
    """How far back a track's heading is read is one setting, and how close a point is the photo's place
    another: moving either leaves the other's answer where it was."""
    still = _run_of(50.0, 4.0, 0, 13, 5, "t.gpx")                              # 12:00:00..12:01:00, one place
    jitter = [cal.GPXPoint(50.00018, 4.0, _utc(12, 1, 1), "t.gpx", 99)]        # 20 m off in the last second
    g, at = _gpx(still + jitter), _utc(12, 1, 31)                              # 30 s past the end
    long_stretch = [cal.place_gps(at, g, _cfg(gpx_direct_match_max_seconds=d)) for d in (5.0, 20.0)]
    assert long_stretch[0] == long_stretch[1] and long_stretch[0]["method"] == "extrapolated"
    assert cal.haversine(50.00018, 4.0, long_stretch[0]["lat"], 4.0) < 100
    short = cal.place_gps(at, g, _cfg(gpx_direct_match_max_seconds=5.0, gpx_extrapolation_heading_seconds=1.0))
    assert cal.haversine(50.00018, 4.0, short["lat"], 4.0) > 500               # the jitter, projected
    assert cal.place_gps(at, g, CFG)["method"] == "direct_match"               # the place setting, unmoved


@pytest.mark.spec("RUL-setting_bounds_one_thing", "RUL-track_placement_bounded", "BLD-track_placement",
                  test="TST-geotag_gps_placement-a_projection_has_its_own_bounds")
def test_a_projection_has_its_own_bounds():
    """How far and how fast a projection past a track's end may go is not what bounds joining two points."""
    car = _run_of(50.0, 4.0, 0, 7, 10, "car.gpx", dlon=0.005)                  # ~130 km/h, ends 12:01:00
    at = _utc(12, 2, 50)
    end = (50.0, 4.03)
    tight_joining = cal.place_gps(at, _gpx(car), _cfg(gpx_interpolation_max_distance_meters=1.0,
                                                      gpx_interpolation_max_speed_kmh=1.0))
    assert (tight_joining["lat"], tight_joining["lon"]) == end                 # as with the defaults
    far = cal.place_gps(at, _gpx(car), _cfg(gpx_extrapolation_max_distance_meters=10000.0))
    assert far["lon"] > 4.08                                                   # carried on along the heading
    slow = cal.place_gps(at, _gpx(car), _cfg(gpx_extrapolation_max_distance_meters=10000.0,
                                             gpx_extrapolation_max_speed_kmh=100.0))
    assert (slow["lat"], slow["lon"]) == end
    # and joining is unmoved by the projection's bounds
    between = _utc(12, 0, 5)
    loose = _cfg(gpx_direct_match_max_seconds=1.0)
    assert cal.place_gps(between, _gpx(car), loose)["method"] == "interpolated"
    assert cal.place_gps(between, _gpx(car), {**loose, "gpx_extrapolation_max_distance_meters": 1.0,
                                              "gpx_extrapolation_max_speed_kmh": 1.0})["method"] == "interpolated"


@pytest.mark.spec("RUL-setting_bounds_one_thing", "RUL-disagreeing_tracks_place_nothing", "BLD-track_placement",
                  test="TST-geotag_gps_placement-how_far_apart_tracks_disagree_is_its_own_setting")
def test_how_far_apart_tracks_disagree_is_its_own_setting():
    alice = _run_of(48.0, 11.0, 0, 30, 10, "alice.gpx")
    bob = _run_of(48.05, 11.0, 5, 30, 10, "bob.gpx")                           # 5.5 km away
    near = _run_of(48.001, 11.0, 5, 30, 10, "bob.gpx")                         # 111 m away
    at = _utc(12, 1, 43)
    assert cal.place_gps(at, _gpx(alice + bob), _cfg(gpx_tracks_agree_max_distance_meters=10000.0)) is not None
    assert cal.place_gps(at, _gpx(alice + near), _cfg(gpx_tracks_agree_max_distance_meters=50.0)) is None
    # what bounds joining two points of one track says nothing about two tracks
    assert cal.place_gps(at, _gpx(alice + bob), _cfg(gpx_interpolation_max_distance_meters=10000.0)) is None
    assert cal.place_gps(at, _gpx(alice + near), _cfg(gpx_interpolation_max_distance_meters=50.0)) is not None


# --- a track is one <trk>, and a break between two <trkseg> is never bridged --------

def _gpx_file(tmp_path, name, body):
    """A GPX file under a tracks folder of its own, read as geotag reads it; `body` is the <trk> elements."""
    root = tmp_path / "gpx"
    root.mkdir(exist_ok=True)
    (root / name).write_text(f'<gpx xmlns="http://www.topografix.com/GPX/1/1">{body}</gpx>')
    return cal.GPXIndex(str(root)).build()


def _trk(*segments):
    """A <trk> of the given segments, each a list of (lat, lon, seconds after 12:00:00 UTC)."""
    def pt(lat, lon, s):
        return (f'<trkpt lat="{lat}" lon="{lon}"><time>'
                f'{(_utc(12, 0, 0) + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>')
    return "<trk>" + "".join("<trkseg>" + "".join(pt(*p) for p in seg) + "</trkseg>" for seg in segments) + "</trk>"


def _track_times(tmp_path, times):
    """{index in `times`: the UTC instant geotag read} for a track of one point at each of `times`, and its
    warnings."""
    body = "<trk><trkseg>" + "".join(f'<trkpt lat="50.0" lon="{4 + i / 1000}"><time>{t}</time></trkpt>'
                                     for i, t in enumerate(times)) + "</trkseg></trk>"
    g = _gpx_file(tmp_path, "t.gpx", body)
    return {round((p.lon - 4) * 1000): p.time_utc for p in g.points}, g.warnings


@pytest.mark.spec("BLD-track_time_parser", "RUL-track_time_never_guessed",
                  test="TST-geotag_gps_placement-a_fraction_of_any_length_is_cut_to_microseconds")
def test_a_fraction_of_any_length_is_cut_to_microseconds(tmp_path):
    """A fraction of a second of 1, 2, 3, 4, 6, 7 or 9 digits is read on every Python, cut to microseconds and never
    rounded: a time never moves forward."""
    fracs = ["9", "99", "999", "9999", "999999", "9999999", "999999999"]
    read, warnings = _track_times(tmp_path, [f"2024-07-03T12:00:00.{f}Z" for f in fracs])
    assert warnings == []
    assert [read[i] for i in range(len(fracs))] == [
        _utc(12, 0, 0).replace(microsecond=int(f[:6].ljust(6, "0"))) for f in fracs]
    assert read[6] == read[5] == read[4] == _utc(12, 0, 0).replace(microsecond=999999)


@pytest.mark.spec("BLD-track_time_parser", "RUL-track_time_never_guessed",
                  test="TST-geotag_gps_placement-track_times_are_read_with_the_zone_they_state")
def test_track_times_are_read_with_the_zone_they_state(tmp_path):
    """Each zone form xsd:dateTime has — `Z`, a positive and a negative offset, `-00:00` — is the instant it states;
    `24:00:00` is the next day's midnight."""
    times = ["2024-07-03T12:00:00Z", "2024-07-03T12:00:00z", "2024-07-03T14:00:00+02:00",
             "2024-07-03T06:30:00-05:30", "2024-07-03T12:00:00-00:00", "2024-07-02T24:00:00+12:00"]
    read, warnings = _track_times(tmp_path, times)
    assert warnings == []
    assert [read[i] for i in range(5)] == [_utc(12, 0, 0)] * 5
    assert read[5] == _utc(0, 0, 0) - timedelta(hours=12)


@pytest.mark.spec("BLD-track_time_parser", "RUL-track_time_never_guessed", "RUL-unreadable_point_skipped",
                  test="TST-geotag_gps_placement-a_time_not_xsd_datetime_or_with_no_zone_is_skipped")
def test_a_time_not_xsd_datetime_or_with_no_zone_is_skipped(tmp_path):
    """A time with no zone is never read as some zone's, and a form that is not xsd:dateTime — though another
    ISO 8601 reader takes it — is unparseable, on every Python: each point is skipped with a warning."""
    times = ["2024-07-03T12:00:00",            # no zone
             "2024-07-03T12:00:00.5",          # no zone, a fraction
             "2024-07-03 12:00:00+00:00",      # a space for the T
             "20240703T120000Z",               # the basic format
             "2024-W27-3T12:00:00Z",           # a week date
             "2024-07-03T12:00Z",              # no seconds
             "2024-07-03T12:00:00+0200",       # an offset with no colon
             "2024-07-03T12:00:00+02:99",      # minutes of the offset out of range
             "2024-07-03T12:00:00.Z",          # a point with no fraction
             "2024-07-03T24:00:01Z",           # past the end of the day
             "2024-07-03T12:00:00Z"]           # the one readable
    read, warnings = _track_times(tmp_path, times)
    assert set(read) == {len(times) - 1}
    assert len(warnings) == len(times) - 1
    assert all("t.gpx" in w and "trkpt" in w for w in warnings)
    assert sum("without timezone" in w for w in warnings) == 2


@pytest.mark.spec("RUL-track_is_one_trk", "RUL-tracks_never_joined", "BLD-track_placement",
                  test="TST-geotag_gps_placement-two_trk_of_one_file_are_never_joined")
def test_two_trk_of_one_file_are_never_joined(tmp_path):
    """An export holding two devices' tracks for the same hours, as two <trk> of one file: the photo is placed on
    one of them, between two of ITS points, never zig-zagging between them; and two that put the instant 5 km
    apart place nothing, both named, each by its place in the file. The placement names the file."""
    a = [(50.0, 4.0, s) for s in range(0, 400, 100)]
    b = [(50.0002, 4.0, s) for s in range(50, 450, 100)]
    g = _gpx_file(tmp_path, "both.gpx", _trk(a) + _trk(b))
    assert len(g.tracks()) == 2
    r = cal.place_gps(_utc(12, 1, 15), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and r["lat"] in (50.0, 50.0002), r
    assert r["gpx_file"] == "both.gpx" and set(r) == {"lat", "lon", "method", "gpx_file"}
    (tmp_path / "far").mkdir()
    far = _gpx_file(tmp_path / "far", "both.gpx", _trk([(48.0, 11.0, s) for s in range(0, 300, 10)])
                    + _trk([(48.05, 11.0, s) for s in range(5, 305, 10)]))
    why = {}
    assert cal.place_gps(_utc(12, 1, 43), far, CFG, why) is None
    assert why["reason"] == "tracks_disagree" and why["apart_meters"] > 5000
    assert why["gpx_files"] == ["both.gpx (track 1)", "both.gpx (track 2)"]


@pytest.mark.spec("RUL-track_is_one_trk", test="TST-geotag_gps_placement-one_trk_of_many_segments_is_one_track")
def test_one_trk_of_many_segments_is_one_track(tmp_path):
    """The nearest safe case: one <trk> is one track however many <trkseg> it holds, and a photo within a segment
    is interpolated as before; two files are two tracks as before."""
    g = _gpx_file(tmp_path, "t.gpx", _trk([(50.0, 4.0, 0), (50.0, 4.002, 100)], [(50.0, 4.01, 600), (50.0, 4.012, 700)]))
    assert len(g.tracks()) == 1
    r = cal.place_gps(_utc(12, 0, 50), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and r["lon"] == pytest.approx(4.001, abs=1e-6)
    r = cal.place_gps(_utc(12, 10, 50), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and r["lon"] == pytest.approx(4.011, abs=1e-6)


@pytest.mark.spec("RUL-track_break_never_bridged", "BLD-track_placement",
                  test="TST-geotag_gps_placement-a_break_between_segments_is_never_bridged")
def test_a_break_between_segments_is_never_bridged(tmp_path):
    """The recording broke for a minute — two <trkseg> of one track, 70 m apart, well within what points are
    joined across. A photo in the break is never placed between them: it is placed past the end nearer it, along
    that segment's own heading, while within the extrapolation window; beyond, nothing places it, the break the
    reason. The same points in one segment are interpolated, as before."""
    cfg = _cfg(gpx_direct_match_max_seconds=5.0)
    first = [(50.0, 3.999, 0), (50.0, 3.9995, 30), (50.0, 4.0, 60)]               # heading east to 12:01:00
    second = [(50.0005, 4.001, 120), (50.001, 4.001, 150)]                       # then north from 12:02:00
    broken = _gpx_file(tmp_path, "t.gpx", _trk(first, second))
    (tmp_path / "whole").mkdir()
    whole = _gpx_file(tmp_path / "whole", "t.gpx", _trk(first + second))
    assert cal.place_gps(_utc(12, 1, 20), whole, cfg)["method"] == "interpolated"
    r = cal.place_gps(_utc(12, 1, 20), broken, cfg)
    assert r["method"] == "extrapolated" and r["lat"] == 50.0 and r["lon"] > 4.0, r
    assert r == cal.place_gps(_utc(12, 1, 20), _gpx([p for p in broken.points if p.segment == 0]), cfg)
    why = {}
    assert cal.place_gps(_utc(12, 1, 30), broken, _cfg(gpx_direct_match_max_seconds=5.0,
                                                       gpx_extrapolation_max_seconds=10.0), why) is None
    assert why == {"reason": "track_gap", "seconds_from_track": 30, "gap_seconds": 60, "segment_break": True}


@pytest.mark.spec("RUL-track_break_never_bridged", "BLD-track_placement",
                  test="TST-geotag_gps_placement-a_heading_is_never_taken_across_a_break")
def test_a_heading_is_never_taken_across_a_break(tmp_path):
    """A photo before a segment of one point is placed at that point: the next segment's points, half a minute
    later, give it no heading."""
    g = _gpx_file(tmp_path, "t.gpx", _trk([(50.0, 4.0, 60)],
                                          [(50.0, 4.001, 90), (50.0, 4.002, 100), (50.0, 4.003, 110)]))
    r = cal.place_gps(_utc(11, 59, 30), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r == {"lat": 50.0, "lon": 4.0, "method": "extrapolated", "gpx_file": "t.gpx"}, r
