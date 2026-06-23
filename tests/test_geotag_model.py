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

"""Phase 2 (geotag) — the in-memory model: by-dest file objects, GPX index, camera groups
(photos-2-geotag, spec §14–§16). Still pre-decision: no JSON artifacts. From conftest.py.
"""
import json
import os
import sys

import pytest

import photos_2_geotag as cal
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]

GPX = """<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="50.10" lon="4.10"><time>2024-07-03T12:05:00Z</time></trkpt>
<trkpt lat="50.00" lon="4.00"><time>2024-07-03T12:00:00Z</time></trkpt>
</trkseg></trk></gpx>
"""


def _hfile(rel, *, key="SONY|ILCE-6400|123", dto="2024:07:03 14:12:08", gps=None,
           media_class="image", folder_class="6-photos-by-dest"):
    parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
              "selected_source_timestamp_tag": "DateTimeOriginal" if dto else None,
              "camera_group_key": key, "has_timestamp": bool(dto), "Make": "SONY", "Model": "ILCE-6400"}
    if gps:
        parsed.update({"GPSLatitude": gps[0], "GPSLongitude": gps[1], "has_native_gps": True})
    return {"relative_path": rel, "media_class": media_class, "folder_class": folder_class,
            "size": 100, "mtime_ns": 1,
            "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
            "metadata_status": {"camera_group_key": key, "has_timestamp": bool(dto),
                                "has_native_gps": bool(gps), "field_set_version": 1,
                                "parsed_json": json.dumps(parsed)}}


def _wf(tmp_path, handoff_files):
    wf = cal.GeotagWorkflow(str(tmp_path))
    wf.handoff = {"files": handoff_files}
    return wf


# --- Stage 2: by-dest file model --------------------------------------------

@pytest.mark.spec("geotag-destination-definition-1")
def test_file_model_builds_by_dest_photos(tmp_path):
    wf = _wf(tmp_path, [_hfile("6-photos-by-dest/Belgium/Brussels/a.arw", gps=(50.84, 4.35))])
    files = wf.build_file_model()
    assert len(files) == 1
    f = files[0]
    assert f["destination"] == "6-photos-by-dest/Belgium/Brussels"
    assert f["camera_group_key"] == "SONY|ILCE-6400|123"
    assert f["source_naive_time"] == "2024:07:03 14:12:08" and f["has_timestamp"]
    assert f["native_gps"]["lat"] == 50.84 and f["has_native_gps"]
    assert f["content_fingerprint"] == "fp-6-photos-by-dest/Belgium/Brussels/a.arw"
    assert f["planned_filename"] is None


@pytest.mark.spec("geotag-inmemory-bydest-only-1", "geotag-never-touch-video-1", "geotag-scope-bydest-only-1")
def test_file_model_excludes_non_bydest_and_videos(tmp_path):
    wf = _wf(tmp_path, [
        _hfile("6-photos-by-dest/T/a.jpg"),
        _hfile("5-photos-by-date/b.jpg", folder_class="5-photos-by-date"),     # not by-dest
        _hfile("6-photos-by-dest/T/c.mp4", media_class="video"),               # video
    ])
    rels = [f["relative_path"] for f in wf.build_file_model()]
    assert rels == ["6-photos-by-dest/T/a.jpg"]


# --- Stage 3: GPX index ------------------------------------------------------

def test_gpx_parses_sorts_and_fingerprints(tmp_path):
    root = tmp_path / "gpx"; root.mkdir()
    (root / "trip.gpx").write_text(GPX)
    idx = cal.GPXIndex(str(root)).build()
    assert idx.status == "usable" and len(idx.points) == 2
    assert idx.points[0].time_utc < idx.points[1].time_utc            # sorted by time
    assert (idx.points[0].lat, idx.points[0].lon) == (50.00, 4.00)
    fp1 = idx.fingerprint
    assert cal.GPXIndex(str(root)).build().fingerprint == fp1         # stable
    (root / "trip.gpx").write_text(GPX.replace("50.10", "51.10"))
    assert cal.GPXIndex(str(root)).build().fingerprint != fp1         # changes with a point


def test_gpx_disabled_and_missing(tmp_path):
    assert cal.GPXIndex("").build().status == "disabled"
    miss = cal.GPXIndex(str(tmp_path / "nope")).build()
    assert miss.status == "missing" and miss.warnings


def test_gpx_malformed_warns_not_crashes(tmp_path):
    root = tmp_path / "gpx"; root.mkdir()
    (root / "bad.gpx").write_text("<gpx><trkpt lat='1'")
    idx = cal.GPXIndex(str(root)).build()
    assert idx.status == "empty" and any("Malformed" in w for w in idx.warnings)


def test_gpx_parser_skips_bad_trkpts(tmp_path):
    # exercise every reject branch in GPXIndex._parse_file (GPS code -> full coverage):
    # missing lon, missing time, out-of-range coord, non-numeric coord, and a naive-time point;
    # the one fully-valid trkpt survives.
    root = tmp_path / "gpx"; root.mkdir()
    (root / "edge.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0"><time>2024-07-03T12:00:00Z</time></trkpt>'              # no lon
        '<trkpt lat="50.0" lon="4.0"></trkpt>'                                       # no time
        '<trkpt lat="200.0" lon="4.0"><time>2024-07-03T12:00:01Z</time></trkpt>'    # lat out of range
        '<trkpt lat="x" lon="4.0"><time>2024-07-03T12:00:02Z</time></trkpt>'        # non-numeric lat
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03 12:00:03</time></trkpt>'      # naive time (no tz)
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:04+02:00</time></trkpt>'  # valid, tz-aware
        '</trkseg></trk></gpx>')
    idx = cal.GPXIndex(str(root)).build()
    assert idx.status == "usable" and len(idx.points) == 1                          # only the valid one
    assert idx.points[0].time_utc.hour == 10                                        # 12:00:04+02:00 -> 10:00:04Z
    assert len(idx.warnings) >= 3                                                   # the rejects warned


def test_gpx_unreadable_file_warns_and_skips(tmp_path):
    # a .gpx that os.walk lists but open() fails on (broken symlink) -> the OSError branch warns.
    root = tmp_path / "gpx"; root.mkdir()
    os.symlink(str(tmp_path / "does-not-exist"), str(root / "broken.gpx"))
    idx = cal.GPXIndex(str(root)).build()
    assert any("Could not read GPX file" in w for w in idx.warnings) and idx.points == []


# --- Stage 4: camera groups + classification ---------------------------------

def test_camera_group_classification(tmp_path, monkeypatch):
    monkeypatch.setitem(utils.CONFIG["camera_time_and_timezone_policy"], "device_groups",
                        {"phones": ["APPLE|iPhone|p1"], "fixed_clock_cameras": ["SONY|ILCE-6400|123"]})
    wf = _wf(tmp_path, [
        _hfile("6-photos-by-dest/A/a.arw", key="SONY|ILCE-6400|123", gps=(1, 1)),
        _hfile("6-photos-by-dest/A/b.arw", key="SONY|ILCE-6400|123"),
        _hfile("6-photos-by-dest/B/p.jpg", key="APPLE|iPhone|p1"),
        _hfile("6-photos-by-dest/A/u.jpg", key="CANON|R5|999"),
    ])
    groups, unknown = wf.recognize_camera_groups(wf.build_file_model())
    assert groups["SONY|ILCE-6400|123"]["camera_group_class"] == "camera"
    assert groups["SONY|ILCE-6400|123"]["file_count"] == 2
    assert groups["SONY|ILCE-6400|123"]["destinations"] == ["6-photos-by-dest/A"]
    assert groups["SONY|ILCE-6400|123"]["has_native_gps"] == 1
    assert groups["APPLE|iPhone|p1"]["camera_group_class"] == "smartphone"
    assert groups["CANON|R5|999"]["camera_group_class"] == "unknown"
    assert unknown == ["CANON|R5|999"]


@pytest.mark.spec("camera-geotag-reuses-1")
def test_geotag_reuses_handoff_camera_group_key_never_recomputes(tmp_path):
    """Shared §6: geotag reuses prep's camera_group_key from the handoff and never recomputes camera
    identity. The handoff carries a SENTINEL group key that the identity fields (Make/Model/serial)
    could never compose — if geotag recomputed from CAMERA_IDENTITY_FIELDS it would land on a
    different key. build_file_model and recognize_camera_groups must use the handoff's key verbatim."""
    sentinel = "PREP-ASSIGNED|opaque-token"
    # parsed identity that a recomputation WOULD turn into "SN-12345|SONY|ILCE-6400" (≠ sentinel)
    parsed = {"DateTimeOriginal": "2024:07:03 14:12:08",
              "selected_source_naive_timestamp": "2024:07:03 14:12:08",
              "selected_source_timestamp_tag": "DateTimeOriginal",
              "camera_group_key": sentinel, "has_timestamp": True,
              "BodySerialNumber": "SN-12345", "Make": "SONY", "Model": "ILCE-6400"}
    rec = {"relative_path": "6-photos-by-dest/Trip/a.arw", "media_class": "image",
           "folder_class": "6-photos-by-dest", "size": 1, "mtime_ns": 1,
           "content_hash": json.dumps({"value": "fp", "status": "valid"}),
           "metadata_status": {"camera_group_key": sentinel, "has_timestamp": True,
                               "has_native_gps": False, "field_set_version": 1,
                               "parsed_json": json.dumps(parsed)}}
    wf = _wf(tmp_path, [rec])
    files = wf.build_file_model()
    assert files[0]["camera_group_key"] == sentinel                  # handoff value, not recomputed
    # the identity fields are surfaced (for display) but were NOT used to derive the key
    assert files[0]["camera_identity"]["BodySerialNumber"] == "SN-12345"
    assert sentinel != "SN-12345|SONY|ILCE-6400"
    policy = utils.CONFIG["camera_time_and_timezone_policy"]
    policy["device_groups"] = {"fixed_clock_cameras": [sentinel], "phones": []}
    groups, unknown = wf.recognize_camera_groups(files)
    assert list(groups) == [sentinel] and unknown == []              # grouped by the handoff key
    assert groups[sentinel]["camera_group_class"] == "camera"


# --- run integration (main) --------------------------------------------------

def _full_ws(tmp_path, *, device_groups, bydest_key="SONY|ILCE-6400|123"):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["camera_time_and_timezone_policy"] = dict(cfg["camera_time_and_timezone_policy"],
                                                  device_groups=device_groups)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    rel = "6-photos-by-dest/Trip/a.jpg"
    p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img")
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": [_hfile(rel, key=bydest_key)]}))
    return ws


def _main(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


@pytest.mark.spec("geotag-first-artifact-21-1")
def test_run_known_group_builds_model(tmp_path, monkeypatch, capsys):
    ws = _full_ws(tmp_path, device_groups={"fixed_clock_cameras": ["SONY|ILCE-6400|123"], "phones": []})
    code = _main(monkeypatch, ws)
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "Model built:" in out.out and "1 camera" in out.out
    # run now advances into Stage 5-6 and writes the first artifact, photos-21 (Phase 3a).
    assert os.path.exists(ws / ".photos-ingest" / "photos-21-time-decisions.json")


@pytest.mark.spec("geotag-incomplete-classification-block-1", "geotag-unknown-group-snippet-config-order-1")
def test_run_unknown_group_prints_snippet_and_exits(tmp_path, monkeypatch, capsys):
    ws = _full_ws(tmp_path, device_groups={"fixed_clock_cameras": [], "phones": []})
    code = _main(monkeypatch, ws)
    cap = capsys.readouterr()
    blob = cap.out + cap.err
    assert code == 2
    assert "unknown camera group" in blob and '"SONY|ILCE-6400|123"' in blob
    # The two arrays must be emitted in the config file's own key order — fixed_clock_cameras before
    # phones (the sort_keys=True seed order) — so a whole-block paste-over keeps the inter-array comma.
    assert blob.index('"fixed_clock_cameras"') < blob.index('"phones"')
