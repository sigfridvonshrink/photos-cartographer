"""Phase 11 — real end-to-end run with NO mocks (slow).

Every other test mocks hashing and metadata; this one runs the real persistent-worker
exiftool pool (MetadataReader.read_metadata_concurrently + ExiftoolWorker / the {ready}
handshake) and the real ImageMagick content hasher against a real fixture, so that code
path is actually exercised. Needs exiftool + ImageMagick (present in CI and locally); the
pre-push hook skips `slow`.
"""
import glob
import json
import os
import shutil

import pytest

import photos_1_prep as prep
import photos_utils as utils

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "cam_small.jpg")


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-source", "1-missing-metadata", "2-redundant-jpgs",
              "3-videos-by-date", "4-photos-by-date", "5-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


@pytest.mark.slow
def test_real_exiftool_and_magick_end_to_end(tmp_path):
    prep.CONFIG["zfs"] = {"enabled": False}     # no snapshot shell-out
    prep.CONFIG["jobs"] = 2
    ws = _ws(tmp_path)
    shutil.copy(FIX, ws / "0-source" / "photo.jpg")

    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()   # real exiftool + real magick
    cache.close()
    assert not plan.blockers, plan.blockers
    prep.PlanExecutor(str(ws)).execute(plan)

    organized = glob.glob(str(ws / "4-photos-by-date" / "*.jpg"))
    assert len(organized) == 1, organized
    rel = os.path.relpath(organized[0], str(ws))
    # the spec naming derives from the real DateTimeOriginal (2026:05:15 11:32:29)
    assert os.path.basename(organized[0]).startswith("2026-05-15--11-32-29")

    md = prep.WorkspaceCache(str(ws)).get_all_metadata()[rel]
    assert md["has_timestamp"] == 1
    assert md["camera_group_key"] and md["camera_group_key"] != "unknown"
    assert "SONY" in md["camera_group_key"]                   # real Make from EXIF
    parsed = json.loads(md["parsed_json"])
    assert parsed.get("DateTimeOriginal")

    # the real content hash backs the file_cache row
    fc = prep.WorkspaceCache(str(ws)).get_all_files()[rel]
    assert fc["content_hash"]

    handoff = json.load(open(utils.handoff_path(str(ws))))
    assert any(f["relative_path"] == rel for f in handoff["files"])
