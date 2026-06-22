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
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CFG = {"gpx_anchor_max_point_distance_meters": 30.0, "gpx_anchor_max_segment_distance_meters": 30.0,
       "gpx_interpolation_max_gap_seconds": 120.0, "gpx_anchor_offset_spread_max_seconds": 120.0}
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


@pytest.mark.spec("geotag-anchor-matching-1")
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


@pytest.mark.spec("geotag-clock-error-window-1")
def test_window_rejects_same_place_other_year():
    # the SAME spot has a point this trip and one 13 years earlier; the old one would win on distance
    # (a tie at 0 m, listed first) but is out of the window, so the recent point anchors instead.
    gpx = _gpx([_pt(50.0, 4.0, datetime(2011, 7, 3, 12, 0, 0, tzinfo=timezone.utc)),
                _pt(50.0, 4.0, _utc(12, 0, 0))])
    c = cal.match_frame_to_gpx(_frame(50.0, 4.0, "2024:07:03 14:00:00"), gpx, WCFG)
    assert c is not None and c["offset_seconds"] == -7200        # 2024 point, not a ~13-year "offset"


@pytest.mark.spec("geotag-window-tz-independent-1")
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


@pytest.mark.spec("geotag-consensus-cluster-1")
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


@pytest.mark.spec("geotag-autoresolve-config-gated-1")
def test_cell_single_anchor_conservative_then_flag(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({}, frames, gpx, single=False)
    assert cell["requires_user_input"] is True and "decision_mode" not in cell
    cell2, _ = _cell({}, frames, gpx, single=True)
    assert cell2["requires_user_input"] is False and cell2["decision_mode"] == "auto_resolved"


@pytest.mark.spec("geotag-conflict-triggers-review-1")
def test_cell_conflict_requires_input_even_with_autoapply(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0)), _pt(51.0, 5.0, _utc(9, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00"), _frame(51.0, 5.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({}, frames, gpx, multi=True)
    assert cell["requires_user_input"] is True and cell["proposal"]["confidence"] == "review_required"


def test_cell_accept_proposal(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({"accept_proposal": True}, frames, gpx, single=False)
    assert cell["effective_time_anchor"]["source"] == "gpx_anchor_accepted"
    assert cell["effective_time_anchor"]["offset_seconds"] == -7200


def test_cell_manual_real_utc_derived(monkeypatch):
    gpx = _gpx([_pt(50.0, 4.0, _utc(12, 0, 0))])
    frames = [_frame(50.0, 4.0, "2024:07:03 14:00:00")]
    cell, _ = _cell({"manual_real_utc": "2024-07-03T11:00:00Z"}, frames, gpx)
    assert cell["effective_time_anchor"]["source"] == "manual_real_utc"
    assert cell["effective_time_anchor"]["offset_seconds"] == -10800              # 11:00 - 14:00


def test_cell_manual_offset_and_bad_offset(monkeypatch):
    gpx = _gpx([])
    cell, _ = _cell({"manual_offset_seconds": -7187}, [], gpx)
    assert cell["effective_time_anchor"] == {"offset_seconds": -7187, "source": "manual"}
    bad, blk = _cell({"manual_offset_seconds": "x"}, [], gpx)
    assert blk and bad["effective_time_anchor"] == ""


@pytest.mark.spec("geotag-no-proposal-requires-input-1")
def test_cell_no_anchor_is_manual_required(monkeypatch):
    cell, _ = _cell({}, [], _gpx([]))
    assert cell["proposal"] == {"proposal_source": "manual_required"} and cell["requires_user_input"]


def test_cell_accept_with_no_proposal_is_stale(monkeypatch):
    cell, _ = _cell({"accept_proposal": True}, [], _gpx([]))      # manual_required -> nothing to accept
    assert cell["stale_user_decision"] is True and cell["requires_user_input"] is True


def test_cell_manual_real_utc_invalid_and_nonderivable(monkeypatch):
    bad, blk = _cell({"manual_real_utc": "not-a-datetime"}, [], _gpx([]))
    assert blk and bad["effective_time_anchor"] == ""                       # invalid -> located blocker
    # a parseable manual_real_utc on a non-GPX (manual_required) cell can't derive an offset alone
    ok, blk2 = _cell({"manual_real_utc": "2024-07-03T11:00:00Z"}, [], _gpx([]))
    assert not blk2 and ok["effective_time_anchor"] == "" and ok["requires_user_input"] is True


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
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/B/a.arw", 50.8467, 4.3525, "2024:07:03 14:12:08"),
             rec("6-photos-by-dest/B/b.arw", 50.8480, 4.3540, "2024:07:03 14:13:08")]
    for f in files:
        p = ws / f["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files}))

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


@pytest.mark.spec("geotag-tz-derived-offset-calc-1")
def test_timezone_naive_offset_is_dst_aware():
    assert cal._timezone_naive_offset("2024:07:03 14:00:00", "Europe/Brussels")[0] == -7200   # summer +2
    assert cal._timezone_naive_offset("2024:01:03 14:00:00", "Europe/Brussels")[0] == -3600   # winter +1
    assert cal._timezone_naive_offset("2024:07:03 14:00:00", "Asia/Tokyo")[0] == -32400        # +9, no DST
    off, real = cal._timezone_naive_offset("2024:07:03 14:00:00", "Europe/Brussels")
    assert off == -7200 and real == "2024-07-03T12:00:00Z"
    for bad in [("2024:07:03 14:00:00", "Bogus/Zone"), ("garbage", "UTC"), ("2024:07:03 14:00:00", "")]:
        assert cal._timezone_naive_offset(*bad) is None


@pytest.mark.spec("geotag-bucket-proposal-priority-1", "geotag-timezone-derived-confirmable-1")
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
    cell, _ = _tzcell({"accept_proposal": True}, tz="Europe/Brussels", rep_naive="2024:07:03 14:00:00")
    assert cell["effective_time_anchor"] == {"offset_seconds": -7200, "source": "timezone_accepted"}
    assert cell["requires_user_input"] is False


def test_cell_no_timezone_is_manual_required():
    cell, _ = _tzcell({}, tz=None, rep_naive="2024:07:03 14:00:00")
    assert cell["proposal"] == {"proposal_source": "manual_required"}
