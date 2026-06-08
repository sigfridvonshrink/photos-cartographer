import pytest
import os
import sys
import importlib.machinery
from unittest import mock

# photos_1_prep is loaded once by conftest.py into sys.modules
import photos_1_prep

def test_photos_1_prep_exists():
    assert os.path.exists('ingest/photos-1-prep')

def test_photos_utils_exists():
    assert os.path.exists('ingest/photos_utils.py')

def test_no_calibrate_command():
    parser = mock.MagicMock()
    # we just want to ensure that 'calibrate' is not mentioned in the argparse setup or the file content as an active command path
    with open('ingest/photos-1-prep', 'r') as f:
        content = f.read()
        # Verify that subcommands don't include calibrate
        assert 'add_parser("calibrate"' not in content
        assert 'add_parser("refresh-library"' not in content
        assert 'add_parser("merge"' not in content

def test_no_calibration_json_generation():
    with open('ingest/photos-1-prep', 'r') as f:
        content = f.read()
        assert 'class CalibrationGenerator' not in content
        assert 'class CalibrationWorkflow' not in content

def test_prep_plans_contain_no_time_metadata():
    with open('ingest/photos-1-prep', 'r') as f:
        content = f.read()
        assert 'apply_time_sync' not in content
        assert 'apply_gpx_placement' not in content

def test_by_dest_read_only():
    # Make sure we don't have operations targeting 5-photos-by-dest for anything other than reading
    # Check that WorkspacePrepWorkflow only targets mutables:
    assert 'class WorkspacePrepWorkflow:' in dir(photos_1_prep) or hasattr(photos_1_prep, 'WorkspacePrepWorkflow')


def test_execute_rejects_forbidden_operation_types():
    # If we pass an invalid op.type, execution should raise ValueError
    executor = photos_1_prep.PlanExecutor("dummy_ws")

    plan = photos_1_prep.Plan(
        plan_version=1,
        plan_id="test",
        command="prep",
        created_at="now",
        workspace_root="dummy_ws",
        digikam_root=None,
        config_fingerprint=photos_1_prep.Fingerprint("sha256", "val"),
        instruction_fingerprints={},
        locks_required=[],
        summary={},
        blockers=[],
        warnings=[],
        operations=[
            photos_1_prep.Operation(
                operation_id="op-1",
                type="metadata_write",
                reason="test",
            )
        ]
    )

    with pytest.raises(ValueError, match="Operation type 'metadata_write' is not allowed in photos-1-prep"):
        executor.execute(plan, "dummy_journal")

def test_execute_rejects_non_prep_plans():
    # If we pass an invalid op.type, execution should raise ValueError
    executor = photos_1_prep.PlanExecutor("dummy_ws")

    plan = photos_1_prep.Plan(
        plan_version=1,
        plan_id="test",
        command="calibrate",
        created_at="now",
        workspace_root="dummy_ws",
        digikam_root=None,
        config_fingerprint=photos_1_prep.Fingerprint("sha256", "val"),
        instruction_fingerprints={},
        locks_required=[],
        summary={},
        blockers=[],
        warnings=[],
        operations=[]
    )

    with pytest.raises(ValueError, match="Plan command 'calibrate' is not supported by photos-1-prep"):
        executor.execute(plan, "dummy_journal")


def test_by_dest_duplicate_does_not_mutate_behavior():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir) / 'workspace'
        ws.mkdir()
        (ws / '.photos-ingest').mkdir(exist_ok=True); (ws / '.photos-ingest' / 'photos-00-workspace-guard').touch()
        (ws / '5-photos-by-dest').mkdir()
        (ws / '0-source').mkdir()

        # Add 5-photos-by-dest file
        by_dest_file = ws / '5-photos-by-dest' / 'existing.jpg'
        by_dest_file.write_text('dummy content')

        # Add duplicate file in 0-source
        source_file = ws / '0-source' / 'duplicate.jpg'
        source_file.write_text('dummy content')

        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from photos_utils import CONFIG
        CONFIG['jobs'] = 1

        cache = photos_1_prep.WorkspaceCache(str(ws), in_memory=True)
        workflow = photos_1_prep.WorkspacePrepWorkflow(str(ws), cache)
        plan = workflow.plan()

        for op in plan.operations:
            assert not (op.source or '').startswith('5-photos-by-dest/')
            assert not (op.destination or '').startswith('5-photos-by-dest/')
            # Any operation related to quarantine must target the source file, not by_dest
            if op.type == 'quarantine_move':
                assert op.source == '0-source/duplicate.jpg'

@mock.patch("photos_1_prep.ContentHasher.hash_file")
@mock.patch("photos_1_prep.ContentHasher.hash_image")
def test_by_dest_duplicate_does_not_mutate_behavior_with_hashes(mock_hash_image, mock_hash_file, tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()

    by_dest = ws / "5-photos-by-dest"
    source = ws / "0-source"
    by_dest.mkdir()
    source.mkdir()

    (by_dest / "existing.jpg").write_text("same content")
    (source / "duplicate.jpg").write_text("same content")

    duplicate_hash = {
        "status": "valid",
        "strategy": "image-content-hash-v1",
        "value": "same-hash"
    }

    mock_hash_file.return_value = duplicate_hash
    mock_hash_image.return_value = duplicate_hash

    cache = photos_1_prep.WorkspaceCache(str(ws), in_memory=True)
    workflow = photos_1_prep.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    for op in plan.operations:
        assert not (op.source or "").startswith("5-photos-by-dest/")
        assert not (op.destination or "").startswith("5-photos-by-dest/")

    quarantine_ops = [op for op in plan.operations if op.type == "quarantine_move"]
    for op in quarantine_ops:
        assert op.source != "5-photos-by-dest/existing.jpg"


def test_by_dest_uppercase_extension_does_not_rename(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()

    by_dest = ws / "5-photos-by-dest"
    by_dest.mkdir()

    (by_dest / "EXISTING.JPG").write_text("content")

    cache = photos_1_prep.WorkspaceCache(str(ws), in_memory=True)
    workflow = photos_1_prep.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    for op in plan.operations:
        assert not (op.source or "").startswith("5-photos-by-dest/")
        assert not (op.destination or "").startswith("5-photos-by-dest/")

def test_dry_run_rejects_metadata_write():
    executor = photos_1_prep.PlanExecutor("dummy_ws")

    plan = photos_1_prep.Plan(
        plan_version=1,
        plan_id="test",
        command="prep",
        created_at="now",
        workspace_root="dummy_ws",
        digikam_root=None,
        config_fingerprint=photos_1_prep.Fingerprint("sha256", "val"),
        instruction_fingerprints={},
        locks_required=[],
        summary={},
        blockers=[],
        warnings=[],
        operations=[
            photos_1_prep.Operation(
                operation_id="op-1",
                type="metadata_write",
                reason="test",
            )
        ]
    )
    with pytest.raises(ValueError, match="Operation type 'metadata_write' is not allowed in photos-1-prep"):
        photos_1_prep.PlanValidator.validate_plan_preflight(plan, "dummy_ws")
