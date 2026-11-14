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

"""Phase 5a (geotag) — GPS placement from the GPX track at a photo's resolved UTC (spec §23
options 4/5). GPS math, so the engine gets full branch coverage: direct match, time-fraction
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


def test_extrapolation_past_window_blocked():
    g = _gpx([_pt(50.0, 4.0, 12, 5, 0), _pt(50.0, 4.001, 12, 6, 0)])
    assert cal.place_gps(_utc(12, 9, 0), g, CFG) is None               # 180 s past last > 120 (forward)
    assert cal.place_gps(_utc(12, 0, 0), g, CFG) is None               # 300 s before first > 120 (backward)


def test_extrapolation_single_point_uses_endpoint():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0)])
    fwd = cal.place_gps(_utc(12, 1, 30), g, CFG)                       # 90 s after the only point
    assert fwd["method"] == "extrapolated" and (fwd["lat"], fwd["lon"]) == (50.0, 4.0)
    back = cal.place_gps(_utc(11, 58, 30), g, CFG)                     # 90 s before the only point
    assert back["method"] == "extrapolated" and (back["lat"], back["lon"]) == (50.0, 4.0)


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


@pytest.mark.spec("RUL-disagreeing_tracks_place_nothing", "BLD-track_placement",
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


@pytest.mark.spec("RUL-unplaced_photo_listed", test="TST-geotag_gps_placement-why_the_tracks_placed_nothing")
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
