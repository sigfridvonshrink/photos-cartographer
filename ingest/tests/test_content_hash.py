"""Un-mocked tests for the real content hash and config-driven naming.

These exercise the actual `ContentHasher.fingerprint_image` (ImageMagick pixel signature),
real EXIF extraction, and the config-driven filename format against the real fixtures
in ``ingest/tests/fixtures/`` — the coverage that was missing while `fingerprint_image` was a
stub and the tests mocked around it.

Most tests use a small real-derived JPEG (`cam_small.jpg`, a downscaled DSC0020.JPG with
its EXIF preserved) so they stay fast while still going through real `magick`/`exiftool`.
The two tests that prove full-size and RAW decoding use the original 17/30 MB fixtures and
are marked ``slow`` so the local pre-push hook can skip them; CI runs the full suite.

photos_1_prep / photos_utils are loaded once by conftest.py into sys.modules.
"""
import os
import shutil
import subprocess

import pytest

import photos_1_prep as prep
import photos_utils as utils

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
CAM_JPG = os.path.join(FIXTURES, "DSC0020.JPG")              # full-size Sony A6700 JPEG
CAM_RAW = os.path.join(FIXTURES, "DSC0020.ARW")              # its RAW sibling (same basename)
CAM_SMALL = os.path.join(FIXTURES, "cam_small.jpg")          # downscaled DSC0020.JPG, real EXIF
PHONE_JPG = os.path.join(FIXTURES, "IMG20260608211806.jpg")  # OnePlus phone, different scene

requires_magick = pytest.mark.skipif(
    not utils.get_identify_command(), reason="ImageMagick (magick/identify) not available"
)
requires_exiftool = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool not available"
)


def _make_ws(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _dests(plan):
    return [op.destination for op in plan.operations if op.destination]


# --- the pixel-signature hasher itself ---------------------------------------

@pytest.mark.slow
@requires_magick
def test_hash_image_valid_on_real_fullsize_jpeg_and_raw():
    # Proves the real full-size JPEG and the real Sony RAW both decode to a stable,
    # version-bound signature. Slow (30 MB RAW decode); CI runs it, pre-push skips it.
    # The full-size JPEG must always decode where magick is present (this catches a
    # broken fingerprint_image); the RAW part is skipped only if this magick build lacks RAW
    # (libraw) support, so a minimal CI image is tolerated rather than reported red.
    jpg = prep.ContentHasher.fingerprint_image(CAM_JPG)
    assert jpg["status"] == "valid", jpg
    assert jpg["value"] and jpg.get("engine_version")
    raw = prep.ContentHasher.fingerprint_image(CAM_RAW)
    if raw["status"] != "valid":
        pytest.skip(f"ImageMagick lacks RAW decode support here: {raw.get('error')}")
    assert raw["value"]
    assert raw["strategy"] == "image-content-hash-v1"
    assert raw.get("engine_version")


@requires_magick
def test_hash_image_valid_and_version_bound():
    r = prep.ContentHasher.fingerprint_image(CAM_SMALL)
    assert r["status"] == "valid" and r["value"]
    assert r["strategy"] == "image-content-hash-v1"
    assert r.get("engine_version")


@requires_magick
def test_pixel_signature_distinct_for_different_photos():
    a = prep.ContentHasher.fingerprint_image(CAM_SMALL)["value"]
    b = prep.ContentHasher.fingerprint_image(PHONE_JPG)["value"]
    assert a and b and a != b


@requires_magick
@requires_exiftool
def test_pixel_signature_is_exif_invariant(tmp_path):
    # Copy the JPEG, mutate EXIF (date + GPS) on the copy without touching pixels;
    # the pixel signature must be unchanged. This is the property calibration relies
    # on (the content hash survives EXIF writes).
    variant = tmp_path / "variant.jpg"
    shutil.copy(CAM_SMALL, variant)
    subprocess.run(
        ["exiftool", "-overwrite_original",
         "-DateTimeOriginal=2099:12:31 23:59:59",
         "-GPSLatitude=12.3456", "-GPSLatitudeRef=N",
         "-GPSLongitude=65.4321", "-GPSLongitudeRef=E",
         str(variant)],
        check=True, capture_output=True,
    )
    original = prep.ContentHasher.fingerprint_image(CAM_SMALL)
    edited = prep.ContentHasher.fingerprint_image(str(variant))
    assert original["status"] == "valid" and edited["status"] == "valid"
    assert original["value"] == edited["value"], "pixel signature changed after an EXIF-only edit"


def test_hash_image_failure_is_recorded_when_magick_absent(monkeypatch):
    # Simulate ImageMagick missing: fingerprint_image must return a clean failure record
    # (which the §6.2/§11.3 blocker path keys on), still version-stamped.
    monkeypatch.setattr(utils, "get_magick_command", lambda: [])      # no persistent worker
    monkeypatch.setattr(utils, "get_identify_command", lambda: [])    # no legacy fallback either
    r = prep.ContentHasher.fingerprint_image(CAM_SMALL)
    assert r["status"] == "failed"
    assert r["value"] is None
    assert "engine_version" in r


# --- end-to-end planning against real photos ---------------------------------

@requires_magick
@requires_exiftool
def test_real_jpeg_organizes_with_spec_filename_and_no_blocker(tmp_path):
    ws = _make_ws(tmp_path)
    shutil.copy(CAM_SMALL, ws / "0-sources" / "cam.jpg")
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws), in_memory=True)
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    # The whole point of Phase 0: a real photo no longer produces a spurious
    # hash-failure blocker.
    assert plan.blockers == [], plan.blockers
    # DateTimeOriginal 2026:05:15 11:32:29 -> spec-shaped by-date name.
    assert any(
        d.startswith("5-photos-by-date/2026-05-15/2026-05-15--11-32-29") and d.endswith(".jpg")
        for d in _dests(plan)
    ), _dests(plan)


@requires_magick
@requires_exiftool
def test_unreadable_image_blocks_with_hash_failure(tmp_path):
    # Negative path: a file that magick cannot decode must surface a §6.2/§11.3
    # hash-failure blocker, not silently pass.
    ws = _make_ws(tmp_path)
    (ws / "0-sources" / "broken.jpg").write_bytes(b"this is not a real jpeg")
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws), in_memory=True)
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert plan.blockers, "an unreadable image must block, not silently pass"
    assert any("hash failure" in b.lower() and "broken.jpg" in b.lower() for b in plan.blockers), plan.blockers


@requires_magick
@requires_exiftool
def test_byte_identical_images_dedup_with_real_hasher(tmp_path):
    ws = _make_ws(tmp_path)
    shutil.copy(CAM_SMALL, ws / "0-sources" / "a.jpg")
    shutil.copy(CAM_SMALL, ws / "0-sources" / "b.jpg")  # identical pixels & bytes
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws), in_memory=True)
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert plan.blockers == [], plan.blockers
    quarantines = [op for op in plan.operations if op.type == "quarantine_move"]
    assert len(quarantines) == 1, [op.type for op in plan.operations]


@pytest.mark.slow
@requires_magick
@requires_exiftool
def test_raw_jpeg_pair_separates_redundant_jpeg(tmp_path):
    # Uses the real RAW (slow). The JPEG sibling only needs the same basename.
    if prep.ContentHasher.fingerprint_image(CAM_RAW)["status"] != "valid":
        pytest.skip("ImageMagick lacks RAW decode support here")
    ws = _make_ws(tmp_path)
    shutil.copy(CAM_RAW, ws / "0-sources" / "DSC0020.ARW")
    shutil.copy(CAM_SMALL, ws / "0-sources" / "DSC0020.JPG")
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws), in_memory=True)
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert plan.blockers == [], plan.blockers
    dests = _dests(plan)
    assert any(d.startswith("3-redundant-jpgs/") for d in dests), dests  # JPEG sibling is redundant
    assert any(
        d.startswith("5-photos-by-date/2026-05-15/2026-05-15--11-32-29") and d.endswith(".arw")
        for d in dests
    ), dests  # RAW retained + organized


# --- config-driven filename format (no external tools needed) ----------------

def test_filename_format_is_config_driven(tmp_path, monkeypatch):
    ws = _make_ws(tmp_path)
    monkeypatch.setattr(
        prep.ContentHasher, "fingerprint_image",
        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                   "value": "sig-" + os.path.basename(p), "engine_version": "test"},
    )

    def fake_meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:03:04 05:06:07",
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", fake_meta)
    (ws / "0-sources" / "x.jpg").write_text("xdata")
    prep.CONFIG["jobs"] = 1
    prep.CONFIG["filename_timestamp_format"] = "%Y%m%d__%H%M%S"  # custom shape (conftest restores CONFIG)

    cache = prep.WorkspaceCache(str(ws), in_memory=True)
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert any("5-photos-by-date/2023-03-04/20230304__050607" in d for d in _dests(plan)), _dests(plan)


@requires_magick
def test_content_hash_restaled_on_imagemagick_version_change(tmp_path, monkeypatch):
    # A cached image content hash recorded under one ImageMagick version must be
    # recomputed when the current version differs (version-binding).
    ws = _make_ws(tmp_path)
    shutil.copy(CAM_SMALL, ws / "0-sources" / "cam.jpg")
    prep.CONFIG["jobs"] = 1

    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "im-OLD")
    cache = prep.WorkspaceCache(str(ws), in_memory=False)
    plan1 = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    prep.PlanExecutor(str(ws)).execute(plan1, str(ws / ".photos-ingest/journal.json"))

    # Same workspace, newer magick -> the image content hash is stale and recomputed.
    # Planning is non-mutating, so execute plan2 to persist the recompute before reading the cache.
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "im-NEW")
    cache2 = prep.WorkspaceCache(str(ws), in_memory=False)
    plan2 = prep.WorkspacePrepWorkflow(str(ws), cache2).plan()
    assert any(op.type == "db_upsert" for op in plan2.operations), \
        "version change should restale the content hash and plan a db_upsert"
    prep.PlanExecutor(str(ws)).execute(plan2, str(ws / ".journal2.json"))

    cache3 = prep.WorkspaceCache(str(ws), in_memory=False)
    rows = cache3.get_all_files()
    row = next((v for k, v in rows.items() if k.endswith(".jpg")), None)
    assert row is not None
    import json as _json
    assert _json.loads(row["content_hash"])["engine_version"] == "im-NEW"


def test_fingerprint_video_uses_nostdin_and_detaches_stdin(monkeypatch):
    """Regression: ffmpeg must run with -nostdin AND a detached stdin, so it never grabs the
    controlling TTY (switching it to no-echo and leaving typed characters invisible)."""
    seen = {}

    class _R:
        returncode = 0
        stdout = "MD5=deadbeef\n"
        stderr = ""

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return _R()

    monkeypatch.setattr(utils.subprocess, "run", _run)
    res = utils.ContentHasher.fingerprint_video("/some/clip.mp4")
    assert res["status"] == "valid" and res["value"] == "deadbeef"
    assert "-nostdin" in seen["cmd"], seen["cmd"]
    assert seen["kw"].get("stdin") == subprocess.DEVNULL, seen["kw"]
