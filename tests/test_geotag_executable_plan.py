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

"""Phase 6b (geotag) — photos-24-executable-plan.json (§28): the per-file operation builder,
the readiness gate, and the deterministic plan + dependency cascade. Op logic at full coverage.
From conftest.py.
"""
import copy
import json
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

BYDEST = "6-photos-by-dest"
UTC = "2024-07-03T12:12:21Z"


def _pol(**over):
    p = copy.deepcopy(utils.CONFIG["camera_time_and_timezone_policy"])
    p.update(over)
    return dict(utils.CONFIG, camera_time_and_timezone_policy=p)


def _file(rel=f"{BYDEST}/T/a.arw"):
    return {"relative_path": rel, "content_fingerprint": "fp" + rel, "size": 10, "mtime_ns": 1}


def _types(ops):
    return [o["type"] for o in ops]


# --- plan_file_ops: branch by branch ----------------------------------------

def test_time_write_honors_flags():
    f = _file()
    full = cal.plan_file_ops(f, UTC, "Europe/Brussels", "preserve_native", None, None, utils.CONFIG)
    w = next(o for o in full if o["type"] == "metadata_time_write")["writes"]
    assert w == {"DateTimeOriginal": "2024:07:03 14:12:21", "OffsetTimeOriginal": "+02:00"}
    # offset tag off -> no OffsetTimeOriginal
    no_off = cal.plan_file_ops(f, UTC, "Europe/Brussels", "preserve_native", None, None,
                               _pol(write_corrected_offset_tags=False))
    assert "OffsetTimeOriginal" not in no_off[0]["writes"]
    # metadata times off -> no time op at all (and preserve_native -> true no-op)
    assert cal.plan_file_ops(f, UTC, "Europe/Brussels", "preserve_native", None, None,
                             _pol(write_corrected_metadata_times=False)) == []


@pytest.mark.parametrize("cat, origin, marker", [
    ("gpx_interpolation", "recompute_automated", "interpolated"),
    ("gpx_extrapolation", "recompute_automated", "interpolated"),
    ("manual_locked", "apply_manual", "manual_locked"),
    ("manual_fallback", "apply_manual", "manual_fallback")])
def test_gps_write_and_marker(cat, origin, marker):
    ops = cal.plan_file_ops(_file(), UTC, "Europe/Brussels", cat, {"lat": 50.0, "lon": 4.0}, None,
                            _pol(write_corrected_metadata_times=False))
    gw = next(o for o in ops if o["type"] == "metadata_gps_write")
    assert gw["writes"] == {"GPSLatitude": 50.0, "GPSLongitude": 4.0} and gw["gps_origin"] == origin
    mk = next(o for o in ops if o["type"] == "gps_marker_write")
    assert mk["writes"]["GPSProcessingMethod"] == marker


def test_no_gps_write_for_preserve_or_no_change_or_missing_coord():
    pol = _pol(write_corrected_metadata_times=False)
    assert cal.plan_file_ops(_file(), UTC, "x", "preserve_native", {"lat": 1, "lon": 2}, None, pol) == []
    assert cal.plan_file_ops(_file(), UTC, "x", "no_change", None, None, pol) == []
    assert cal.plan_file_ops(_file(), UTC, "x", "gpx_interpolation", None, None, pol) == []  # no coord


def test_rename_op_by_flag():
    f = _file()
    ren = {"rename": True, "current_name": "a.arw", "planned_name": "2024-07-03--14-12-21.arw"}
    pol = _pol(write_corrected_metadata_times=False)
    op = cal.plan_file_ops(f, UTC, "Europe/Brussels", "preserve_native", None, ren, pol)
    assert _types(op) == ["rename_no_clobber"] and op[0]["from"] == "a.arw" and op[0]["to"].endswith(".arw")
    assert cal.plan_file_ops(f, UTC, "x", "preserve_native", None, {"rename": False}, pol) == []  # no rename
    assert cal.plan_file_ops(f, UTC, "x", "preserve_native", None, ren,
                             _pol(write_corrected_metadata_times=False,
                                  write_corrected_filename_times=False)) == []   # flag off


def test_operation_id_deterministic_and_distinct():
    f = _file()
    a = cal.plan_file_ops(f, UTC, "Europe/Brussels", "preserve_native", None, None, utils.CONFIG)
    b = cal.plan_file_ops(f, UTC, "Europe/Brussels", "preserve_native", None, None, utils.CONFIG)
    assert a[0]["operation_id"] == b[0]["operation_id"]                                # stable
    g = cal.plan_file_ops(f, UTC, "Europe/Brussels", "gpx_interpolation", {"lat": 1, "lon": 2}, None,
                          _pol(write_corrected_metadata_times=False))
    assert len({o["operation_id"] for o in g}) == 2                                    # distinct per op


def test_local_time_and_offset_unpositionable():
    assert cal._local_time_and_offset(None, "Europe/Brussels") == (None, None)
    assert cal._local_time_and_offset(UTC, "") == (None, None)


# --- build_executable_plan + readiness + deps -------------------------------

def _wf(tmp_path, *, files, time_status="complete", gps_status="complete", tz="Europe/Brussels"):
    ws = tmp_path / "ws"; (ws / ".photos-ingest").mkdir(parents=True)
    ctl = ws / ".photos-ingest"
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"cache_fingerprint": "pcf"}))
    dests = {f["destination"] for f in files}
    time_art = {"status": time_status, "destinations": {
        d: {"destination_timezone": {"effective_iana_timezone": tz}} for d in dests}}
    gps_art = {"status": gps_status, "destinations": {
        d: {"folder_fallback": {"effective_fallback": None}, "gps_decisions": {"review_items": []}} for d in dests}}
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(time_art))
    (ctl / "photos-22-gps-drift-validation.json").write_text(
        json.dumps({"status": "complete", "destinations": {}}))
    (ctl / "photos-23-gps-decisions.json").write_text(json.dumps(gps_art))
    wf = cal.GeotagWorkflow(str(ws))
    wf.handoff = {"cache_fingerprint": "pcf"}
    wf._gpx_fingerprint = "gfp"
    return wf, time_art, gps_art


def _gpx():
    idx = cal.GPXIndex(""); idx.points = []
    return idx


def _model(rel, dest, *, native=False):
    return {"relative_path": rel, "destination": dest, "has_native_gps": native,
            "content_fingerprint": "fp" + rel, "size": 10, "mtime_ns": 1}


def _row(rel, status="valid", utc=UTC):
    return {"relative_path": rel, "resolved_utc": (utc if status == "valid" else None),
            "resolved_utc_status": status}


def test_plan_ready_with_ops_and_full_depends_on(tmp_path):
    files = [_model(f"{BYDEST}/T/a.arw", f"{BYDEST}/T", native=True)]
    wf, t, g = _wf(tmp_path, files=files)
    plan, blk = wf.build_executable_plan(files, [_row(f"{BYDEST}/T/a.arw")], t, g, _gpx(), "rfp")
    assert not blk and plan["status"] == "ready" and plan["executable"] is True
    assert plan["artifact_type"] == "executable_plan" and plan["plan_id"]
    d = plan["destinations"][f"{BYDEST}/T"]
    assert d["summary"]["metadata_time_writes"] == 1                                   # native -> time only
    dep = plan["depends_on"]
    for k in ("time_decisions", "gps_decisions", "resolved_utc_cache_fingerprint", "config_fingerprint",
              "camera_group_fingerprint", "handoff", "prep_cache_fingerprint", "gpx_fingerprint",
              "metadata_field_set_version", "filename_format_fingerprint", "media_preconditions",
              "planned_operation_fingerprint"):
        assert k in dep, k
    assert dep["time_decisions"]["sha256"] and dep["resolved_utc_cache_fingerprint"] == "rfp"


def test_unresolved_utc_blocks(tmp_path):
    files = [_model(f"{BYDEST}/T/a.arw", f"{BYDEST}/T")]
    wf, t, g = _wf(tmp_path, files=files)
    plan, blk = wf.build_executable_plan(files, [_row(f"{BYDEST}/T/a.arw", status="unresolved")], t, g, _gpx(), "rfp")
    assert plan["status"] == "blocked" and plan["executable"] is False
    assert any("no valid resolved UTC" in b for b in blk)


def test_incomplete_decisions_block(tmp_path):
    files = [_model(f"{BYDEST}/T/a.arw", f"{BYDEST}/T", native=True)]
    rows = [_row(f"{BYDEST}/T/a.arw")]
    wf, t, g = _wf(tmp_path, files=files)                                     # both complete on disk
    plan, blk = wf.build_executable_plan(files, rows, t, dict(g, status="requires_user_input"), _gpx(), "rfp")
    assert plan["status"] == "blocked" and any("photos-23-gps-decisions" in b for b in blk)
    _, blk2 = wf.build_executable_plan(files, rows, dict(t, status="requires_user_input"), g, _gpx(), "rfp")
    assert any("photos-21-time-decisions" in b for b in blk2)


def test_plan_deterministic_and_fingerprint_sensitive(tmp_path):
    files = [_model(f"{BYDEST}/T/a.arw", f"{BYDEST}/T", native=True)]
    wf, t, g = _wf(tmp_path, files=files)
    rows = [_row(f"{BYDEST}/T/a.arw")]
    p1, _ = wf.build_executable_plan(files, rows, t, g, _gpx(), "rfp")
    p2, _ = wf.build_executable_plan(files, rows, t, g, _gpx(), "rfp")
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)            # byte-identical
    assert p1["plan_id"] == p2["plan_id"]
    p3, _ = wf.build_executable_plan(files, rows, t, g, _gpx(), "different-rfp")
    assert p3["plan_id"] != p1["plan_id"]                                              # input change -> new id
