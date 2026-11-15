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

"""A position at latitude 0 and longitude 0 — what a device writes with no fix — is no position of the photo's own
(RUL-null_island_is_no_position, BLD-own_position_test): placed as a photo without one, never kept, never an anchor,
never counted as placed natively; and the position written over it is logged with it
(RUL-log_records_null_island_replaced). From conftest.py.
"""
import json
import sys
from datetime import datetime, timezone

import pytest
from _handoff import match_disk, vouched

import photos_2_geotag as cal
import photos_utils as utils

BYDEST = "6-photos-by-dest"
CAM = "SONY|ILCE-6400|123"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _hfile(rel, lat, lon, *, dto="2024:07:03 14:12:08"):
    parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
              "selected_source_timestamp_tag": "EXIF:DateTimeOriginal", "camera_group_key": CAM,
              "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon}
    return {"relative_path": rel, "media_class": "image", "folder_class": BYDEST, "size": 1, "mtime_ns": 1,
            "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
            "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                "camera_group_key": CAM, "has_timestamp": True,
                                # a flag a prep before the one test set: geotag judges the values themselves
                                "has_native_gps": True,
                                "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}


@pytest.mark.parametrize("lat, lon, own", [(0, 0, False), (0.0, 0.0, False), (-0.0, 0.0, False),
                                           (0, 1e-7, True), (1e-7, 0, True), (0, 4.35, True), (50.84, 0, True),
                                           (None, 0, False), (0, None, False), (None, None, False)])
@pytest.mark.spec("BLD-own_position_test", "RUL-null_island_is_no_position",
                  test="TST-geotag_null_island-own_position_is_not_exactly_zero")
def test_own_position_is_not_exactly_zero(lat, lon, own):
    # only the exact zero point is no fix: a value merely near it may be a real place
    assert utils.has_own_position(lat, lon) is own


@pytest.mark.spec("BLD-own_position_test", "RUL-null_island_is_no_position",
                  test="TST-geotag_null_island-prep_reads_zero_point_as_no_native_gps")
def test_prep_reads_zero_point_as_no_native_gps():
    parse = utils.MetadataReader._parse_exiftool_item
    zero = parse({"EXIF:DateTimeOriginal": "2024:07:03 14:12:08", "Composite:GPSLatitude": 0,
                  "Composite:GPSLongitude": 0})
    assert zero["has_native_gps"] is False
    assert (zero["GPSLatitude"], zero["GPSLongitude"]) == (0, 0)            # the values as recorded, kept
    near = parse({"EXIF:DateTimeOriginal": "2024:07:03 14:12:08", "Composite:GPSLatitude": 0.0001,
                  "Composite:GPSLongitude": 0})
    assert near["has_native_gps"] is True


@pytest.mark.spec("BLD-own_position_test", "RUL-null_island_is_no_position",
                  test="TST-geotag_null_island-file_model_holds_zero_point_as_no_own_position")
def test_file_model_holds_zero_point_as_no_own_position(tmp_path):
    wf = cal.GeotagWorkflow(str(tmp_path))
    wf.handoff = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"],
                  "files": [_hfile(f"{BYDEST}/T/z.jpg", 0, 0), _hfile(f"{BYDEST}/T/r.jpg", 50.84, 4.35)]}
    by = {f["relative_path"]: f for f in wf.build_file_model()}
    z, r = by[f"{BYDEST}/T/z.jpg"], by[f"{BYDEST}/T/r.jpg"]
    assert z["has_native_gps"] is False and r["has_native_gps"] is True
    assert (z["native_gps"]["lat"], z["native_gps"]["lon"]) == (0, 0)      # still what the file holds
    assert cal.holds_no_fix(z) and not cal.holds_no_fix(r)
    # decided from pinned values, the same: a pinned zero point is no position of the photo's own
    pinned = cal.from_originals(z, cal.own_values({"GPSLatitude": 0.0, "GPSLongitude": 0.0, "has_native_gps": True,
                                                   "selected_source_naive_timestamp": "2024:07:03 14:12:08",
                                                   "selected_source_timestamp_tag": "EXIF:DateTimeOriginal"}))
    assert pinned["has_native_gps"] is False and pinned["native_gps"] is None


def _pt(lat, lon, h, m, s):
    return cal.GPXPoint(lat, lon, datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc), "trip.gpx", 0)


def _gpx():
    idx = cal.GPXIndex("")
    idx.points = [_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.001, 12, 1, 0)]
    return idx


def _model(rel, lat, lon):
    f = {"relative_path": rel, "destination": f"{BYDEST}/T", "camera_group_key": CAM,
         "content_fingerprint": "fp" + rel, "size": 10,
         "mtime_ns": 1, "native_gps": {"lat": lat, "lon": lon, "processing_method": None},
         "processing_method": None}
    return dict(f, has_native_gps=utils.has_own_position(lat, lon))


@pytest.mark.spec("RUL-null_island_is_no_position", "RUL-placement_order", "BLD-placement_order",
                  "BLD-gps_decisions_record",
                  test="TST-geotag_null_island-zero_point_is_placed_never_kept_nor_counted_native")
def test_zero_point_is_placed_never_kept_nor_counted_native(tmp_path):
    ws = tmp_path / "ws"; (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws)); wf._gpx_fingerprint = "gfp"
    z = _model(f"{BYDEST}/T/z.jpg", 0, 0)
    ru = datetime(2024, 7, 3, 12, 0, 30, tzinfo=timezone.utc)
    assert cal.classify_gps(z, ru, _gpx(), utils.CONFIG, None, {})[0] == "gpx_interpolation"   # placed by the track
    assert cal.classify_gps(z, None, _gpx(), utils.CONFIG, None, {})[0] == "blocked"           # else waits
    art, _ = wf.build_gps_decisions([z], [{"relative_path": z["relative_path"], "resolved_utc": None}],
                                    _gpx(), None, "rfp")
    s = art["destinations"][f"{BYDEST}/T"]["gps_decisions"]["summary"]
    assert s["preserve_native_gps"] == 0 and s["blocked"] == 1


@pytest.mark.spec("RUL-log_records_null_island_replaced", "BLD-geotag_log_steps",
                  test="TST-geotag_null_island-position_written_over_zero_point_is_logged_with_it")
def test_position_written_over_zero_point_is_logged_with_it(tmp_path):
    ws = tmp_path / "ws"; ctl = ws / ".photos-ingest"; ctl.mkdir(parents=True)
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {"cache_fingerprint": "pcf"})))
    d = f"{BYDEST}/T"
    time_art = {"status": "complete", "destinations": {d: {"destination_timezone": {"effective_iana_timezone": "UTC"}}}}
    gps_art = {"status": "complete", "destinations": {
        d: {"folder_fallback": {"effective_fallback": None}, "gps_decisions": {"review_items": []}}}}
    for name, art in (("photos-21-time-decisions.json", time_art), ("photos-23-gps-decisions.json", gps_art),
                      ("photos-22-gps-drift-validation.json", {"status": "complete", "destinations": {}})):
        (ctl / name).write_text(json.dumps(art))
    wf = cal.GeotagWorkflow(str(ws)); wf.handoff = {"cache_fingerprint": "pcf"}; wf._gpx_fingerprint = "gfp"
    files = [_model(f"{d}/z.jpg", 0, 0), _model(f"{d}/m.jpg", None, None)]
    rows = [{"relative_path": f["relative_path"], "resolved_utc": "2024-07-03T12:00:30Z",
             "resolved_utc_status": "valid"} for f in files]
    plan, blk = wf.build_executable_plan(files, rows, time_art, gps_art, _gpx(), "rfp")
    assert not blk
    ops = plan["destinations"][d]["operations"]
    gz = next(o for o in ops if o["type"] == "metadata_gps_write" and o["relative_path"].endswith("z.jpg"))
    gm = next(o for o in ops if o["type"] == "metadata_gps_write" and o["relative_path"].endswith("m.jpg"))
    assert gz["gps_origin"] == "recompute_automated"
    assert gz["pre_state"] == {"present": True, "GPSLatitude": 0, "GPSLongitude": 0, "GPSProcessingMethod": ""}
    assert "pre_state" not in gm                       # a photo with no position at all: nothing replaced
    photos = cal.build_complete_log({}, files, rows, {}, plan)          # the log finalize writes
    written = {fp: next(s for s in photos[fp]["journey"] if s["action"] == "gps_written")
               for fp in (f"fp{d}/z.jpg", f"fp{d}/m.jpg")}
    assert written[f"fp{d}/z.jpg"]["pre_state"] == gz["pre_state"]
    assert "pre_state" not in written[f"fp{d}/m.jpg"]


@pytest.mark.parametrize("lon, anchored", [(0, False), (0.0001, True)], ids=["zero_point", "near_it"])
@pytest.mark.spec("RUL-null_island_is_no_position", "BLD-own_position_test", "RUL-offset_from_own_evidence",
                  test="TST-geotag_null_island-zero_point_is_never_an_anchor")
def test_zero_point_is_never_an_anchor(tmp_path, monkeypatch, lon, anchored):
    # A track that passes the zero point when the photo was taken would anchor its camera's clock — were the
    # zero point a position. A point 11 m from it is one, and does.
    ws = tmp_path / "ws"; ws.mkdir()
    for m in MANAGED:
        (ws / m).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx_dir = tmp_path / "gpx"; gpx_dir.mkdir()
    (gpx_dir / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        f'<trkpt lat="0" lon="{lon}"><time>2024-07-03T12:12:21Z</time></trkpt>'
        f'<trkpt lat="0.0001" lon="{lon}"><time>2024-07-03T12:13:21Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx_dir)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    files = [_hfile(f"{BYDEST}/B/a.arw", 0, lon)]
    for f in files:
        p = ws / f["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {
        "filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files),
        "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
    except SystemExit as e:
        assert e.code in (0, None)
    art = json.load(open(ctl / "photos-21-time-decisions.json"))
    cell = art["destinations"][f"{BYDEST}/B"]["camera_group_time_decisions"][CAM]
    assert (cell["proposal"]["proposal_source"] == "gpx_self_anchor") is anchored
