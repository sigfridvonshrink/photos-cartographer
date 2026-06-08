import pytest
import os
import json
import sqlite3
from importlib.machinery import SourceFileLoader
from unittest.mock import patch, MagicMock

# Dynamically import the extensionless script
prep = SourceFileLoader("photos_1_prep", "ingest/photos-1-prep").load_module()

@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".photos-1-prep-root").touch()

    # Create required folders
    (root / "0-source").mkdir()
    (root / "1-missing-metadata").mkdir()
    (root / "2-redundant-jpgs").mkdir()
    (root / "3-videos-by-date").mkdir()
    (root / "4-photos-by-date").mkdir()
    (root / "5-photos-by-dest").mkdir()
    (root / "5-photos-by-dest" / "vacation").mkdir()

    yield root

def create_mock_metadata_reader(monkeypatch):
    # Mock the MetadataReader so we don't actually run exiftool
    def mock_read(folders, max_workers=4, progress_coordinator=None):
        # Need to return paths that match any folder passed in exactly
        res = {}
        for folder in folders:
            if "0-source" in folder:
                res[os.path.join(folder, "photo.jpg")] = {
                    "DateTimeOriginal": "2023:01:01 12:00:00",
                    "Make": "Canon",
                    "Model": "EOS R5",
                    "SerialNumber": "12345",
                    "GPSLatitude": 45.0,
                    "GPSLongitude": -90.0,
                    "camera_group_key": "12345|Canon|EOS R5",
                    "has_native_gps": True,
                    "has_timestamp": True,
                    "raw_payload": "{}"
                }
            if "vacation" in folder:
                res[os.path.join(folder, "photo2.jpg")] = {
                    "DateTimeOriginal": "2023:01:02 12:00:00",
                    "Make": "Canon",
                    "Model": "EOS R5",
                    "SerialNumber": "12345",
                    "GPSLatitude": 45.0,
                    "GPSLongitude": -90.0,
                    "camera_group_key": "12345|Canon|EOS R5",
                    "has_native_gps": True,
                    "has_timestamp": True,
                    "raw_payload": "{}"
                }
        return res, set()

    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read)
    monkeypatch.setattr(prep.ContentHasher, "hash_file", lambda *a, **k: {"status": "valid", "strategy": "sha256-v1", "value": "dummyhash"})
    monkeypatch.setattr(prep.ContentHasher, "hash_image", lambda *a, **k: {"status": "valid", "strategy": "image-content-hash-v1", "value": "dummycontenthash"})

def test_metadata_cache_creation_and_staleness(workspace, monkeypatch):
    create_mock_metadata_reader(monkeypatch)

    # Create test file
    source_file = workspace / "0-source" / "photo.jpg"
    source_file.write_text("dummy content")

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()

    # The file is in 0-source, so it gets a move_no_clobber op, which carries the db_upsert
    move_ops = [op for op in plan.operations if op.type == "move_no_clobber"]
    assert len(move_ops) > 0
    upsert_fx = [fx for fx in move_ops[0].database_effects_after_verification if fx["action"] == "upsert"][0]

    assert "metadata" in upsert_fx["data"]
    assert upsert_fx["data"]["metadata"]["camera_group_key"] == "12345|Canon|EOS R5"
    assert upsert_fx["data"]["metadata"]["has_native_gps"] is True

    # Simulate execution updates cache
    cache.upsert_file(upsert_fx["data"])
    md_row = cache.get_metadata(upsert_fx["data"]["relative_path"])
    assert md_row is not None
    assert md_row["camera_group_key"] == "12345|Canon|EOS R5"

    # In the test environment, the first plan just generates the operations. We need to execute the plan
    # to move the file physically to the destination (or rename it).
    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest-journal.json")
    executor.execute(plan, journal_path)

    # Change FIELD_SET_VERSION to simulate stale metadata and expect a refresh
    # photos-1-prep does an inline import `from photos_utils import FIELD_SET_VERSION`, so we must patch the module.
    import photos_utils as utils
    monkeypatch.setattr(utils, "FIELD_SET_VERSION", 2)
    # Replan without modifying the file (should still trigger metadata scan due to version mismatch)

    # Actually mock read to return updated metadata
    def mock_read_updated(folders, max_workers=4, progress_coordinator=None):
         return { upsert_fx["data"]["absolute_path"]: { "DateTimeOriginal": "2023:01:01 12:00:00", "Make": "Canon", "Model": "EOS R5", "SerialNumber": "12345", "camera_group_key": "12345|Canon|EOS R5", "has_native_gps": False, "has_timestamp": True, "raw_payload": "{}" } }, set()
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_updated)

    plan2 = workflow.plan()
    # The file has been moved (to 4-photos-by-date or 1-missing-metadata), so it will just get a pure db_upsert to update metadata cache.
    db_upserts2 = [op for op in plan2.operations if op.type == "db_upsert"]
    assert len(db_upserts2) > 0
    upsert_fx2 = [fx for fx in db_upserts2[0].database_effects_after_verification if fx["action"] == "upsert"][0]
    assert upsert_fx2["data"]["metadata"]["has_native_gps"] is False
    assert upsert_fx2["data"]["metadata"]["field_set_version"] == 2

def test_handoff_manifest_enrichment(workspace, monkeypatch):
    create_mock_metadata_reader(monkeypatch)

    # Create test files
    source_file = workspace / "0-source" / "photo.jpg"
    source_file.write_text("dummy")

    dest_file = workspace / "5-photos-by-dest" / "vacation" / "photo2.jpg"
    dest_file.write_text("dummy2")

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()

    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest-journal.json")
    executor.execute(plan, journal_path)

    handoff_path = workspace / ".photos-ingest" / "photos-1-prep-handoff.json"
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

    # 0-source gets moved to 1-missing-metadata normally, but here it's got no gps so maybe just 1-missing-metadata
    # Actually wait, why did it go to quarantine? Because it's an exact duplicate of the content_hash returned by the mock.
    # We should look at whatever files are actually in cg["files"], but they are sorted correctly.
    assert len(cg["files"]) == 2
    assert cg["files"] == sorted(cg["files"])
    assert cg["cache_freshness"]["total_files"] == 2
    assert cg["cache_freshness"]["metadata_extracted_ok"] == 2
    assert cg["cache_freshness"]["metadata_reused_from_cache"] == 0
    assert cg["group_key"] == "12345|Canon|EOS R5"
    assert cg["file_count"] == 2
    assert cg["has_native_gps"] == 2

    assert len(handoff["destination_folders"]) == 1
    df = handoff["destination_folders"][0]
    assert df["path"] == "5-photos-by-dest/vacation"
    assert df["scanned_files"] == 1
    assert "12345|Canon|EOS R5" in df["camera_groups"]
    assert df["cache_freshness"]["total_files"] == 1
    assert df["cache_freshness"]["metadata_extracted_ok"] == 1


def test_metadata_extractor_version_refreshes(workspace, monkeypatch):
    create_mock_metadata_reader(monkeypatch)

    # Create test file
    source_file = workspace / "0-source" / "photo.jpg"
    source_file.write_text("dummy content")

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()
    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest-journal.json")
    executor.execute(plan, journal_path)

    # Change exiftool version
    import photos_utils as utils
    monkeypatch.setattr(utils, "get_exiftool_version", lambda: "12.00")

    plan2 = workflow.plan()
    assert "reused_from_cache" not in plan2.summary.get("metadata_plan_status", {}).values()


def test_extraction_failure_is_extraction_failed(workspace, monkeypatch):
    import photos_utils as utils

    # Create test file
    source_file = workspace / "0-source" / "photo.jpg"
    source_file.write_text("dummy content")

    # Mock read_metadata_concurrently to return empty dictionary (simulation of extraction failure)
    def mock_read_metadata_concurrently(folders, max_workers=4, progress_coordinator=None):
        return {}, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(prep.ContentHasher, "hash_file", lambda *a, **k: {"status": "valid", "strategy": "sha256-v1", "value": "dummyhash"})
    monkeypatch.setattr(prep.ContentHasher, "hash_image", lambda *a, **k: {"status": "valid", "strategy": "image-content-hash-v1", "value": "dummycontenthash"})

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()
    assert plan.summary.get("metadata_plan_status", {}).get("0-source/photo.jpg") == "extraction_failed"

    # extraction failure now creates a blocker when there's no valid cache
    assert "Metadata extraction failed or returned empty for 0-source/photo.jpg" in plan.warnings
    assert any("no valid cache exists" in b for b in plan.blockers)

    import pytest
    executor = prep.PlanExecutor(str(workspace))
    journal_path = str(workspace / ".photos-ingest-journal.json")
    with pytest.raises(ValueError, match="Plan contains blockers"):
        executor.execute(plan, journal_path)

def test_non_media_is_not_applicable(workspace, monkeypatch):
    import photos_utils as utils
    source_file = workspace / "0-source" / "document.txt"
    source_file.write_text("dummy content")

    def mock_read_metadata_concurrently(folders, max_workers=4, progress_coordinator=None):
        return {}, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)
    workflow = prep.WorkspacePrepWorkflow(str(workspace), cache)

    plan = workflow.plan()
    assert plan.summary.get("metadata_plan_status", {}).get("0-source/document.txt") == "not_applicable"


def test_schema_migration(workspace):
    import sqlite3
    db_path = workspace / ".photos_ingest.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute('''
        CREATE TABLE file_cache (
            relative_path TEXT PRIMARY KEY,
            absolute_path TEXT,
            size INTEGER,
            mtime_ns INTEGER,
            inode INTEGER,
            media_class TEXT,
            hash TEXT,
            content_hash TEXT,
            last_seen_ns INTEGER
        )
    ''')
    conn.execute('''
        CREATE TABLE metadata_cache (
            relative_path TEXT PRIMARY KEY,
            size INTEGER,
            mtime_ns INTEGER,
            content_hash TEXT,
            extractor TEXT,
            extractor_version TEXT,
            field_set_version INTEGER,
            extraction_options_fingerprint TEXT,
            camera_group_key TEXT,
            has_native_gps INTEGER,
            has_timestamp INTEGER,
            parsed_json TEXT,
            raw_payload TEXT,
            FOREIGN KEY(relative_path) REFERENCES file_cache(relative_path) ON DELETE CASCADE
        )
    ''')
    conn.execute('''
        INSERT INTO file_cache (relative_path, size, mtime_ns) VALUES ('test.jpg', 123, 456)
    ''')
    conn.commit()
    conn.close()

    cache = prep.WorkspaceCache(str(workspace), in_memory=False)

    # Assert missing columns were added by schema migration
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(metadata_cache)")
    columns = {row[1] for row in cur.fetchall()}
    conn.close()

    assert "metadata_schema_version" in columns
    assert "camera_group_key_version" in columns
    assert "extraction_status" in columns
    assert "extraction_error" in columns

    # Verify upsert succeeds without 'no such column' error
    data = {
        "relative_path": "test.jpg",
        "absolute_path": "/fake/path/test.jpg",
        "size": 123,
        "mtime_ns": 456,
        "inode": 1,
        "media_class": "image",
        "hash": None,
        "content_hash": None,
        "last_seen_ns": 12345,
        "metadata": {
            "extractor": "exiftool",
            "extractor_version": "1.0",
            "field_set_version": 1,
            "extraction_options_fingerprint": "hash",
            "metadata_schema_version": 1,
            "camera_group_key_version": 1,
            "camera_group_key": "cam",
            "has_native_gps": False,
            "has_timestamp": True,
            "extraction_status": "extracted_ok",
            "extraction_error": None,
            "parsed_json": "{}",
            "raw_payload": "{}"
        }
    }
    cache.upsert_file(data)
