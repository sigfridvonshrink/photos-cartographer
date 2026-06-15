"""Phase 3c (calibration) — §10.2: clock offsets do NOT inherit across destinations.

Each (camera group, destination[, date]) bucket proposes its own offset from GPX self-anchor →
timezone-derived → manual. A child with no self-anchor does NOT adopt an ancestor's resolved offset
(unlike the timezone, which still inherits — see test_calibration_time_decisions.py). Self-anchors
never leak between destinations. From conftest.py.
"""
from datetime import datetime, timezone

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
BYDEST = "6-photos-by-dest"


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    return idx


def _pt(lat, lon, t):
    return cal.GPXPoint(lat, lon, datetime(2024, 7, 3, t, 0, 0, tzinfo=timezone.utc), "t.gpx", 0)


def _file(rel, dest, *, gps=None, naive="2024:07:03 14:00:00", key=CAM):
    return {"relative_path": rel, "destination": dest, "camera_group_key": key,
            "native_gps": ({"lat": gps[0], "lon": gps[1]} if gps else None),
            "has_native_gps": bool(gps), "has_timestamp": True, "source_naive_time": naive,
            "camera_identity": {}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.CalibrationWorkflow(str(ws))
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
    # The offset-inheritance helper was removed with §10.2; only the timezone still inherits.
    assert not hasattr(cal.CalibrationWorkflow, "_nearest_ancestor_offset")


def test_child_does_not_inherit_resolved_parent_offset(tmp_path):
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Trip/Sub/c.arw", f"{BYDEST}/Trip/Sub")]   # no GPS, no tz
    art, _ = _build(wf, files, _gpx(TRACK))
    parent = _cell(art, f"{BYDEST}/Trip")
    assert parent["decision_mode"] == "auto_resolved" and parent["effective_time_anchor"]["offset_seconds"] == -7200
    child = _cell(art, f"{BYDEST}/Trip/Sub")
    assert child["proposal"] == {"proposal_source": "manual_required"}    # parent's -7200 does NOT flow down
    assert child["requires_user_input"] is True


def test_no_ancestor_is_manual_required(tmp_path):
    wf = _wf(tmp_path)
    files = [_file(f"{BYDEST}/Alone/x.arw", f"{BYDEST}/Alone")]              # no GPS, no ancestor, no tz
    art, _ = _build(wf, files, _gpx(TRACK))
    assert _cell(art, f"{BYDEST}/Alone")["proposal"] == {"proposal_source": "manual_required"}


def test_sibling_offset_does_not_leak(tmp_path):
    wf = _wf(tmp_path)
    # Trip/A self-anchors; Trip/B (sibling, no GPS) must NOT adopt A — offsets never cross destinations.
    files = [_file(f"{BYDEST}/Trip/A/a.arw", f"{BYDEST}/Trip/A", gps=(50.0, 4.0)),
             _file(f"{BYDEST}/Trip/A/b.arw", f"{BYDEST}/Trip/A", gps=(51.0, 5.0), naive="2024:07:03 15:00:00"),
             _file(f"{BYDEST}/Trip/B/c.arw", f"{BYDEST}/Trip/B")]
    art, _ = _build(wf, files, _gpx(TRACK))
    assert _cell(art, f"{BYDEST}/Trip/A")["decision_mode"] == "auto_resolved"
    assert _cell(art, f"{BYDEST}/Trip/B")["proposal"] == {"proposal_source": "manual_required"}


def test_manual_parent_offset_does_not_reroot_children(tmp_path):
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Trip/Sub/c.arw", f"{BYDEST}/Trip/Sub"),
                             _file(f"{BYDEST}/Trip/Sub/Deep/d.arw", f"{BYDEST}/Trip/Sub/Deep")]
    # Sub is given a manual offset; Deep must still be manual_required (no inheritance), not -100.
    prior = {"destinations": {f"{BYDEST}/Trip/Sub": {"camera_group_time_decisions":
             {CAM: {"user_decision": {"manual_offset_seconds": -100}}}}}}
    art, _ = _build(wf, files, _gpx(TRACK), prior)
    assert _cell(art, f"{BYDEST}/Trip/Sub")["effective_time_anchor"] == {"offset_seconds": -100, "source": "manual"}
    assert _cell(art, f"{BYDEST}/Trip/Sub/Deep")["proposal"] == {"proposal_source": "manual_required"}


def test_determinism_rerun_byte_identical(tmp_path):
    wf = _wf(tmp_path)
    files = PARENT_FRAMES + [_file(f"{BYDEST}/Trip/Sub/c.arw", f"{BYDEST}/Trip/Sub")]
    import json
    a1, _ = _build(wf, files, _gpx(TRACK))
    a2, _ = _build(wf, files, _gpx(TRACK), a1)
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)
