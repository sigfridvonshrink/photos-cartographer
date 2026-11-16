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

"""Phase 6c-1 — REAL-tool integration for the executor: the rest of the suite mocks exiftool +
ImageMagick, so this test drives the actual binaries (present in CI's "Install system tools" step)
to validate the executor's central safety assumption end-to-end — an exiftool write changes the
EXIF but NOT the ImageMagick content fingerprint, so the post-write verify confirms the op.

Skipped when the tools are absent (e.g. a bare local checkout). From conftest.py.
"""
import json
from _handoff import vouched
from _zone import answer_root_zone, with_root_zone
import os
import shutil
import subprocess
import sys

import pytest

import photos_2_geotag as cal
import photos_utils as utils

_HAVE_TOOLS = bool(shutil.which("exiftool") and (shutil.which("magick") or shutil.which("identify")))
pytestmark = pytest.mark.skipif(not _HAVE_TOOLS, reason="requires real exiftool + ImageMagick")

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cam_small.jpg")
CAM = "SONY|ILCE-6400|123"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


@pytest.mark.spec("RUL-fingerprint_survives_mutation", test="TST-geotag_execution_real-exif_write_preserves_content_fingerprint")
def test_exif_write_preserves_content_fingerprint(tmp_path):
    """The seam the executor relies on, against the real binaries: write EXIF, fingerprint is stable."""
    img = tmp_path / "img.jpg"; shutil.copy(FIXTURE, img)
    before = utils.ContentHasher.fingerprint_image(str(img))
    assert before["status"] == "valid"
    assert cal.GeotagWorkflow(str(tmp_path))._exiftool_write(
        str(img), {"DateTimeOriginal": "2024:07:03 14:12:21", "GPSLatitude": 50.8467, "GPSLongitude": 4.3525}) is True
    after = utils.ContentHasher.fingerprint_image(str(img))
    assert after["value"] == before["value"]                          # decoded content unchanged
    got = subprocess.run(["exiftool", "-s3", "-DateTimeOriginal", str(img)],
                         capture_output=True, text=True).stdout.strip()
    assert got == "2024:07:03 14:12:21"                               # EXIF really written


@pytest.mark.parametrize("lat, lon, refs", [(50.8467, 4.3525, ("N", "E")), (-33.9, -70.6, ("S", "W"))])
@pytest.mark.spec("RUL-position_written_whole", "BLD-position_tags",
                  test="TST-geotag_execution_real-planned_gps_write_lands_a_readable_fix")
def test_planned_gps_write_lands_a_readable_fix(tmp_path, lat, lon, refs):
    """RUL-position_written_whole against the real binary: the tags `plan_file_ops` plans must land a fix a conforming
    reader can use. Coordinate-only writes were readable to exiftool's lenient composite but carried
    no GPSLatitudeRef/GPSLongitudeRef, so exiv2/digiKam saw NO location — and `-n` stored a negative
    coordinate as its magnitude, flipping the hemisphere. Assert the raw ref tags AND the signed
    round-trip, since the composite alone would pass even with the refs missing."""
    img = tmp_path / "img.jpg"; shutil.copy(FIXTURE, img)
    ops = cal.plan_file_ops({"relative_path": "img.jpg", "content_fingerprint": "fp", "size": 1, "mtime_ns": 1},
                            "2024-07-03T12:12:21Z", "Europe/Brussels", "gpx_interpolation",
                            {"lat": lat, "lon": lon}, None)
    writes = next(o for o in ops if o["type"] == "metadata_gps_write")["writes"]
    assert cal.GeotagWorkflow(str(tmp_path))._exiftool_write(str(img), writes) is True

    raw = subprocess.run(["exiftool", "-n", "-s3", "-EXIF:GPSLatitudeRef", "-EXIF:GPSLongitudeRef", str(img)],
                         capture_output=True, text=True).stdout.split()
    assert tuple(raw) == refs                                  # the hemisphere is on the file itself
    back = json.loads(subprocess.run(["exiftool", "-n", "-j", "-GPSLatitude", "-GPSLongitude", str(img)],
                                     capture_output=True, text=True).stdout)[0]
    assert (round(back["GPSLatitude"], 4), round(back["GPSLongitude"], 4)) == (round(lat, 4), round(lon, 4))


def _run(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", cmd])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def test_full_execute_with_real_tools(tmp_path, monkeypatch):
    """plan -> execute the whole geotag against real exiftool + ImageMagick: two real photos get
    their corrected time written and are renamed to destination-local civil time, and every post-write
    content fingerprint matches (status success)."""
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir(); (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)                        # the zone answered once at the root (RUL-timezone_auto_resolves)
    real_fp = utils.ContentHasher.fingerprint_image(FIXTURE)["value"]

    def rec(rel, dto, lat, lon):
        dst = ws / rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(FIXTURE, dst)
        st = dst.stat()
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon}
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": real_fp, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/T/a.jpg", "2024:07:03 14:00:00", 50.0, 4.0),
             rec("6-photos-by-dest/T/b.jpg", "2024:07:03 15:00:00", 51.0, 5.0)]
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": files, "cache_fingerprint": "pcf",
        "depends_on": {"cache": {"image_engine_version": utils.get_imagemagick_version(), "fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))

    _run(monkeypatch, ws, "plan")
    p = ctl / "photos-21-time-decisions.json"; a = json.load(open(p))
    p.write_text(json.dumps(a))
    _run(monkeypatch, ws, "plan")
    assert (ctl / "photos-24-executable-plan.json").exists()

    assert _run(monkeypatch, ws, "execute") == 0                      # real exiftool + fingerprint, no mocks
    summary = json.load(open(ctl / "photos-25-execution-summary.json"))
    assert summary["status"] == "success", summary
    assert summary["totals"]["metadata_time_writes"] == 2 and summary["totals"]["renames"] == 2
    assert not summary["fingerprint_mismatches"]                       # the real write was content-invariant
    # renamed to destination-local civil time (resolved 12:00/13:00Z + Brussels summer +2h)
    out = ws / "6-photos-by-dest" / "T"
    assert sorted(os.listdir(out)) == ["2024-07-03--14-00-00.jpg", "2024-07-03--15-00-00.jpg"]
    # and the corrected time was really written into the renamed file
    got = subprocess.run(["exiftool", "-s3", "-DateTimeOriginal", str(out / "2024-07-03--14-00-00.jpg")],
                         capture_output=True, text=True).stdout.strip()
    assert got == "2024:07:03 14:00:00"


@pytest.mark.parametrize("lat, lon", [(50.8467, 4.3525), (-33.865143, -70.6)])
@pytest.mark.spec("BLD-geotag_execution", test="TST-geotag_execution_real-a_written_photo_reads_back_as_its_planned_values")
def test_a_written_photo_reads_back_as_its_planned_values(tmp_path, lat, lon):
    """Against the real binary: a photo geotag wrote reads back as holding every planned value — time, offset,
    position, references, marker — which is how execute tells its own interrupted write from an edit made since
    the plan; an edit to one tag no longer reads back as the plan."""
    img = tmp_path / "img.jpg"; shutil.copy(FIXTURE, img)
    ops = cal.plan_file_ops({"relative_path": "img.jpg", "content_fingerprint": "fp", "size": 1, "mtime_ns": 1},
                            "2024-07-03T12:12:21Z", "Europe/Brussels", "gpx_interpolation",
                            {"lat": lat, "lon": lon}, None)
    writes = {}
    for o in ops:
        writes.update(o.get("writes") or {})
    wf = cal.GeotagWorkflow(str(tmp_path))
    assert wf._exiftool_write(str(img), writes) is True
    assert cal._holds_writes(wf._exiftool_read(str(img), sorted(writes)), writes)
    assert wf._exiftool_write(str(img), {"DateTimeOriginal": "2024:07:03 09:00:00"}) is True  # edited elsewhere
    assert not cal._holds_writes(wf._exiftool_read(str(img), sorted(writes)), writes)


def _prep_read(path):
    """The photo's metadata as prep reads and keeps it (BLD-metadata_extraction, BLD-other_time_fields_read)."""
    out = subprocess.run(["exiftool"] + utils.EXIFTOOL_METADATA_OPTIONS + [str(path)], capture_output=True, text=True)
    return utils.MetadataReader._parse_exiftool_item(json.loads(out.stdout)[0])


def _model_file(path, parsed):
    """The photo as geotag's file model holds it, from prep's record."""
    return {"relative_path": path.name, "content_fingerprint": "fp", "size": 1, "mtime_ns": 1,
            "raw_times": {k: parsed[k] for k in ("DateTimeOriginal", "OffsetTimeOriginal") if parsed.get(k)},
            "other_times": cal.held_other_times(parsed)}


@pytest.mark.spec("RUL-other_capture_times_corrected", "BLD-other_time_fields_written", "BLD-other_time_fields_read",
                  test="TST-geotag_execution_real-the_other_time_fields_are_rewritten_in_a_real_photo")
def test_the_other_time_fields_are_rewritten_in_a_real_photo(tmp_path):
    """Against the real binary, on a camera JPEG holding CreateDate, ModifyDate, their offsets and sub-seconds:
    one copy given an XMP and an IPTC date too. Prep's read tells which fields each holds; geotag's time write puts
    the corrected local time into exactly those, each in its own format, read back by prep as written — so a
    re-plan finds nothing to write, and execute recognises its own write. ModifyDate, its offset and the sub-second
    fields keep their values; the copy without XMP or IPTC is given neither."""
    tagged = tmp_path / "tagged.jpg"; shutil.copy(FIXTURE, tagged)
    bare = tmp_path / "bare.jpg"; shutil.copy(FIXTURE, bare)
    subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-XMP:DateCreated=2026:05:15 11:32:29.58+02:00",
                    "-IPTC:DateCreated=2026:05:15", "-IPTC:TimeCreated=11:32:29+02:00", str(tagged)], check=True)
    wf = cal.GeotagWorkflow(str(tmp_path))
    for img in (tagged, bare):
        before = _prep_read(img)
        assert (before["DateTimeOriginal"], before["OffsetTimeOriginal"]) == ("2026:05:15 11:32:29", "+02:00")
        assert before["EXIF:CreateDate"] == "2026:05:15 11:32:29"
        f = _model_file(img, before)
        (op,) = [o for o in cal.plan_file_ops(f, "2026-05-15T09:32:29Z", "Asia/Tokyo", "preserve_native", None, None)
                 if o["type"] == "metadata_time_write"]
        assert wf._exiftool_write(str(img), op["writes"]) is True
        assert cal._holds_writes(wf._exiftool_read(str(img), sorted(op["writes"])), op["writes"])
        after = _prep_read(img)
        assert (after["DateTimeOriginal"], after["OffsetTimeOriginal"]) == ("2026:05:15 18:32:29", "+09:00")
        assert (after["EXIF:CreateDate"], after["EXIF:OffsetTimeDigitized"]) == ("2026:05:15 18:32:29", "+09:00")
        for k in ("ModifyDate", "OffsetTime", "SubSecTimeOriginal"):
            assert before[k] is not None and after[k] == before[k], k          # the edit's time, the fraction
        subsec = subprocess.run(["exiftool", "-n", "-s3", "-SubSecTimeDigitized", "-SubSecTime", str(img)],
                                capture_output=True, text=True).stdout.split()
        assert subsec == ["581", "581"]
        assert not [o for o in cal.plan_file_ops(_model_file(img, after), "2026-05-15T09:32:29Z", "Asia/Tokyo",
                                                 "preserve_native", None, None)
                    if o["type"] == "metadata_time_write"]                       # held as written: nothing again
    t = _prep_read(tagged)
    assert (t["XMP:DateCreated"], t["IPTC:DateCreated"], t["IPTC:TimeCreated"]) == \
        ("2026:05:15 18:32:29.58+09:00", "2026:05:15", "18:32:29+09:00")
    raw = subprocess.run(["exiftool", "-b", "-XMP", str(tagged)], capture_output=True, text=True).stdout
    assert "2026-05-15T18:32:29.58+09:00" in raw                                  # ISO in the file itself
    b = _prep_read(bare)
    assert (b["XMP:DateCreated"], b["IPTC:DateCreated"], b["IPTC:TimeCreated"]) == (None, None, None)


@pytest.mark.spec("RUL-suffix_in_capture_order", "BLD-sub_second_read", "BLD-metadata_extraction",
                  test="TST-geotag_execution_real-a_burst_timed_by_create_date_keeps_its_order")
def test_a_burst_timed_by_create_date_keeps_its_order(tmp_path):
    """Against the real binary: two photos of one second recording no DateTimeOriginal, timed by CreateDate, the one
    whose name sorts first taken later by SubSecTimeDigitized. Prep reads the EXIF sub-second field beside CreateDate,
    and geotag gives the earlier photo the bare name, the later the first suffix — not their names' order."""
    files = []
    for name, digits in (("a.jpg", "70"), ("b.jpg", "30")):
        img = tmp_path / name; shutil.copy(FIXTURE, img)
        subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-DateTimeOriginal=", "-SubSecTimeOriginal=",
                        f"-SubSecTimeDigitized={digits}", str(img)], check=True)
        parsed = _prep_read(img)
        assert parsed["selected_source_timestamp_tag"].endswith(":CreateDate")
        assert parsed["SubSecTimeDigitized"] is not None
        files.append({"relative_path": "6-photos-by-dest/T/" + name, "resolved_utc": "2026-05-15T09:32:29Z",
                      "destination_timezone": "Europe/Brussels", "sub_second": cal.recorded_sub_second(parsed)})
    assert [f["sub_second"] for f in files] == [0.7, 0.3]
    planned = {r["current_name"]: r["planned_name"] for r in cal.plan_renames(files, "%Y-%m-%d--%H-%M-%S")}
    assert planned == {"b.jpg": "2026-05-15--11-32-29.jpg", "a.jpg": "2026-05-15--11-32-29-001.jpg"}


@pytest.mark.spec("RUL-failed_write_reason_recorded", "BLD-write_failure_reason",
                  test="TST-geotag_execution_real-a_photo_exiftool_cannot_write_gives_its_reason")
def test_a_photo_exiftool_cannot_write_gives_its_reason(tmp_path):
    """The real exiftool, given a file it cannot write: the write returns exiftool's own message, the file is left
    as it was and nothing is left beside it."""
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a picture at all")
    said = cal.GeotagWorkflow(str(tmp_path))._exiftool_write(str(bad), {"DateTimeOriginal": "2024:07:03 14:00:00"})
    assert isinstance(said, str) and said.startswith("Error: ") and "bad.jpg" in said
    assert bad.read_bytes() == b"not a picture at all" and os.listdir(tmp_path) == ["bad.jpg"]
