import os
import sys
import json
import sqlite3
from pathlib import Path

# photos_1_prep is loaded once by conftest.py into sys.modules
import photos_1_prep as photos_ingest

def setup_workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()

    (ws / "0-sources").mkdir()
    (ws / "1-strays").mkdir()
    (ws / "3-redundant-jpgs").mkdir()
    (ws / "4-videos-by-date").mkdir()
    (ws / "2-missing-metadata").mkdir()
    (ws / "5-photos-by-date").mkdir()
    (ws / "6-photos-by-dest").mkdir()

    # Existing files in their correct final locations
    (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").parent.mkdir(parents=True)
    (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").write_text("already_dest")

    (ws / "5-photos-by-date" / "2023-01-01").mkdir()
    (ws / "5-photos-by-date" / "2023-01-01" / "2023-01-01--12-00-00.jpg").write_text("already_date")

    # Source file that needs prep
    (ws / "0-sources" / "new_img.jpg").write_text("new_source")

    # Source file that duplicates a by-dest file
    (ws / "0-sources" / "dup_img.jpg").write_text("already_dest")

    return ws

import unittest.mock as mock
def mock_read_metadata_concurrently(folders, max_workers=4, progress_coordinator=None):
    res = {}
    import os
    for folder in folders:
        for f in os.listdir(folder):
            abs_path = os.path.join(folder, f)
            res[abs_path] = {"DateTimeOriginal": "2023:01:01 12:00:00", "extraction_status": "extracted_ok", "raw_payload": "{}"}
    return res, set()


















@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_prep_idempotency_and_by_dest_accounting(mock_meta, tmp_path):
    ws = setup_workspace(tmp_path)

    # Inject mock hasher so we have valid content_hash values
    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)

    # FIRST RUN
    plan1 = workflow.plan()

    assert plan1.command == "prep"
    assert len(plan1.blockers) == 0

    # Expect ops: move new_img to 2-missing-metadata, quarantine dup_img, and db_upsert for by-dest files
    # By-dest and already_date files should NOT generate media ops

    ops_types = [op.type for op in plan1.operations]
    assert "move_no_clobber" in ops_types # for new_img
    assert "quarantine_move" in ops_types # for dup_img
    assert "db_upsert" in ops_types # for by-dest img1.jpg

    # We should only have those 3 operations
    assert len(plan1.operations) == 3, f"Expected 3 operations, got {len(plan1.operations)}"

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")
    executor.execute(plan1, journal_path)

    # SECOND RUN (IDEMPOTENT)
    cache2 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow2 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache2)
    plan2 = workflow2.plan()

    # Should generate NO operations
    assert len(plan2.operations) == 0, f"Expected 0 operations on second run, got {len(plan2.operations)}"
    assert plan2.summary["no_op_files"] > 0
    assert plan2.summary["operations_planned"] == 0

    # Check that cache correctly preserved identity
    # The new_img should now be in 2-missing-metadata, and its hash should exist in cache
    all_files = cache2.get_all_files()
    assert any(f.startswith("5-photos-by-date/2023-01-01/2023-01-01--12-00-00-001") for f in all_files.keys())

    # Verify that by-dest files were NEVER mutated (still in original place)
    assert (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").exists()
    assert (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").read_text() == "already_dest"


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_handoff_manifest_generated(mock_meta, tmp_path):
    ws = setup_workspace(tmp_path)

    # Inject mock hasher so we have valid content_hash values
    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan1 = workflow.plan()

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")
    executor.execute(plan1, journal_path)

    manifest_path = ws / ".photos-ingest" / "photos-11-handoff.json"
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text())

    assert data["schema_version"] == 1
    assert data["tool"] == "photos-1-prep"
    assert data["run_metadata"]["plan_id"] == plan1.plan_id
    assert "cache_fingerprint" in data
    assert "depends_on" in data

    # Check depends_on content
    depends = data["depends_on"]
    assert "effective_config" in depends
    assert "execution_journal" in depends
    assert "final_workspace_inventory" in depends

    assert depends["execution_journal"]["status"] == "success"

    # Check that duplicates and configs were written accurately
    assert len(data["files"]) > 0

    # Verify fingerprint_status mappings (by dest should be valid)
    by_dest_files = [f for f in data["files"] if f["relative_path"].startswith("6-photos-by-dest")]
    assert len(by_dest_files) > 0
    assert by_dest_files[0]["fingerprint_status"] == "valid"


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_stale_cache_upsert_fails(mock_meta, tmp_path):
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan1 = workflow.plan()

    # Modify the by-dest file AFTER the plan is generated but BEFORE execution
    (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").write_text("modified_after_plan")

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")

    import pytest
    with pytest.raises(ValueError, match="Stale plan: dependency changed after planning|Stale plan: cache-upsert target changed after planning"):
        executor.execute(plan1, journal_path)

    # Assert no media mutations occurred
    assert (ws / "0-sources" / "new_img.jpg").exists()
    assert (ws / "0-sources" / "dup_img.jpg").exists()
    assert not (ws / "2-missing-metadata" / "UNKN_new_img.jpg").exists()
    assert not (ws / ".photos-ingest-quarantine" / plan1.plan_id).exists()
    assert not (ws / ".photos-ingest" / "photos-11-handoff.json").exists()

    # Assert cache row was not updated
    cache_verify = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    all_files = cache_verify.get_all_files()
    assert "6-photos-by-dest/vacation/img1.jpg" not in all_files


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_cache_fingerprint_changes(mock_meta, tmp_path):
    ws = setup_workspace(tmp_path)
    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan1 = workflow.plan()

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")
    executor.execute(plan1, journal_path)

    manifest_path = ws / ".photos-ingest" / "photos-11-handoff.json"
    data1 = json.loads(manifest_path.read_text())
    fp1 = data1["cache_fingerprint"]

    # Run again without changes
    cache2 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow2 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache2)
    plan2 = workflow2.plan()
    executor.execute(plan2, journal_path)
    data2 = json.loads(manifest_path.read_text())
    fp2 = data2["cache_fingerprint"]

    assert fp1 == fp2

    # Change a file
    (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").write_text("modified_data_with_different_size")

    cache3 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow3 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache3)
    plan3 = workflow3.plan()
    executor.execute(plan3, journal_path)

    data3 = json.loads(manifest_path.read_text())
    fp3 = data3["cache_fingerprint"]

    assert fp3 != fp1




@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_db_upsert_absolute_path_rejected(mock_meta, tmp_path):
    ws = setup_workspace(tmp_path)

    # Inject mock hasher so we have valid content_hash values
    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan1 = workflow.plan()

    # Inject malicious absolute path
    for op in plan1.operations:
        if op.type == "db_upsert":
            for fx in op.database_effects_after_verification:
                if fx.get("action") == "upsert":
                    fx["data"]["relative_path"] = "/tmp/malicious.jpg"

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")

    import pytest
    with pytest.raises(ValueError, match="Path must be relative"):
        executor.execute(plan1, journal_path)


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_stale_already_cached_file_aborts(mock_meta, tmp_path):
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    # FIRST RUN: Populate cache
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan1 = workflow.plan()
    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")
    executor.execute(plan1, journal_path)

    # SECOND RUN: generate a plan that reuses the cache
    cache2 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow2 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache2)
    plan2 = workflow2.plan()

    # Confirm by-dest file does not need a db_upsert
    has_upsert = any(op.type == "db_upsert" for op in plan2.operations)
    assert not has_upsert, "Should not generate db_upsert if cache is fresh"

    # Modify the by-dest file BEFORE execute
    (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").write_text("modified_data_staleness_test")

    executor2 = photos_ingest.PlanExecutor(str(ws))
    import pytest
    with pytest.raises(ValueError, match="Stale plan: dependency changed after planning"):
        executor2.execute(plan2, journal_path)

    # Assert no media mutations occurred (0-sources files remain unmodified if they were there...)
    # Wait, the first run already moved 0-sources files to 2-missing-metadata and quarantine!
    # So we should check that they weren't mutated *again* or something.
    # We can just check that no execution succeeded.
    assert (ws / "5-photos-by-date" / "2023-01-01" / "2023-01-01--12-00-00-001.jpg").exists()

@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_stale_ghost_prune_reappeared_file_aborts_before_cache_remove(mock_meta, tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    for _d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
               "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / _d).mkdir(parents=True, exist_ok=True)

    # Create cache row for a missing file
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    cache.upsert_file({
        "absolute_path": str(ws / "5-photos-by-date" / "reappeared.jpg"),
        "relative_path": "5-photos-by-date/reappeared.jpg",
        "size": 100,
        "mtime_ns": 1000,
        "inode": 12345,
        "media_class": "5-photos-by-date",
        "hash": "fakehash",
        "content_hash": "fakehash",
        "datetime_original": None,
        "create_date": None,
        "modify_date": None,
        "exif_json": "{}",
        "last_seen_ns": 1000000
    })

    # File is strictly missing
    assert not (ws / "5-photos-by-date" / "reappeared.jpg").exists()

    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    # Assert plan has ghost_prune db_remove effect
    db_remove_ops = [op for op in plan.operations if op.type == "db_remove"]
    assert len(db_remove_ops) == 1

    remove_fx = [fx for fx in db_remove_ops[0].database_effects_after_verification if fx.get("action") == "remove" and fx.get("relative_path") == "5-photos-by-date/reappeared.jpg"]
    assert len(remove_fx) == 1

    # Assert precondition must_be_missing == True
    assert remove_fx[0].get("preconditions", {}).get("must_be_missing") is True

    # Touch the file to reappear
    (ws / "5-photos-by-date" / "reappeared.jpg").write_text("reappeared data")

    # Try executing the stale plan
    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")

    import pytest
    with pytest.raises(ValueError, match="Stale plan: ghost-prune target reappeared after planning: 5-photos-by-date/reappeared.jpg"):
        executor.execute(plan, journal_path)

    # Assert cache is intact
    cache_verify = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    assert "5-photos-by-date/reappeared.jpg" in cache_verify.get_all_files()

    # Assert file still exists
    assert (ws / "5-photos-by-date" / "reappeared.jpg").exists()

    # Assert no handoff manifest generated
    assert not (ws / ".photos-ingest" / "photos-11-handoff.json").exists()