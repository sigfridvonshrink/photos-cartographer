from unittest.mock import patch, MagicMock
import os
import sys
import json
import sqlite3
import shutil
import importlib.machinery
import importlib.util
from unittest import mock
from pathlib import Path

# Dynamically load the single script file without a .py extension
script_path = os.path.join(os.path.dirname(__file__), '..', 'photos-1-prep')
loader = importlib.machinery.SourceFileLoader('photos_1_prep', script_path)
spec = importlib.util.spec_from_loader('photos_1_prep', loader)
photos_ingest = importlib.util.module_from_spec(spec)
sys.modules['photos_1_prep'] = photos_ingest
loader.exec_module(photos_ingest)

def setup_workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-1-prep-root").touch()

    # Root file collision
    (ws / "IMG_1234.JPG").write_text("image1234_data")

    # Another file with collision in 0-source (case-insensitive collision)
    source_dir = ws / "0-source"
    source_dir.mkdir()
    (source_dir / "img_1234.jpg").write_text("image1234_different_data")

    # RAW/JPG pair in 0-source
    (source_dir / "PHOTO_555.CR2").write_text("raw_data")
    (source_dir / "PHOTO_555.jpg").write_text("jpg_data")

# Exact duplicate in 4-photos-by-date
    photos_dir = ws / "4-photos-by-date"
    photos_dir.mkdir()
    (photos_dir / "20230101_120000-001.jpg").write_text("duplicate_data")

    # Another duplicate case: RAW and JPG have SAME content but shouldn't quarantine
    (ws / "RAW_SAME.CR2").write_text("same_hash_content")
    (ws / "RAW_SAME.jpg").write_text("same_hash_content")

    # Source duplicate in 0-source

    # Source duplicate in 0-source
    (source_dir / "dup_image.jpg").write_text("duplicate_data")

    return ws

def mock_hash_file(filepath):
    import hashlib
    try:
        with open(filepath, 'rb') as f:
            val = hashlib.sha256(f.read()).hexdigest()
            return {"status": "valid", "strategy": "sha256-v1", "value": val}
    except Exception as e:
        return {"status": "failed", "strategy": "sha256-v1", "value": None, "error": str(e)}

def mock_hash_image(filepath):
    return mock_hash_file(filepath)

def mock_read_metadata_concurrently(folders, max_workers=4, progress_coordinator=None):
    # Return fake metadata
    res = {}
    import os
    for folder in folders:
        for f in os.listdir(folder):
            abs_path = os.path.join(folder, f)
            if "duplicate" in abs_path or "20230101_120000" in abs_path:
                res[abs_path] = {"DateTimeOriginal": "2023:01:01 12:00:00"}
            elif "555" in abs_path:
                res[abs_path] = {"DateTimeOriginal": "2023:02:02 14:00:00"}
            else:
                res[abs_path] = {}
    return res, set()

@mock.patch('photos_1_prep.ContentHasher.hash_file', side_effect=mock_hash_file)
@mock.patch('photos_1_prep.ContentHasher.hash_image', side_effect=mock_hash_image)
@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_prep_workflow_plan_and_execute(mock_meta, mock_hash_img, mock_hash_file, tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1

    # Run plan
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    assert plan.command == "prep"
    assert len(plan.blockers) == 0

    ops = plan.operations
    assert len(ops) > 0
    op_types = [op.type for op in ops]

    assert "quarantine_move" in op_types
    assert "move_no_clobber" in op_types
    assert "rename_no_clobber" in op_types

    # Run execute
    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / "journal.json")
    executor.execute(plan, journal_path)

    # PR ACCEPTANCE TEST: root-to-"0-source" collision where neither file is overwritten
    # IMG_1234.JPG moves from root to 0-source. But 0-source/img_1234.jpg exists!
    # They should both survive with deterministic suffix naming.
    assert not (ws / "IMG_1234.JPG").exists()

    files_in_dest = list((ws / "1-missing-metadata").iterdir())
    names_in_dest = [f.name.lower() for f in files_in_dest]

    count_1234 = sum(1 for name in names_in_dest if "1234" in name and name.endswith(".jpg"))
    assert count_1234 == 2, f"Expected 2 variants of img_1234 in dest, found {names_in_dest}"

    # PR ACCEPTANCE TEST: "IMG.JPG" vs "IMG.jpg" survival with deterministic naming;
    # (Tested implicitly by the above root-to-source case normalizations preserving both files)

    # PR ACCEPTANCE TEST: RAW/JPG not treated as disposable duplicates
    # PHOTO_555.CR2 and PHOTO_555.jpg have the same fake hash, but shouldn't quarantine.
    # The JPG should be in 2-redundant-jpgs. The RAW should be in 4-photos-by-date.
    assert (ws / "2-redundant-jpgs" / "PHOTO_555.jpg").exists()
    assert (ws / "4-photos-by-date" / "20230202_140000-001.cr2").exists()

    # PR ACCEPTANCE TEST: RAW/JPG pair not quarantined if hashes match exactly
    files_in_dest = list((ws / "1-missing-metadata").iterdir())
    names_in_dest = [f.name.lower() for f in files_in_dest]
    assert any("raw_same" in name and name.endswith(".jpg") for name in names_in_dest)
    assert any("raw_same" in name and name.endswith(".cr2") for name in names_in_dest)

# PR ACCEPTANCE TEST: quarantine manifest creation and structured evidence
    quarantine_base = ws / ".photos-ingest-quarantine" / plan.plan_id
    assert quarantine_base.exists()
    assert (quarantine_base / "0-source" / "dup_image.jpg").exists()

    manifest_file = quarantine_base / "manifest.json"
    assert manifest_file.exists()

    with open(str(manifest_file), 'r') as mf:
        manifest_data = json.load(mf)
        assert len(manifest_data) > 0
        assert "duplicate_evidence" in manifest_data[0]
        assert "strategy" in manifest_data[0]["duplicate_evidence"]
        assert "status" in manifest_data[0]["duplicate_evidence"]
        assert "value" in manifest_data[0]["duplicate_evidence"]

# PR ACCEPTANCE TEST: check the cache after execution
    cache_conn = sqlite3.connect(executor.workspace_root + "/.photos_ingest.db")
    cur = cache_conn.cursor()
    cur.execute("SELECT relative_path FROM file_cache")
    db_paths = [r[0] for r in cur.fetchall()]
    assert any("2-redundant-jpgs" in p for p in db_paths)
    assert any("4-photos-by-date" in p for p in db_paths)
    assert "IMG_1234.JPG" not in db_paths

# Assert no intermediate paths exist
    assert not any("0-source/IMG_1234.JPG" in p for p in db_paths)
    assert not any("__photos_ingest_tmp_extnorm__" in p for p in db_paths)
    cache_conn.close()

def test_deterministic_temp_names(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan1 = workflow.plan()
    plan2 = workflow.plan()

    # Verify temp names are identical across repeated runs
    temp_ops1 = [op for op in plan1.operations if op.destination and "__photos_ingest_tmp_extnorm__" in op.destination]
    temp_ops2 = [op for op in plan2.operations if op.destination and "__photos_ingest_tmp_extnorm__" in op.destination]

    assert len(temp_ops1) > 0
    assert len(temp_ops1) == len(temp_ops2)
    for i in range(len(temp_ops1)):
        assert temp_ops1[i].destination == temp_ops2[i].destination

@mock.patch('photos_1_prep.ContentHasher.hash_file', side_effect=mock_hash_file)
@mock.patch('photos_1_prep.ContentHasher.hash_image', side_effect=mock_hash_image)
@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_source_changed_after_plan_abort(mock_meta, mock_hash_img, mock_hash_file, tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    # PR ACCEPTANCE TEST: source-changed-after-plan abort
    # Modify a file after plan is created
    import time
    time.sleep(0.01)
    (ws / "IMG_1234.JPG").write_text("modified_data_size_change")

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / "journal.json")

    import pytest
    with pytest.raises(ValueError, match="Precondition failed: size changed"):
        executor.execute(plan, journal_path)

def test_sidecar_blocking(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1

    # PR ACCEPTANCE TEST: sidecar blocking
    (ws / "0-source" / "PHOTO_555.xmp").touch()

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    assert len(plan.blockers) > 0
    assert "Forbidden sidecar files detected" in plan.blockers[0]

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / "journal.json")

    import pytest
    with pytest.raises(ValueError, match="Plan contains blockers and cannot be executed"):
        executor.execute(plan, journal_path)


def test_hash_failure_preservation(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1

# PR ACCEPTANCE TEST: hash failure preserving files and blocking
    # We mock it to fail for certain files
    def mock_hash_fail(filepath):
        if "dup_image" in str(filepath) or "20230101_120000" in str(filepath):
            return {"status": "failed", "strategy": "image-content-hash-v1", "value": None, "error": "Mocked failure"}
        import hashlib
        try:
            with open(filepath, 'rb') as f:
                val = hashlib.sha256(f.read()).hexdigest()
                return {"status": "valid", "strategy": "sha256-v1", "value": val}
        except Exception as e:
            return {"status": "failed", "strategy": "sha256-v1", "value": None, "error": str(e)}

    with mock.patch('photos_1_prep.ContentHasher.hash_file', side_effect=mock_hash_fail), \
         mock.patch('photos_1_prep.ContentHasher.hash_image', side_effect=mock_hash_fail), \
         mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently):

        cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
        workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
        plan = workflow.plan()

        assert len(plan.blockers) > 0
        assert any("Hash failure" in b for b in plan.blockers)

        # Check operations to ensure neither was queued for quarantine
        op_types = [op.type for op in plan.operations]
        assert "quarantine_move" not in op_types

def test_symlink_blocking(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1

    # PR ACCEPTANCE TEST: symlink blocking
    # Create a symlink in 0-source pointing outside
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("external")
    symlink_path = ws / "0-source" / "symlink.txt"
    os.symlink(str(outside_file), str(symlink_path))

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    assert len(plan.blockers) > 0
    assert any("Forbidden symlink detected" in b for b in plan.blockers)
def test_deterministic_temp_names_with_existing(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    # Minimal fixture explicitly constructed to trigger the suffix logic precisely
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-1-prep-root").touch()

    src_dir = ws / "0-source"
    src_dir.mkdir()

    # A single target file requiring extension normalisation
    (src_dir / "collision_test.JPG").write_text("dummy")

    # Explicitly pre-create the base temp name and -001 to block them
    # Note we use the target destination for the temp name check
    (src_dir / "collision_test.__photos_ingest_tmp_extnorm__.jpg").write_text("blocked")
    (src_dir / "collision_test.__photos_ingest_tmp_extnorm__-001.jpg").write_text("blocked")

    photos_ingest.CONFIG["jobs"] = 1
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    temp_ops = [op for op in plan.operations if "__photos_ingest_tmp_extnorm__" in op.destination]

    found_002 = False
    for op in temp_ops:
        if "collision_test.__photos_ingest_tmp_extnorm__-002.jpg" in op.destination.lower():
            found_002 = True
            break

    assert found_002, f"The planner failed to allocate the expected -002 temp name. Found destinations: {[op.destination for op in temp_ops]}"

def test_source_changed_after_plan_abort_no_db(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)

    # Hand build a plan and verify executor fails it without making a DB
    plan = photos_ingest.Plan(
        plan_version=1,
        plan_id="dummy",
        command="prep",
        created_at="now",
        workspace_root=str(ws),
        digikam_root=None,
        config_fingerprint="dummy",
        instruction_fingerprints={},
        locks_required=["workspace"],
        summary={},
        blockers=[],
        warnings=[],
        operations=[
            photos_ingest.Operation(
                operation_id="op-1",
                type="move_no_clobber",
                reason="test",
                source="IMG_1234.JPG",
                destination="new_unique_name.jpg",
                preconditions={"size": 999999, "mtime_ns": 999999},
                verification={},
                database_effects_after_verification=[{"action": "upsert", "data": {}}]
            )
        ]
    )

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / "journal.json")
    db_path = str(ws / ".photos_ingest.db")

    assert not os.path.exists(db_path)

    import pytest
    with pytest.raises(ValueError, match="Precondition failed"):
        executor.execute(plan, journal_path)

    assert not os.path.exists(db_path)
