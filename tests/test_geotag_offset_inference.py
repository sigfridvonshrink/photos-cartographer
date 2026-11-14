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

"""Phase 3b (geotag) — GPX/native-GPS ranking clock-offset inference (spec §19).

GPS is correctness-critical, so the geometry/matching/ranking engine is tested at full branch
coverage: the pure helpers directly (point/segment matching, projection clamping, ranking,
conflict detection) plus the end-to-end offset cell (auto-resolution, accept, manual). From
conftest.py.
"""
from datetime import datetime, timedelta, timezone

import pytest
from _handoff import match_disk

import photos_2_geotag as cal
import photos_utils as utils

CFG = {"gpx_anchor_max_point_distance_meters": 30.0, "gpx_anchor_max_segment_distance_meters": 30.0,
       "gpx_anchor_max_segment_gap_seconds": 120.0, "gpx_anchor_offset_spread_max_seconds": 120.0,
       "gpx_anchor_same_pass_max_seconds": 120.0, "gpx_anchor_stay_max_seconds": 120.0,
       "gpx_anchor_stay_distance_meters": 6.0, "gpx_anchor_decision_tolerance_seconds": 120.0}
CAM = "SONY|ILCE-6400|123"


def _utc(h, m, s):
    return datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc)


def _pt(lat, lon, t, src="trip.gpx", i=0):
    return cal.GPXPoint(lat, lon, t, src, i)


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    return idx


def _frame(lat, lon, naive, rel="6-photos-by-dest/B/x.arw"):
    return {"native_gps": {"lat": lat, "lon": lon}, "source_naive_time": naive, "relative_path": rel}


# --- haversine + projection (pure geometry) ---------------------------------

def test_haversine_zero_and_known_arc():
    assert cal.haversine(50.0, 4.0, 50.0, 4.0) == 0.0
    assert cal.haversine(0.0, 0.0, 0.0, 0.001) == pytest.approx(111.19, abs=0.5)  # ~111 m/0.001deg


def test_point_to_segment_midpoint_and_clamping():
    # P beside the middle of a N-S segment -> t≈0.5
    d, t = cal._point_to_segment(0.0005, 0.0005, 0.0, 0.0, 0.0, 0.001)
    assert t == pytest.approx(0.5, abs=0.01) and d == pytest.approx(55.6, abs=1.0)
    # segment runs A=(0,0) -> B=(0, 0.001) along longitude; project past each end
    _, t0 = cal._point_to_segment(0.0, -0.001, 0.0, 0.0, 0.0, 0.001)   # west of A -> t clamped to 0
    assert t0 == 0.0
    _, t1 = cal._point_to_segment(0.0, 0.002, 0.0, 0.0, 0.0, 0.001)    # east of B -> t clamped to 1
    assert t1 == 1.0
    # zero-length segment -> distance to A, t=0
    dz, tz = cal._point_to_segment(0.0, 0.001, 0.0, 0.0, 0.0, 0.0)
    assert tz == 0.0 and dz == pytest.approx(111.2, abs=1.0)


def test_parse_helpers():
    assert cal._parse_camera_naive("2024:07:03 14:12:08") == datetime(2024, 7, 3, 14, 12, 8)
    assert cal._parse_camera_naive("garbage") is None and cal._parse_camera_naive(None) is None
    assert cal._parse_utc("2024-07-03T12:12:21Z").tzinfo is not None
    assert cal._parse_utc("nope") is None and cal._parse_utc(None) is None


# --- match_frame_to_gpx (every branch) --------------------------------------

def test_point_match_offset_sign():
    gpx = _gpx([_pt(50.8467, 4.3525, _utc(12, 12, 21))])
    c = cal.match_frame_to_gpx(_frame(50.8467, 4.3525, "2024:07:03 14:12:08"), gpx, CFG)
    assert c["match_type"] == "gpx_point_match" and c["offset_seconds"] == -7187   # camera ahead
    # camera behind -> positive offset
    c2 = cal.match_frame_to_gpx(_frame(50.8467, 4.3525, "2024:07:03 12:12:00"), gpx, CFG)
    assert c2["offset_seconds"] == 21


@pytest.mark.spec("BLD-anchor_matching")
def test_point_just_past_threshold_then_segment_or_none():
    far = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(50.0, 4.001, _utc(12, 0, 30))])
    # a frame ~111 m from both points (beyond 30 m) but the segment between them is far too ->
    frame = _frame(50.001, 4.0005, "2024:07:03 14:00:00")
    assert cal.match_frame_to_gpx(frame, far, CFG) is None                        # nothing within 30 m


def test_segment_match_interpolates_time():
    # two points 30 s apart along a line; frame beside the midpoint (within 30 m) -> ~t=0.5
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(50.0, 4.001, _utc(12, 0, 30))])
    c = cal.match_frame_to_gpx(_frame(50.0001, 4.0005, "2024:07:03 14:00:15"), gpx, CFG)
    assert c["match_type"] == "gpx_segment_interpolation"
    assert c["offset_seconds"] == pytest.approx(-7200, abs=2)                     # ~14:00:15 -> 12:00:15


def test_segment_rejected_when_gap_too_large():
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(50.0, 4.001, _utc(12, 5, 0))])  # 300 s > 120 s cap
    assert cal.match_frame_to_gpx(_frame(50.0001, 4.0005, "2024:07:03 14:00:00"), gpx, CFG) is None


def test_match_none_branches():
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    assert cal.match_frame_to_gpx({"native_gps": None, "source_naive_time": "x"}, gpx, CFG) is None
    assert cal.match_frame_to_gpx(_frame(50.0, 4.0, "garbage"), gpx, CFG) is None          # unparseable time
    assert cal.match_frame_to_gpx(_frame(50.0, 4.0, "2024:07:03 12:00:00"), _gpx([]), CFG) is None  # empty gpx


def test_point_preferred_over_closer_segment():
    # an exact-position point (dist 0) plus a segment the frame is even "on" -> point wins
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(50.0, 4.001, _utc(12, 0, 30))])
    c = cal.match_frame_to_gpx(_frame(50.0, 4.0, "2024:07:03 14:00:00"), gpx, CFG)
    assert c["match_type"] == "gpx_point_match"


# --- infer_anchor_proposal (ranking / supporting / conflicting) -------------

def test_proposal_single_point_high():
    gpx = _gpx([_pt(50.8467, 4.3525, _utc(12, 12, 21))])
    p = cal.infer_anchor_proposal([_frame(50.8467, 4.3525, "2024:07:03 14:12:08")], gpx, CFG)
    assert p["proposed_offset_seconds"] == -7187 and p["confidence"] == "high"
    assert p["proposal_source"] == "gpx_self_anchor" and p["anchor_count"] == 1


def test_proposal_two_consistent_supporting():
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(51.0, 5.0, _utc(13, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/a.arw"),
              _frame(51.0, 5.0, "2024:07:03 15:00:02", "6-photos-by-dest/B/b.arw")]  # ~same offset
    p = cal.infer_anchor_proposal(frames, gpx, CFG)
    assert p["anchor_count"] == 2 and p["supporting_count"] == 1 and p["conflicting_count"] == 0
    assert p["confidence"] == "high"


def test_proposal_conflict_review_required():
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(51.0, 5.0, _utc(9, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/a.arw"),    # offset -7200
              _frame(51.0, 5.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/b.arw")]    # offset -18000
    p = cal.infer_anchor_proposal(frames, gpx, CFG)
    assert p["conflicting_count"] == 1 and p["confidence"] == "review_required"


def test_proposal_segment_only_medium_and_none():
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(50.0, 4.001, _utc(12, 0, 30))])
    p = cal.infer_anchor_proposal([_frame(50.0001, 4.0005, "2024:07:03 14:00:15")], gpx, CFG)
    assert p["recommended_gpx_match"]["match_type"] == "gpx_segment_interpolation" and p["confidence"] == "medium"
    assert cal.infer_anchor_proposal([], gpx, CFG) is None                          # nothing anchors


def test_proposal_skips_unmatched_frames():
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00"),           # matches the point
              _frame(60.0, 10.0, "2024:07:03 14:00:00")]          # far away -> no match (skipped)
    p = cal.infer_anchor_proposal(frames, gpx, CFG)
    assert p["anchor_count"] == 1


# --- plausible-clock-error window + consensus + groups/skipped (§19.1/§19.3) -

WCFG = dict(CFG, gpx_anchor_max_clock_error_seconds=172800.0)   # 2-day window


@pytest.mark.spec("RUL-anchor_within_clock_error", test="TST-geotag_offset_inference-window_rejects_same_place_other_year")
def test_window_rejects_same_place_other_year():
    # the SAME spot has a point this trip and one 13 years earlier; the old one would win on distance
    # (a tie at 0 m, listed first) but is out of the window, so the recent point anchors instead.
    gpx = _gpx([_pt(50.0, 4.0, datetime(2011, 7, 3, 12, 0, 0, tzinfo=timezone.utc)),
                _pt(50.0, 4.0, _utc(12, 0, 0))])
    c = cal.match_frame_to_gpx(_frame(50.0, 4.0, "2024:07:03 14:00:00"), gpx, WCFG)
    assert c is not None and c["offset_seconds"] == -7200        # 2024 point, not a ~13-year "offset"


@pytest.mark.spec("RUL-anchor_within_clock_error", test="TST-geotag_offset_inference-clock_error_window_is_timezone_independent")
def test_clock_error_window_is_timezone_independent():
    """§19.1: the clock-error matching window reads the frame's naive time AS UTC; the destination
    timezone is never used to bound matching. The matcher takes no timezone, and decorating the frame
    + cfg with a destination timezone leaves the match identical. Discriminating: the window is tight
    (3h) so if the naive time were re-read through a destination tz (Tokyo +9 / Honolulu -10, hours
    off) the GPX point would fall outside the window and the match would vanish — it does not."""
    import inspect
    tight = dict(CFG, gpx_anchor_max_clock_error_seconds=10800.0)        # 3h window
    gpx_pts = [_pt(50.0, 4.0, _utc(12, 0, 0))]
    # frame naive 14:00 read as UTC is 2h from the 12:00Z point -> inside the 3h window.
    tokyo = dict(_frame(50.0, 4.0, "2024:07:03 14:00:00"), destination_timezone="Asia/Tokyo")
    honolulu = dict(_frame(50.0, 4.0, "2024:07:03 14:00:00"), destination_timezone="Pacific/Honolulu")
    c_tok = cal.match_frame_to_gpx(tokyo, _gpx(list(gpx_pts)), dict(tight, default_folder_timezone="Asia/Tokyo"))
    c_hon = cal.match_frame_to_gpx(honolulu, _gpx(list(gpx_pts)), dict(tight, default_folder_timezone="Pacific/Honolulu"))
    assert c_tok is not None and c_hon == c_tok                          # same match regardless of dest tz
    assert c_tok["offset_seconds"] == -7200                              # 12:00Z - 14:00 naive, no tz shift
    # the matcher's signature carries no timezone parameter at all
    params = inspect.signature(cal.match_frame_to_gpx).parameters
    assert "tz" not in params and "timezone" not in params


def test_window_out_of_window_is_skipped_with_reason():
    gpx = _gpx([_pt(50.0, 4.0, datetime(2011, 7, 3, 12, 0, 0, tzinfo=timezone.utc))])   # only the old point
    frame = _frame(50.0, 4.0, "2024:07:03 14:00:00")
    assert cal.match_frame_to_gpx(frame, gpx, WCFG) is None
    assert cal._frame_skip_reason(frame, gpx, WCFG) == "outside_time_window"   # spatially close, wrong time
    far = _frame(60.0, 10.0, "2024:07:03 14:00:00")
    assert cal._frame_skip_reason(far, gpx, WCFG) == "no_nearby_track"


@pytest.mark.spec("RUL-anchor_consensus", test="TST-geotag_offset_inference-consensus_majority_beats_closer_minority")
def test_consensus_majority_beats_closer_minority():
    # three frames agree on +3600; a fourth exact match says 0 -> the crowd wins, the loner conflicts
    gpx = _gpx([_pt(50.0, 4.0, _utc(15, 0, 0)), _pt(51.0, 5.0, _utc(15, 0, 0)),
                _pt(52.0, 6.0, _utc(15, 0, 0)), _pt(53.0, 7.0, _utc(14, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/a.arw"),
              _frame(51.0, 5.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/b.arw"),
              _frame(52.0, 6.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/c.arw"),
              _frame(53.0, 7.0, "2024:07:03 14:00:00", "6-photos-by-dest/B/d.arw")]
    p = cal.infer_anchor_proposal(frames, gpx, WCFG)
    assert p["proposed_offset_seconds"] == 3600 and p["conflicting_count"] == 1
    assert [g["count"] for g in p["groups"]] == [3, 1]            # sorted by count desc
    assert p["groups"][0]["offset_seconds"] == 3600
    assert p["anchors"][0]["proposed_offset_seconds"] == 3600     # anchors[0] is the consensus rep


def test_groups_carry_full_path_and_local_inputs_plus_skipped():
    gpx = _gpx([_pt(50.0, 4.0, _utc(15, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "6-photos-by-dest/Japan/Kyoto/keep.arw"),
              _frame(60.0, 10.0, "2024:07:03 14:00:00", "6-photos-by-dest/Japan/Kyoto/faraway.arw")]
    p = cal.infer_anchor_proposal(frames, gpx, WCFG)
    rep = p["groups"][0]["representative"]
    assert rep["source_file"] == "6-photos-by-dest/Japan/Kyoto/keep.arw"   # full by-dest relative path
    assert rep["real_utc"] == "2024-07-03T15:00:00Z" and rep["camera_source_naive_time"] == "2024:07:03 14:00:00"
    assert p["skipped"]["no_nearby_track"] == 1
    assert p["skipped"]["examples"][0]["source_file"] == "6-photos-by-dest/Japan/Kyoto/faraway.arw"


# --- offset cell: auto-resolution / accept / manual (end-to-end) ------------

def _cell(prior_ud, frames, gpx, *, multi=True, single=False):
    wf = cal.GeotagWorkflow("/tmp")
    utils.CONFIG.update(CFG)
    utils.CONFIG["camera_time_and_timezone_policy"]["multi_anchor_auto_apply"] = multi
    utils.CONFIG["camera_time_and_timezone_policy"]["single_anchor_auto_apply"] = single
    blockers = []
    cell = wf._offset_cell("6-photos-by-dest/B", "K", {"camera_group_class": "camera"},
                           {"user_decision": prior_ud}, frames, gpx, blockers)
    return cell, blockers


GPX1 = None


def test_cell_multi_anchor_auto_resolves(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(51.0, 5.0, _utc(13, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00"), _frame(51.0, 5.0, "2024:07:03 15:00:02")]
    cell, _ = _cell({}, frames, gpx, multi=True)
    assert cell["decision_mode"] == "auto_resolved" and cell["requires_user_input"] is False
    assert cell["effective_time_anchor"]["source"] == "gpx_anchor_auto"


@pytest.mark.spec("RUL-anchor_offset_auto_as_configured", test="TST-geotag_offset_inference-cell_single_anchor_conservative_then_flag")
def test_cell_single_anchor_conservative_then_flag(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({}, frames, gpx, single=False)
    assert cell["requires_user_input"] is True and "decision_mode" not in cell
    cell2, _ = _cell({}, frames, gpx, single=True)
    assert cell2["requires_user_input"] is False and cell2["decision_mode"] == "auto_resolved"


@pytest.mark.spec("BLD-anchor_matching", "RUL-anchor_offset_auto_as_configured", test="TST-geotag_offset_inference-cell_conflict_requires_input_even_with_autoapply")
def test_cell_conflict_requires_input_even_with_autoapply(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(51.0, 5.0, _utc(9, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00"), _frame(51.0, 5.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({}, frames, gpx, multi=True)
    assert cell["requires_user_input"] is True and cell["proposal"]["confidence"] == "review_required"


def test_cell_accept_proposal(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({"accept_proposal": True, "accepted_offset_seconds": -7200}, frames, gpx, single=False)
    assert cell["effective_time_anchor"]["source"] == "gpx_anchor_accepted"
    assert cell["effective_time_anchor"]["offset_seconds"] == -7200


def test_cell_manual_offset_and_bad_offset(monkeypatch):
    gpx = _gpx([])
    cell, _ = _cell({"manual_offset_seconds": -7187}, [], gpx)
    assert cell["effective_time_anchor"] == {"offset_seconds": -7187, "source": "manual"}
    bad, blk = _cell({"manual_offset_seconds": "x"}, [], gpx)
    assert blk and bad["effective_time_anchor"] == ""


@pytest.mark.spec("RUL-timezone_auto_resolves")
def test_cell_no_anchor_is_manual_required(monkeypatch):
    cell, _ = _cell({}, [], _gpx([]))
    assert cell["proposal"] == {"proposal_source": "manual_required"} and cell["requires_user_input"]


def test_cell_accept_with_no_proposal_is_stale(monkeypatch):
    cell, _ = _cell({"accept_proposal": True, "accepted_offset_seconds": -7200}, [], _gpx([]))      # manual_required -> nothing to accept
    assert cell["stale_user_decision"] is True and cell["requires_user_input"] is True
    _, blk = _cell({"accept_proposal": True}, [], _gpx([]))        # an acceptance naming no offset accepts nothing
    assert blk and "accepted_offset_seconds" in blk[0]


def test_config_anchor_thresholds_reject_negative():
    with pytest.raises(ValueError, match="gpx_anchor_max_point_distance_meters"):
        utils.validate_config({"gpx_anchor_max_point_distance_meters": -1})


# --- end-to-end: GPX anchor flows through `run` into photos-21 ----------------

def test_run_auto_resolves_offset_from_gpx(tmp_path, monkeypatch):
    import json, os, sys
    MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
               "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx_dir = tmp_path / "gpx"; gpx_dir.mkdir()
    (gpx_dir / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.8467" lon="4.3525"><time>2024-07-03T12:12:21Z</time></trkpt>'
        '<trkpt lat="50.8480" lon="4.3540"><time>2024-07-03T12:13:21Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx_dir)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))

    def rec(rel, lat, lon, dto):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon}
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": 1, "mtime_ns": 1, "content_hash": json.dumps({"value": "fp" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/B/a.arw", 50.8467, 4.3525, "2024:07:03 14:12:08"),
             rec("6-photos-by-dest/B/b.arw", 50.8480, 4.3540, "2024:07:03 14:13:08")]
    for f in files:
        p = ws / f["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files)}))

    CAM_CFG = CAM
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
    except SystemExit as e:
        assert e.code in (0, None)
    art = json.load(open(ctl / "photos-21-time-decisions.json"))
    cell = art["destinations"]["6-photos-by-dest/B"]["camera_group_time_decisions"][CAM_CFG]
    assert cell["proposal"]["proposal_source"] == "gpx_self_anchor"
    assert cell["proposal"]["proposed_offset_seconds"] == -7187
    assert cell["decision_mode"] == "auto_resolved"                    # two consistent anchors
    assert cell["effective_time_anchor"]["offset_seconds"] == -7187


# --- timezone-derived offset proposal (no anchor, no inherited) — §19.4 -------

def _tzcell(prior_ud, *, tz, rep_naive, frames=None, date=None):
    wf = cal.GeotagWorkflow("/tmp")
    utils.CONFIG.update(CFG)
    blockers = []
    cell = wf._offset_cell("6-photos-by-dest/B", "K", {"camera_group_class": "camera"},
                           {"user_decision": prior_ud}, frames or [], _gpx([]), blockers,
                           tz=tz, rep_naive=rep_naive, date=date)
    return cell, blockers


@pytest.mark.spec("BLD-timezone_naive_offset")
def test_timezone_naive_offset_is_dst_aware():
    assert cal._timezone_naive_offset("2024:07:03 14:00:00", "Europe/Brussels")[0] == -7200   # summer +2
    assert cal._timezone_naive_offset("2024:01:03 14:00:00", "Europe/Brussels")[0] == -3600   # winter +1
    assert cal._timezone_naive_offset("2024:07:03 14:00:00", "Asia/Tokyo")[0] == -32400        # +9, no DST
    off, real = cal._timezone_naive_offset("2024:07:03 14:00:00", "Europe/Brussels")
    assert off == -7200 and real == "2024-07-03T12:00:00Z"
    for bad in [("2024:07:03 14:00:00", "Bogus/Zone"), ("garbage", "UTC"), ("2024:07:03 14:00:00", "")]:
        assert cal._timezone_naive_offset(*bad) is None


@pytest.mark.spec("RUL-offset_from_own_evidence", "BLD-timezone_naive_offset", "RUL-other_proposals_need_acceptance", test="TST-geotag_offset_inference-cell_timezone_derived_when_no_anchor")
def test_cell_timezone_derived_when_no_anchor():
    cell, _ = _tzcell({}, tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00")
    p = cell["proposal"]
    assert p["proposal_source"] == "timezone_naive" and p["proposed_offset_seconds"] == -7200
    assert p["proposed_real_utc"] == "2024-07-03T12:00:00Z" and p["proposed_from_timezone"] == "Europe/Brussels"
    assert p["confidence"] == "review_required"
    assert cell["requires_user_input"] is True and "decision_mode" not in cell   # confirmable, never auto


def test_cell_records_its_date_bucket():
    cell, _ = _tzcell({}, tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00", date="2024-07-03")
    assert cell["date"] == "2024-07-03"                       # per-day bucket stamps its naive date
    bare, _ = _tzcell({}, tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00")
    assert "date" not in bare                                 # single-date common case: bare group key, no date


def test_cell_accept_timezone_derived_resolves():
    cell, _ = _tzcell({"accept_proposal": True, "accepted_offset_seconds": -7200}, tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00")
    assert cell["effective_time_anchor"] == {"offset_seconds": -7200, "source": "timezone_accepted"}
    assert cell["requires_user_input"] is False


def test_cell_no_timezone_is_manual_required():
    cell, _ = _tzcell({}, tz=None, rep_naive="2024:07:03 14:00:00")
    assert cell["proposal"] == {"proposal_source": "manual_required"}


# --- the same place on several passes: consecutive days, repeated visits ------------------------

def _route_days(days, extra=()):
    """The same walk through Bruges on each of `days` (July), one point every 10 min from 09:00 UTC, the
    first day's track a hair closer to the photo spots; plus `extra` (day, lat, lon, minute) points."""
    route = [(51.2080 + i * 0.0005, 3.2240 + i * 0.0005) for i in range(10)]
    pts = []
    for n, day in enumerate(days):
        nudge = 0.00001 if n == 0 else 0.00004
        for i, (la, lo) in enumerate(route):
            pts.append(_pt(la + nudge, lo, datetime(2024, 7, day, 9, 10 * i, tzinfo=timezone.utc) if i < 6
                           else datetime(2024, 7, day, 10, 10 * (i - 6), tzinfo=timezone.utc), f"day{day}.gpx", i))
    for day, la, lo, minute in extra:
        pts.append(_pt(la, lo, datetime(2024, 7, day, 11, minute, tzinfo=timezone.utc), f"day{day}.gpx", 99))
    return route, _gpx(sorted(pts, key=lambda p: p.time_utc))


def _photo(lat, lon, real_utc, i):
    cam = real_utc.replace(tzinfo=None) + timedelta(hours=2)        # camera on local time: offset -7200
    return _frame(lat, lon, cam.strftime("%Y:%m:%d %H:%M:%S"), rel=f"6-photos-by-dest/Bruges/p{i}.jpg")


@pytest.mark.spec("RUL-anchor_consensus", "RUL-revisit_matched_to_its_day", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-each_pass_by_a_place_is_a_candidate")
def test_each_pass_by_a_place_is_a_candidate():
    route, gpx = _route_days([3, 4])
    f = _photo(*route[2], datetime(2024, 7, 4, 9, 20, tzinfo=timezone.utc), 2)
    cands = cal.frame_candidates(f, gpx, WCFG)
    assert [c["gpx_file"] for c in cands] == ["day3.gpx", "day4.gpx"]        # one per visit, in time order
    assert [c["offset_seconds"] for c in cands] == [-7200 - 86400, -7200]
    assert cal.match_frame_to_gpx(f, gpx, WCFG)["gpx_file"] == "day3.gpx"   # the closest alone: the wrong day


@pytest.mark.spec("RUL-anchor_consensus", "RUL-revisit_matched_to_its_day", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-a_place_walked_on_two_days_takes_the_photos_day")
def test_a_place_walked_on_two_days_takes_the_photos_day():
    # Photos of 4 July along a route also walked on 3 July — whose track passes closer — plus one spot only
    # the 4 July track knows: every photo supports the 4 July offset, so it wins outright and applies itself.
    route, gpx = _route_days([3, 4], extra=[(4, 51.2200, 3.2400, 0)])
    frames = [_photo(*route[i], datetime(2024, 7, 4, 9, 10 * i, tzinfo=timezone.utc), i) for i in (1, 3, 5)]
    frames.append(_photo(51.2200, 3.2400, datetime(2024, 7, 4, 11, 0, tzinfo=timezone.utc), 9))
    p = cal.infer_anchor_proposal(frames, gpx, WCFG)
    assert p["proposed_offset_seconds"] == -7200 and p["confidence"] == "high"
    assert p["tied"] is False and p["conflicting_count"] == 0 and p["supporting_count"] == 3
    assert {a["gpx_match"]["gpx_file"] for a in p["anchors"]} == {"day4.gpx"}
    assert [g["count"] for g in p["groups"]] == [4, 3]                      # 4 July: all four; 3 July: three


@pytest.mark.spec("RUL-anchor_consensus", "RUL-indistinct_visits_wait", "RUL-anchor_offset_auto_as_configured", "BLD-anchor_matching", test="TST-geotag_offset_inference-two_days_nothing_tells_apart_wait_for_review")
def test_two_days_nothing_tells_apart_wait_for_review(monkeypatch):
    # The same route on two days and no photo only one day explains: the smaller clock error is proposed,
    # but as a disagreement — it never applies itself.
    route, gpx = _route_days([3, 4])
    frames = [_photo(*route[i], datetime(2024, 7, 4, 9, 10 * i, tzinfo=timezone.utc), i) for i in (1, 3, 5)]
    p = cal.infer_anchor_proposal(frames, gpx, WCFG)
    assert p["proposed_offset_seconds"] == -7200 and p["tied"] is True and p["confidence"] == "review_required"
    cell, _ = _cell({}, frames, gpx, multi=True)
    assert cell["requires_user_input"] is True and cell["effective_time_anchor"] == ""


@pytest.mark.spec("RUL-chosen_group_is_anchored", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-a_picked_group_counts_as_gps_backed")
def test_a_picked_group_counts_as_gps_backed(monkeypatch):
    # On a tie the user picks the other day's group: its offset is anchored by the camera's GPS like an accepted
    # proposal (no drift check follows); an offset no group supports stays a manual one.
    route, gpx = _route_days([3, 4])
    frames = [_photo(*route[i], datetime(2024, 7, 4, 9, 10 * i, tzinfo=timezone.utc), i) for i in (1, 3, 5)]
    p = cal.infer_anchor_proposal(frames, gpx, WCFG)
    assert [(g["offset_seconds"], g["representative"]["gpx_file"]) for g in p["groups"]] == \
        [(-7200, "day4.gpx"), (-93600, "day3.gpx")]                          # each group names its track
    other, _ = _cell({"manual_offset_seconds": -93600}, frames, gpx)
    assert other["effective_time_anchor"] == {"offset_seconds": -93600, "source": "gpx_anchor_chosen"}
    near, _ = _cell({"manual_offset_seconds": -7200 + 60}, frames, gpx)       # within the spread: that group
    assert near["effective_time_anchor"]["source"] == "gpx_anchor_chosen"
    own, _ = _cell({"manual_offset_seconds": -3600}, frames, gpx)
    assert own["effective_time_anchor"] == {"offset_seconds": -3600, "source": "manual"}
    assert "gpx_anchor_chosen" not in cal.GeotagWorkflow._DRIFT_TRIGGER_SOURCES


@pytest.mark.spec("BLD-anchor_matching", "RUL-anchor_proposal_carries_evidence", test="TST-geotag_offset_inference-conflicting_photos_are_named")
def test_conflicting_photos_are_named():
    # Photos that support no pass of the agreed offset are named, so the user can tell scattered bad positions
    # from a clock changed during the day.
    route, gpx = _route_days([4], extra=[(4, 51.2300, 3.2500, 30)])
    frames = [_photo(*route[i], datetime(2024, 7, 4, 9, 10 * i, tzinfo=timezone.utc), i) for i in (1, 3, 5)]
    frames.append(_photo(51.2300, 3.2500, datetime(2024, 7, 4, 15, 0, tzinfo=timezone.utc), 8))  # clock off by 3.5 h
    p = cal.infer_anchor_proposal(frames, gpx, WCFG)
    assert p["proposed_offset_seconds"] == -7200 and p["conflicting_count"] == 1
    assert p["conflicting_files"] == ["6-photos-by-dest/Bruges/p8.jpg"] and p["confidence"] == "review_required"


# --- what a place can and cannot say about the time (§19.1) -------------------------------------------

M = 1 / 111320.0            # one metre of latitude, in degrees
BASE = datetime(2024, 7, 3, 10, 0, 0, tzinfo=timezone.utc)
DCFG = dict(utils.DEFAULT_CONFIG)


def _at(seconds):
    return BASE + timedelta(seconds=seconds)


def _naive(seconds):
    return _at(seconds).strftime("%Y:%m:%d %H:%M:%S")


@pytest.mark.spec("RUL-stay_fixes_no_clock", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-a_stay_of_the_tracks_fixes_no_clock")
def test_a_stay_of_the_tracks_fixes_no_clock(monkeypatch):
    """The tracks stood an hour at the place two photos were taken (a museum, a lunch): the place says the
    photos were taken some time in that hour, not when. The offset proposed is one that fits, marked as
    no reading — never applied by itself — and a third photo taken on the move fixes it."""
    stay = [_pt(50.0 + (i % 3 - 1) * 4 * M, 4.0, _at(i * 5), i=i) for i in range(720)]      # 60 min, jittering
    still = [_frame(50.0, 4.0, _naive(3000), "a"), _frame(50.0, 4.0, _naive(3004), "b")]    # clock exactly UTC
    p = cal.infer_anchor_proposal(still, _gpx(stay), DCFG)
    assert p["imprecise_seconds"] >= 3000 and p["confidence"] == "review_required"
    utils.CONFIG.update(DCFG)
    wf, blk = cal.GeotagWorkflow("/tmp"), []
    cell = wf._offset_cell("6-photos-by-dest/B", "K", {"camera_group_class": "camera"}, {}, still, _gpx(stay), blk)
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"]     # two anchors, yet not auto
    ud = {"accept_proposal": True, "accepted_offset_seconds": p["proposed_offset_seconds"]}
    cell = wf._offset_cell("6-photos-by-dest/B", "K", {"camera_group_class": "camera"}, {"user_decision": ud},
                           still, _gpx(stay), blk)
    assert cell["effective_time_anchor"]["source"] == "gpx_anchor_imprecise" and not blk
    assert "gpx_anchor_imprecise" in cal.GeotagWorkflow._DRIFT_TRIGGER_SOURCES      # ...and is checked on the track
    # the walk away from the place: a photo on it says when, and the stay's photos agree with it
    walk = [_pt(50.0 + (i + 1) * 7 * M, 4.0, _at(3600 + (i + 1) * 5), i=1000 + i) for i in range(120)]
    moving = _frame(50.0 + 60 * 7 * M, 4.0, _naive(3600 + 60 * 5), "c")
    p = cal.infer_anchor_proposal(still + [moving], _gpx(stay + walk), DCFG)
    assert (p["proposed_offset_seconds"], p["imprecise_seconds"], p["confidence"]) == (0, 0, "high")
    assert p["conflicting_count"] == 0 and p["anchor_count"] == 3


@pytest.mark.spec("RUL-revisit_matched_to_its_day", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-out_and_back_is_two_passes")
def test_a_walk_out_and_back_is_two_passes():
    """A path walked out and back within the half hour: each leg is a pass of its own, so a photo on the way
    back is not timed by the way out because that leg's track ran a metre closer."""
    out = [_pt(50.0 + t * 1.4 * M, 4.0, _at(t), i=t) for t in range(0, 600, 5)]
    back = [_pt(50.0 + (1200 - t) * 1.4 * M, 4.0 + 3 * M, _at(t), i=t) for t in range(600, 1200, 5)]
    on_the_way_back = _frame(50.0 + 300 * 1.4 * M, 4.0 + 1 * M, _naive(900))     # nearer the outbound line
    cands = cal.frame_candidates(on_the_way_back, _gpx(out + back), DCFG)
    assert [c["offset_seconds"] for c in cands] == [-600, 0]                    # both legs offered
    later = _frame(50.0 + 200 * 1.4 * M, 4.0 + 1 * M, _naive(1000), "b")
    p = cal.infer_anchor_proposal([on_the_way_back, later], _gpx(out + back), DCFG)
    assert p["proposed_offset_seconds"] == 0 and not p["tied"]                  # the leg both photos agree on


@pytest.mark.spec("BLD-anchor_matching", test="TST-geotag_offset_inference-an_anchor_is_on_one_track")
def test_an_anchor_never_spans_two_tracks():
    """Two people 220 m either side of a photo's place: no segment joins a point of one track to a point of the
    other, so the photo anchors on neither."""
    a = [_pt(50.0, 4.0 - 0.003, _at(t), "a.gpx", t) for t in range(0, 100, 10)]
    b = [_pt(50.0, 4.0 + 0.003, _at(t + 5), "b.gpx", t) for t in range(0, 100, 10)]
    assert cal.frame_candidates(_frame(50.0, 4.0, _naive(50)), _gpx(a + b), DCFG) == []


@pytest.mark.spec("RUL-acceptance_holds_for_its_proposal", "BLD-offset_acceptance",
                  test="TST-geotag_offset_inference-an_acceptance_holds_for_the_proposal_it_accepted")
def test_an_acceptance_holds_only_for_the_proposal_it_accepted():
    """The user accepted "the camera was on local time" (−2 h). Then the zone above changed, or photos with
    GPS arrived that say otherwise: what is proposed now was never accepted, so it asks — the answer kept as
    written, applied to nothing."""
    accepted = {"accept_proposal": True, "accepted_offset_seconds": -7200}
    cell, blk = _tzcell(accepted, tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00")
    assert cell["effective_time_anchor"] == {"offset_seconds": -7200, "source": "timezone_accepted"} and not blk
    cell, blk = _tzcell(accepted, tz="Asia/Tokyo", rep_naive="2024:07:03 14:00:00")       # the zone changed
    assert cell["effective_time_anchor"] == "" and cell["stale_user_decision"] and cell["requires_user_input"]
    assert cell["user_decision"]["accepted_offset_seconds"] == -7200 and not blk          # kept as written
    # photos with their own GPS arrive, anchoring an hour off what was accepted
    gpx = _gpx([_pt(50.0, 4.0, _utc(13, 0, 0)), _pt(50.001, 4.0, _utc(13, 5, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "a"), _frame(50.001, 4.0, "2024:07:03 14:05:00", "b")]
    cell, _ = _cell(accepted, frames, gpx)
    assert cell["proposal"]["proposed_offset_seconds"] == -3600
    assert cell["effective_time_anchor"] == "" and cell["stale_user_decision"]
    # a GPS proposal a few seconds from the one accepted is the same finding
    cell, _ = _cell({"accept_proposal": True, "accepted_offset_seconds": -3590}, frames, gpx, multi=False)
    assert cell["effective_time_anchor"] == {"offset_seconds": -3600, "source": "gpx_anchor_accepted"}


@pytest.mark.spec("RUL-written_value_over_acceptance", test="TST-geotag_offset_inference-a_written_offset_outranks_an_acceptance")
def test_a_written_offset_outranks_an_acceptance():
    cell, _ = _tzcell({"accept_proposal": True, "accepted_offset_seconds": -7200, "manual_offset_seconds": -60},
                      tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00")
    assert cell["effective_time_anchor"] == {"offset_seconds": -60, "source": "manual"}


@pytest.mark.spec("RUL-kept_offset_rests_on_its_tracks", "RUL-anchor_offset_auto_as_configured", "BLD-day_offset_kept",
                  test="TST-geotag_offset_inference-a_kept_offset_rests_on_its_tracks")
def test_a_kept_offset_rests_on_what_it_was_found_from():
    """An offset found from the camera's GPS is kept for later photos of the day only while the tracks it was
    found from are there unchanged and no photo that arrived since says otherwise."""
    utils.CONFIG.update(CFG)
    wf, g = cal.GeotagWorkflow("/tmp"), {"camera_group_class": "camera"}
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(50.001, 4.0, _utc(12, 5, 0))])
    gpx.file_sha = {"trip.gpx": "sha-1"}
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "a"), _frame(50.001, 4.0, "2024:07:03 14:05:00", "b")]
    first = wf._offset_cell("D", "K", g, {}, frames, gpx, [])
    assert first["effective_time_anchor"]["source"] == "gpx_anchor_auto"
    assert first["anchored_by"] == [{"gpx_file": "trip.gpx", "sha256": "sha-1"}]
    # its photos corrected, a later one with no GPS: kept
    kept = wf._offset_cell("D", "K", g, first, [], gpx, [])
    assert kept["decision_mode"] == "kept_from_earlier" and kept["effective_time_anchor"]["offset_seconds"] == -7200
    assert kept["anchored_by"] == first["anchored_by"]                 # ...and still says what it rests on
    again = wf._offset_cell("D", "K", g, kept, [], gpx, [])
    assert again["decision_mode"] == "kept_from_earlier"
    # the track taken out of gpx_root (another person's, say), or changed: what it rested on is gone — it asks
    gone = _gpx([]); gone.file_sha = {}
    assert wf._offset_cell("D", "K", g, kept, [], gone, [])["requires_user_input"]
    changed = _gpx(gpx.points); changed.file_sha = {"trip.gpx": "sha-2"}
    assert wf._offset_cell("D", "K", g, kept, [], changed, [])["requires_user_input"]
    # a photo arrives whose own GPS puts the clock an hour elsewhere (one anchor: not applied by itself)
    other = [_frame(50.0, 4.0, "2024:07:03 13:00:00", "c")]
    cell = wf._offset_cell("D", "K", g, kept, other, gpx, [])
    assert cell["proposal"]["proposed_offset_seconds"] == -3600 and cell["requires_user_input"]
    # ...while one that agrees leaves it kept
    same = [_frame(50.0, 4.0, "2024:07:03 14:00:05", "d")]
    assert wf._offset_cell("D", "K", g, kept, same, gpx, [])["decision_mode"] == "kept_from_earlier"


# --- each setting bounds one thing --------------------------------------------------------------------------

@pytest.mark.spec("RUL-setting_bounds_one_thing", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-what_is_one_pass_is_its_own_setting")
def test_what_is_one_pass_is_its_own_setting():
    """How soon a track must be back to have passed a place once is not how close offsets must be to agree."""
    out = [_pt(50.0 + t * 1.4 * M, 4.0, _at(t), i=t) for t in range(0, 600, 5)]
    back = [_pt(50.0 + (1200 - t) * 1.4 * M, 4.0 + 3 * M, _at(t), i=t) for t in range(600, 1200, 5)]
    frame = _frame(50.0 + 300 * 1.4 * M, 4.0 + 1 * M, _naive(900))
    two = lambda cfg: len(cal.frame_candidates(frame, _gpx(out + back), cfg))
    assert two(DCFG) == 2
    assert two({**DCFG, "gpx_anchor_offset_spread_max_seconds": 3600.0}) == 2
    assert two({**DCFG, "gpx_anchor_same_pass_max_seconds": 3600.0}) == 1


@pytest.mark.spec("RUL-setting_bounds_one_thing", "RUL-stay_fixes_no_clock", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-how_long_a_stay_is_imprecise_is_its_own_setting")
def test_how_long_a_stay_is_imprecise_is_its_own_setting():
    """How long, and how near, a track must stay for its anchor to be imprecise are settings of their own."""
    stay = [_pt(50.0 + (i % 3 - 1) * 4 * M, 4.0, _at(i * 5), i=i) for i in range(720)]      # 60 min, ±4 m
    still = [_frame(50.0, 4.0, _naive(3000), "a"), _frame(50.0, 4.0, _naive(3004), "b")]
    imprecise = lambda cfg: cal.infer_anchor_proposal(still, _gpx(stay), cfg)["imprecise_seconds"]
    assert imprecise(DCFG) >= 3000
    assert imprecise({**DCFG, "gpx_anchor_offset_spread_max_seconds": 7200.0}) >= 3000
    assert imprecise({**DCFG, "gpx_anchor_same_pass_max_seconds": 7200.0}) >= 3000
    assert imprecise({**DCFG, "gpx_anchor_max_point_distance_meters": 500.0}) >= 3000
    assert imprecise({**DCFG, "gpx_anchor_stay_max_seconds": 7200.0}) == 0
    # a track 8 m off for the hour but for half a minute at the very place: how near counts as staying
    by = [_pt(50.0 + (0 if 590 <= i < 596 else 8) * M, 4.0, _at(i * 5), i=i) for i in range(720)]
    near = lambda cfg: cal.infer_anchor_proposal(still[:1], _gpx(by), cfg)["imprecise_seconds"]
    assert near(DCFG) >= 3000
    assert near({**DCFG, "gpx_anchor_max_point_distance_meters": 500.0}) >= 3000
    assert near({**DCFG, "gpx_anchor_stay_distance_meters": 2.0}) == 0


@pytest.mark.spec("RUL-setting_bounds_one_thing", "BLD-anchor_matching",
                  test="TST-geotag_offset_inference-the_segment_gap_is_its_own_setting")
def test_the_gap_a_segment_may_anchor_across_is_its_own_setting():
    """A frame beside a segment anchors on it while the segment's two points are no farther apart in time
    than the anchor's own gap setting — whatever gap a photo may be placed across."""
    seg = [_pt(50.0, 4.0, _at(0)), _pt(50.0 + 400 * M, 4.0, _at(300))]
    beside = _frame(50.0 + 200 * M, 4.0, _naive(150))
    n = lambda cfg: len(cal.frame_candidates(beside, _gpx(seg), cfg))
    assert n(DCFG) == 1
    assert n({**DCFG, "gpx_interpolation_max_gap_seconds": 10.0}) == 1
    assert n({**DCFG, "gpx_anchor_max_segment_gap_seconds": 10.0}) == 0


@pytest.mark.spec("RUL-setting_bounds_one_thing", "RUL-acceptance_holds_for_its_proposal", "BLD-offset_acceptance",
                  test="TST-geotag_offset_inference-how_far_a_proposal_may_move_is_its_own_setting")
def test_how_far_a_proposal_may_move_under_an_acceptance_is_its_own_setting(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(13, 0, 0)), _pt(50.001, 4.0, _utc(13, 5, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00", "a"), _frame(50.001, 4.0, "2024:07:03 14:05:00", "b")]
    accepted = {"accept_proposal": True, "accepted_offset_seconds": -3590}      # 10 s from what is proposed

    def source(**over):
        monkeypatch.setitem(utils.CONFIG, "gpx_anchor_decision_tolerance_seconds", 120.0)
        wf = cal.GeotagWorkflow("/tmp")
        utils.CONFIG.update({**CFG, **over})
        utils.CONFIG["camera_time_and_timezone_policy"]["multi_anchor_auto_apply"] = False
        cell = wf._offset_cell("6-photos-by-dest/B", "K", {"camera_group_class": "camera"},
                               {"user_decision": accepted}, frames, gpx, [])
        return cell["effective_time_anchor"], cell["stale_user_decision"], cell["proposal"]

    eff, stale, proposal = source()
    assert eff == {"offset_seconds": -3600, "source": "gpx_anchor_accepted"} and not stale
    assert proposal["acceptance_tolerance_seconds"] == 120.0                    # what the editor judges by
    eff, stale, _ = source(gpx_anchor_offset_spread_max_seconds=5.0)            # anchors' agreement: another matter
    assert eff["source"] == "gpx_anchor_accepted" and not stale
    eff, stale, proposal = source(gpx_anchor_decision_tolerance_seconds=5.0)
    assert eff == "" and stale and proposal["acceptance_tolerance_seconds"] == 5.0
