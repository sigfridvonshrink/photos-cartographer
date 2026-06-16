"""Phase 6c-1 — REAL-tool integration for the executor: the rest of the suite mocks exiftool +
ImageMagick, so this test drives the actual binaries (present in CI's "Install system tools" step)
to validate the executor's central safety assumption end-to-end — an exiftool write changes the
EXIF but NOT the ImageMagick content fingerprint, so the post-write verify confirms the op.

Skipped when the tools are absent (e.g. a bare local checkout). From conftest.py.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

_HAVE_TOOLS = bool(shutil.which("exiftool") and (shutil.which("magick") or shutil.which("identify")))
pytestmark = pytest.mark.skipif(not _HAVE_TOOLS, reason="requires real exiftool + ImageMagick")

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cam_small.jpg")
CAM = "SONY|ILCE-6400|123"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def test_exif_write_preserves_content_fingerprint(tmp_path):
    """The seam the executor relies on, against the real binaries: write EXIF, fingerprint is stable."""
    img = tmp_path / "img.jpg"; shutil.copy(FIXTURE, img)
    before = utils.ContentHasher.fingerprint_image(str(img))
    assert before["status"] == "valid"
    assert cal.CalibrationWorkflow(str(tmp_path))._exiftool_write(
        str(img), {"DateTimeOriginal": "2024:07:03 14:12:21", "GPSLatitude": 50.8467, "GPSLongitude": 4.3525})
    after = utils.ContentHasher.fingerprint_image(str(img))
    assert after["value"] == before["value"]                          # decoded content unchanged
    got = subprocess.run(["exiftool", "-s3", "-DateTimeOriginal", str(img)],
                         capture_output=True, text=True).stdout.strip()
    assert got == "2024:07:03 14:12:21"                               # EXIF really written


def _run(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-time-gps", cmd])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def test_full_execute_with_real_tools(tmp_path, monkeypatch):
    """plan -> execute the whole calibration against real exiftool + ImageMagick: two real photos get
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
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/T/a.jpg", "2024:07:03 14:00:00", 50.0, 4.0),
             rec("6-photos-by-dest/T/b.jpg", "2024:07:03 15:00:00", 51.0, 5.0)]
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))

    _run(monkeypatch, ws, "plan")
    p = ctl / "photos-21-time-decisions.json"; a = json.load(open(p))
    a["destinations"]["6-photos-by-dest/T"]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
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
