"""Phase 5a — the §19 user-visible run report + media-class helper.

Mocked hashing/metadata (content-based hash so identical files dedup), fast.
photos_1_prep / photos_utils come from conftest.py.
"""
import glob
import os

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock(monkeypatch):
    def spy(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", spy)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "camera_group_key": "test-cam",
                    "has_native_gps": False,
                    "has_timestamp": True,
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def test_media_class_for_ext():
    assert utils.media_class_for_ext("JPG") == "image"
    assert utils.media_class_for_ext(".arw") == "raw"
    assert utils.media_class_for_ext("mp4") == "video"
    assert utils.media_class_for_ext("txt") == "other"
    assert utils.media_class_for_ext("") == "other"


def test_report_has_expected_counts(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "new.jpg").write_bytes(b"NEW")
    (ws / "0-sources" / "dupA.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "dupB.jpg").write_bytes(b"SAME")   # one of the pair is quarantined
    r = _plan(ws).summary["report"]
    assert r["media_operations"] >= 1
    assert r["duplicates_against_mutable"] == 1
    assert r["duplicates_against_by_dest"] == 0
    assert r["camera_groups_found"] == 1
    assert "quarantine_footprint" in r
    assert r["extractor"] == "exiftool"


def test_duplicate_split_against_by_dest(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "keep.jpg").write_bytes(b"SAME")   # retained by-dest copy
    (ws / "0-sources" / "dup.jpg").write_bytes(b"SAME")           # mutable duplicate
    r = _plan(ws).summary["report"]
    assert r["duplicates_against_by_dest"] == 1
    assert r["duplicates_against_mutable"] == 0
    assert r["by_dest_files_scanned_read_only"] == 1
    assert r["by_dest_mutated"] == 0


def test_recognized_move_counted_in_report(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    cache = prep.WorkspaceCache(str(ws))
    p1 = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(p1)
    org = glob.glob(str(ws / "5-photos-by-date" / "*.jpg"))[0]
    (ws / "6-photos-by-dest" / "T").mkdir(parents=True)
    os.rename(org, ws / "6-photos-by-dest" / "T" / os.path.basename(org))
    p2 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    assert p2.summary["report"]["recognized_moves"] == 1


def test_print_summary_renders_categories(capsys):
    coord = utils.ProgressCoordinator(quiet=False)
    summary = {
        "report": {
            "media_operations": 3, "cache_operations": 1, "no_op_already_correct": 2,
            "recognized_moves": 1, "by_dest_files_scanned_read_only": 4, "by_dest_mutated": 0,
            "duplicates_against_mutable": 1, "duplicates_against_by_dest": 1,
            "metadata_reused": 2, "metadata_extracted": 3, "metadata_carried_forward": 1,
            "metadata_failed": 0, "camera_groups_found": 2, "native_gps_files": 1,
            "missing_timestamp_files": 0, "blockers": 0, "warnings": 1,
            "quarantine_footprint": {"total_files": 1, "total_bytes": 10, "plan_id_dirs": 1},
            "extractor": "exiftool", "extractor_version": "12.0", "field_set_version": 1,
        },
        "performance_and_cache": {"dependency_validation_status": "success",
                                  "handoff_written_after_successful_validation": True,
                                  "db_upserts_applied": 5, "db_removes_applied": 1, "db_renames_applied": 0},
    }
    coord.print_summary(plan_summary=summary)
    err = capsys.readouterr().err
    for label in ("Prep run summary", "Media operations", "Recognized moves",
                  "Duplicates", "Camera groups", "Quarantine footprint", "Dependency validation"):
        assert label in err, err
