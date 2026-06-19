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
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CFG = {"gpx_direct_match_max_seconds": 60.0, "gpx_interpolation_max_gap_seconds": 120.0,
       "gpx_interpolation_max_distance_meters": 1000.0, "gpx_interpolation_max_speed_kmh": 150.0,
       "gpx_extrapolation_max_seconds": 120.0}


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
    # just past 60 s and far from the next point in time -> not direct; here the pair is 1 h apart
    # (> max_gap) so it also fails interpolation -> blocked.
    assert cal.place_gps(_utc(12, 1, 1), g, CFG) is None


# --- interpolation -----------------------------------------------------------

def test_interpolation_midpoint():
    g = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.002, 12, 1, 40)])   # 100 s apart, ~140 m
    r = cal.place_gps(_utc(12, 0, 50), g, _cfg(gpx_direct_match_max_seconds=5.0))
    assert r["method"] == "interpolated" and r["lon"] == pytest.approx(4.001, abs=1e-6)  # ratio 0.5


def test_interpolation_each_gate_blocks():
    near = _cfg(gpx_direct_match_max_seconds=1.0)                    # force the interp path
    gap_fail = _gpx([_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.0001, 12, 5, 0)])    # 300 s > 120
    assert cal.place_gps(_utc(12, 2, 0), gap_fail, near) is None
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
