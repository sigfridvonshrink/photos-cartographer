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

import pytest
import os
import json
import shutil
import sqlite3
from unittest.mock import patch, MagicMock

# photos_1_prep is loaded once by conftest.py into sys.modules
import photos_1_prep as prep
import photos_utils as utils

requires_exiftool = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool not available"
)


@requires_exiftool
def test_exiftool_worker_registry_and_cleanup_close_dead_children_quietly(capfd):
    # A worker registers itself; close() deregisters it. cleanup_all() (the atexit hook) closes every
    # live worker. Crucially, closing a worker whose child has already died (an interrupted run) must
    # NOT leave a pipe to flush at GC — i.e. no "Exception ignored ... BrokenPipeError" noise.
    w = utils.PersistentExifToolWorker()
    assert w in utils.PersistentExifToolWorker._instances
    w.process.kill()                                  # simulate the child dying on a Ctrl-C
    utils.PersistentExifToolWorker.cleanup_all()      # what atexit runs at shutdown
    assert w.closed is True
    assert w not in utils.PersistentExifToolWorker._instances   # close(remove=True) deregistered it
    # The kill()'d child's broken stdin must have been closed cleanly — no deferred GC complaint.
    err = capfd.readouterr().err
    assert "Exception ignored" not in err and "BrokenPipe" not in err

@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".photos-ingest").mkdir(exist_ok=True); (root / ".photos-ingest" / "photos-00-workspace-guard").touch()

    # Create required folders
    (root / "0-sources").mkdir()
    (root / "1-strays").mkdir()
    (root / "2-missing-metadata").mkdir()
    (root / "3-redundant-jpgs").mkdir()
    (root / "4-videos-by-date").mkdir()
    (root / "5-photos-by-date").mkdir()
    (root / "6-photos-by-dest").mkdir()
    (root / "6-photos-by-dest" / "vacation").mkdir()

    yield root

def create_mock_metadata_reader(monkeypatch):
    # Mock the MetadataReader so we don't actually run exiftool
    def mock_read(folders, max_workers=4, progress_coordinator=None):
        # Need to return paths that match any folder passed in exactly
        res = {}
        for folder in folders:
            if "0-sources" in folder:
                res[os.path.join(folder, "photo.jpg")] = {
                    "DateTimeOriginal": "2023:01:01 12:00:00",
                    "Make": "Canon",
                    "Model": "EOS R5",
                    "SerialNumber": "12345",
                    "GPSLatitude": 45.0,
                    "GPSLongitude": -90.0,
                    "camera_group_key": "12345|Canon|EOS R5",
                    "has_native_gps": True,
                    "has_timestamp": True
                }
            if "vacation" in folder:
                res[os.path.join(folder, "2023-01-02--12-00-00.jpg")] = {
                    "DateTimeOriginal": "2023:01:02 12:00:00",
                    "Make": "Canon",
                    "Model": "EOS R5",
                    "SerialNumber": "12345",
                    "GPSLatitude": 45.0,
                    "GPSLongitude": -90.0,
                    "camera_group_key": "12345|Canon|EOS R5",
                    "has_native_gps": True,
                    "has_timestamp": True
                }
        return res, set()

    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", lambda *a, **k: {"status": "valid", "strategy": "image-content-hash-v1", "value": "dummycontenthash"})

@pytest.mark.spec("RUL-metadata_kept_for_geotag", "RUL-database_matches_files", "BLD-database_ops", test="TST-exif_metadata-metadata_cache_creation_and_staleness")
def test_metadata_cache_creation_and_staleness(workspace, monkeypatch):
    create_mock_metadata_reader(monkeypatch)

    # Create test file
    source_file = workspace / "0-sources" / "photo.jpg"
    source_file.write_text("dummy content")

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()

    # The file is in 0-sources, so it gets a move_no_clobber op, which carries the db_upsert
    move_ops = [op for op in plan.operations if op.type == "move_no_clobber"]
    assert len(move_ops) > 0
    upsert_fx = [fx for fx in move_ops[0].database_effects_after_verification if fx["action"] == "upsert"][0]

    assert "metadata" in upsert_fx["data"]
    assert upsert_fx["data"]["metadata"]["camera_group_key"] == "12345|Canon|EOS R5"
    assert upsert_fx["data"]["metadata"]["has_native_gps"] is True

    # Simulate execution updates cache
    cache.upsert_file(upsert_fx["data"])
    md_row = cache.conn.execute("SELECT * FROM metadata_cache WHERE relative_path = ?",
                                (upsert_fx["data"]["relative_path"],)).fetchone()
    assert md_row is not None
    assert md_row["camera_group_key"] == "12345|Canon|EOS R5"

    # In the test environment, the first plan just generates the operations. We need to execute the plan
    # to move the file physically to the destination (or rename it).
    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest/journal.json")
    executor.execute(plan, journal_path)

    # Change FIELD_SET_VERSION to simulate stale metadata and expect a refresh
    # photos-1-prep does an inline import `from photos_utils import FIELD_SET_VERSION`, so we must patch the module.
    import photos_utils as utils
    monkeypatch.setattr(utils, "FIELD_SET_VERSION", utils.FIELD_SET_VERSION + 1)
    # Replan without modifying the file (should still trigger metadata scan due to version mismatch)

    # Actually mock read to return updated metadata
    def mock_read_updated(folders, max_workers=4, progress_coordinator=None):
         return { upsert_fx["data"]["absolute_path"]: { "DateTimeOriginal": "2023:01:01 12:00:00", "Make": "Canon", "Model": "EOS R5", "SerialNumber": "12345", "camera_group_key": "12345|Canon|EOS R5", "has_native_gps": False, "has_timestamp": True } }, set()
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_updated)

    plan2 = workflow.plan()
    # The file has been moved (to 5-photos-by-date or 2-missing-metadata), so it will just get a pure db_upsert to update metadata cache.
    db_upserts2 = [op for op in plan2.operations if op.type == "db_upsert"]
    assert len(db_upserts2) > 0
    upsert_fx2 = [fx for fx in db_upserts2[0].database_effects_after_verification if fx["action"] == "upsert"][0]
    assert upsert_fx2["data"]["metadata"]["has_native_gps"] is False
    assert upsert_fx2["data"]["metadata"]["field_set_version"] == utils.FIELD_SET_VERSION

@pytest.mark.spec("RUL-grouping_facts_reported", "BLD-handoff_grouping_facts", test="TST-exif_metadata-handoff_manifest_enrichment")
def test_handoff_manifest_enrichment(workspace, monkeypatch):
    create_mock_metadata_reader(monkeypatch)

    # Create test files
    source_file = workspace / "0-sources" / "photo.jpg"
    source_file.write_text("dummy")

    dest_file = workspace / "6-photos-by-dest" / "vacation" / "2023-01-02--12-00-00.jpg"
    dest_file.write_text("dummy2")

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()

    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest/journal.json")
    executor.execute(plan, journal_path)

    handoff_path = workspace / ".photos-ingest" / "photos-11-handoff.json"
    assert handoff_path.exists()

    with open(handoff_path) as f:
        handoff = json.load(f)

    assert "metadata_extractor" in handoff["depends_on"]
    assert handoff["depends_on"]["metadata_extractor"]["name"] == "exiftool"
    assert "field_set_version" in handoff["depends_on"]["metadata_extractor"]
    assert "extraction_options_fingerprint" in handoff["depends_on"]["metadata_extractor"]
    assert handoff["depends_on"]["metadata_extractor"]["version"] == plan.metadata_dependencies["extractor_version"]
    assert handoff["depends_on"]["metadata_extractor"]["metadata_schema_version"] == getattr(plan, "metadata_dependencies", {}).get("metadata_schema_version", 1)

    assert len(handoff["camera_groups"]) == 1
    cg = handoff["camera_groups"][0]

    # The mock fingerprints both files alike, so the inbox photo is quarantined as a duplicate of the
    # by-dest one; a quarantined file leaves the database and the handoff.
    assert cg["files"] == ["6-photos-by-dest/vacation/2023-01-02--12-00-00.jpg"]
    assert cg["cache_freshness"]["total_files"] == 1
    assert cg["cache_freshness"]["metadata_extracted_ok"] == 1
    assert cg["cache_freshness"]["metadata_reused_from_cache"] == 0
    assert cg["group_key"] == "12345|Canon|EOS R5"
    assert cg["file_count"] == 1
    assert cg["has_native_gps"] == 1

    assert len(handoff["destination_folders"]) == 1
    df = handoff["destination_folders"][0]
    assert df["path"] == "6-photos-by-dest/vacation"
    assert df["scanned_files"] == 1
    assert "12345|Canon|EOS R5" in df["camera_groups"]
    assert df["cache_freshness"]["total_files"] == 1
    assert df["cache_freshness"]["metadata_extracted_ok"] == 1


@pytest.mark.spec("RUL-metadata_freshness", test="TST-exif_metadata-metadata_extractor_version_refreshes")
def test_metadata_extractor_version_refreshes(workspace, monkeypatch):
    create_mock_metadata_reader(monkeypatch)

    # Create test file
    source_file = workspace / "0-sources" / "photo.jpg"
    source_file.write_text("dummy content")

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()
    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest/journal.json")
    executor.execute(plan, journal_path)

    # Change exiftool version
    import photos_utils as utils
    monkeypatch.setattr(utils, "get_exiftool_version", lambda: "12.00")

    plan2 = workflow.plan()
    assert "reused_from_cache" not in plan2.summary.get("metadata_plan_status", {}).values()


def test_extraction_failure_is_extraction_failed(workspace, monkeypatch):
    import photos_utils as utils

    # Create test file
    source_file = workspace / "0-sources" / "photo.jpg"
    source_file.write_text("dummy content")

    # Mock read_metadata_concurrently to return empty dictionary (simulation of extraction failure)
    def mock_read_metadata_concurrently(folders, max_workers=4, progress_coordinator=None):
        return {}, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", lambda *a, **k: {"status": "valid", "strategy": "image-content-hash-v1", "value": "dummycontenthash"})

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()
    assert plan.summary.get("metadata_plan_status", {}).get("0-sources/photo.jpg") == "extraction_failed"

    # extraction failure now creates a blocker when there's no valid cache
    assert "Metadata extraction failed or returned empty for 0-sources/photo.jpg" in plan.warnings
    assert any("no valid cache exists" in b for b in plan.blockers)

    import pytest
    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest/journal.json")
    with pytest.raises(ValueError, match="Plan contains blockers"):
        executor.execute(plan, journal_path)

def test_non_media_is_not_applicable(workspace, monkeypatch):
    import photos_utils as utils
    source_file = workspace / "0-sources" / "document.txt"
    source_file.write_text("dummy content")

    def mock_read_metadata_concurrently(folders, max_workers=4, progress_coordinator=None):
        return {}, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()
    assert plan.summary.get("metadata_plan_status", {}).get("0-sources/document.txt") == "not_applicable"


@pytest.mark.spec("RUL-cache_schema_not_migrated", "BLD-cache_versions", test="TST-exif_metadata-a_database_of_another_schema_stops_prep")
def test_a_database_of_another_schema_stops_prep(workspace):
    """A workspace database recording a schema version not this build's stops prep's plan: it is never
    migrated."""
    cache = prep.WorkspaceCache(str(workspace))
    cache.set_meta("cache_schema_version", "999")
    cache.close()
    cache = prep.WorkspaceCache(str(workspace), read_only=True)
    with pytest.raises(ValueError, match="schema version 999"):
        prep.WorkspacePrepWorkflow(str(workspace), cache).plan()
    cache.close()


@pytest.mark.spec("RUL-recorded_time_order", test="TST-exif_metadata-parse_exiftool_item_timestamp_source_fallback")
def test_parse_exiftool_item_timestamp_source_fallback():
    """selected_source_naive_timestamp prefers DateTimeOriginal, then CreateDate, then ModifyDate,
    else None; its provenance names the group it came from."""
    import photos_utils as utils
    parse = utils.MetadataReader._parse_exiftool_item
    r = parse({"EXIF:DateTimeOriginal": "2020:01:01 00:00:00", "EXIF:CreateDate": "2019:09:09 09:09:09"})
    assert r["selected_source_timestamp_tag"] == "EXIF:DateTimeOriginal"
    assert r["selected_source_naive_timestamp"] == "2020:01:01 00:00:00"
    r = parse({"EXIF:CreateDate": "2019:09:09 09:09:09"})                # no DTO -> CreateDate
    assert r["selected_source_timestamp_tag"] == "EXIF:CreateDate"
    assert r["selected_source_naive_timestamp"] == "2019:09:09 09:09:09"
    r = parse({"QuickTime:ModifyDate": "2018:08:08 08:08:08"})           # only ModifyDate
    assert r["selected_source_timestamp_tag"] == "QuickTime:ModifyDate"
    assert r["selected_source_naive_timestamp"] == "2018:08:08 08:08:08"
    r = parse({})                                                        # no timestamp at all
    assert r["selected_source_naive_timestamp"] is None


@pytest.mark.spec("RUL-recorded_time_order", test="TST-exif_metadata-a_placeholder_time_does_not_hide_a_valid_one")
def test_a_placeholder_time_does_not_hide_a_valid_one():
    """A field present but holding no valid time is passed over for the next that holds one; a file whose
    fields all hold none has no recorded time."""
    import photos_utils as utils
    parse = utils.MetadataReader._parse_exiftool_item
    r = parse({"EXIF:DateTimeOriginal": "0000:00:00 00:00:00", "EXIF:CreateDate": "2019:09:09 09:09:09"})
    assert (r["selected_source_timestamp_tag"], r["selected_source_naive_timestamp"]) == ("EXIF:CreateDate", "2019:09:09 09:09:09")
    assert r["has_timestamp"] is True
    r = parse({"EXIF:DateTimeOriginal": "    :  :     :  :  ", "EXIF:ModifyDate": "garbage"})
    assert r["selected_source_naive_timestamp"] is None and r["has_timestamp"] is False


@pytest.mark.spec("RUL-metadata_group_order", "BLD-metadata_extraction",
                  test="TST-exif_metadata-a_field_is_taken_from_exif_then_xmp")
def test_a_field_is_taken_from_exif_then_xmp():
    """Each field is taken from EXIF when EXIF holds it, else from XMP; a time field missing or holding no
    valid time in EXIF is taken from the same field in XMP before the next field is tried. The GPS
    position is taken signed, from exiftool's Composite group."""
    import photos_utils as utils
    parse = utils.MetadataReader._parse_exiftool_item
    r = parse({"XMP:CreateDate": "2020:01:01 01:01:01", "EXIF:CreateDate": "2021:02:02 02:02:02",
               "XMP:Make": "XmpMake", "EXIF:Make": "ExifMake", "XMP:Model": "OnlyXmp"})
    assert (r["CreateDate"], r["Make"], r["Model"]) == ("2021:02:02 02:02:02", "ExifMake", "OnlyXmp")
    r = parse({"EXIF:DateTimeOriginal": "0000:00:00 00:00:00", "XMP:DateTimeOriginal": "2022:03:03 03:03:03",
               "EXIF:CreateDate": "2019:09:09 09:09:09"})
    assert (r["selected_source_timestamp_tag"], r["selected_source_naive_timestamp"]) == \
        ("XMP:DateTimeOriginal", "2022:03:03 03:03:03")
    r = parse({"EXIF:GPSLatitude": 33.5, "EXIF:GPSLatitudeRef": "S", "Composite:GPSLatitude": -33.5,
               "EXIF:GPSLongitude": 70.1, "Composite:GPSLongitude": -70.1})
    assert (r["GPSLatitude"], r["GPSLongitude"], r["GPSLatitudeRef"]) == (-33.5, -70.1, "S")
