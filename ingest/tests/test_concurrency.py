
import pytest
import os
import json
import sqlite3
import sys
import subprocess
from unittest.mock import patch, MagicMock

# photos_1_prep and photos_utils are loaded once by conftest.py into sys.modules
import photos_1_prep as prep
import photos_utils as utils

@pytest.fixture
def workspace(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "0-sources"))
    os.makedirs(os.path.join(root, "1-strays"))
    os.makedirs(os.path.join(root, "2-missing-metadata"))
    os.makedirs(os.path.join(root, "3-redundant-jpgs"))
    os.makedirs(os.path.join(root, "4-videos-by-date"))
    os.makedirs(os.path.join(root, "5-photos-by-date"))
    os.makedirs(os.path.join(root, "6-photos-by-dest"))
    os.makedirs(os.path.join(root, ".photos-ingest"), exist_ok=True)
    with open(os.path.join(root, ".photos-ingest", "photos-00-workspace-guard"), "w") as f:
        f.write("")

    # Create some dummy files
    for i in range(10):
        with open(os.path.join(root, "0-sources", f"file{i}.jpg"), "w") as f:
            f.write(f"content{i}")

    return root

@patch("subprocess.Popen")
def test_exiftool_pool_lifecycle(mock_popen):
    mock_process = MagicMock()
    mock_popen.return_value = mock_process

    with utils.ExifToolWorkerPool(size=2) as pool:
        assert pool.workers.qsize() == 2

        worker1 = pool.workers.get()
        assert not worker1.closed

        # The worker doesn't even need to be put back; shutdown tracks via _all_workers

    assert worker1.closed

@patch("subprocess.Popen")
@patch("photos_utils.PersistentExifToolWorker.read_metadata")
def test_read_metadata_concurrently(mock_read, mock_popen, workspace):
    mock_process = MagicMock()
    mock_popen.return_value = mock_process

    mock_read.side_effect = [{"file1.jpg": {"Make": "Canon"}}, {"file2.jpg": {"Make": "Nikon"}}]

    coordinator = utils.ProgressCoordinator(quiet=True)
    res, failed = utils.MetadataReader.read_metadata_concurrently(["folder1", "folder2"], max_workers=2, progress_coordinator=coordinator)

    assert res == {"file1.jpg": {"Make": "Canon"}, "file2.jpg": {"Make": "Nikon"}}
    assert coordinator.counters.get("metadata_extracted", 0) == 2

@patch("subprocess.Popen")
@patch("photos_utils.PersistentExifToolWorker.read_metadata")
def test_deterministic_plan_with_jobs(mock_read, mock_popen, workspace):
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_read.return_value = {}


    utils.CONFIG["jobs"] = 1
    cache1 = prep.WorkspaceCache(workspace)
    workflow1 = prep.WorkspacePrepWorkflow(workspace, cache1)
    plan1 = workflow1.plan()

    utils.CONFIG["jobs"] = 4
    cache4 = prep.WorkspaceCache(workspace)
    workflow4 = prep.WorkspacePrepWorkflow(workspace, cache4)
    plan4 = workflow4.plan()
    assert plan4.summary["execution_config"]["jobs_requested"] == 4
    assert plan4.summary["execution_config"]["jobs_semantic"] is False


    d1 = json.loads(plan1.to_json())
    d4 = json.loads(plan4.to_json())

    VOLATILE_KEYS = {
        "plan_id",
        "created_at",
        "operation_id",
        "last_seen_ns",
        "absolute_path",
        "duration_seconds",
        "progress",
        # jobs count is a concurrency knob recorded in the plan summary
        # (execution_config / performance_and_cache); it legitimately varies
        # between the jobs=1 and jobs=4 runs and is asserted separately above.
        "jobs_requested",
        "jobs_semantic",
    }

    def stable_dict_sort_key(d):
        return (
            str(d.get("type", "")),
            str(d.get("relative_path", "")),
            str(d.get("source", "")),
            str(d.get("src", "")),
            str(d.get("destination", "")),
            str(d.get("dest", "")),
            json.dumps(d, sort_keys=True, default=str),
        )

    def canonicalize(value):
        if isinstance(value, dict):
            # Normalise JSON payloads to avoid string formatting issues
            if "hash" in value and isinstance(value["hash"], str):
                try:
                    value["hash"] = json.dumps(json.loads(value["hash"]), sort_keys=True)
                except: pass
            if "content_hash" in value and isinstance(value["content_hash"], str):
                try:
                    value["content_hash"] = json.dumps(json.loads(value["content_hash"]), sort_keys=True)
                except: pass
            if "raw_payload" in value and isinstance(value["raw_payload"], str):
                try:
                    value["raw_payload"] = json.dumps(json.loads(value["raw_payload"]), sort_keys=True)
                except: pass
            if "parsed_json" in value and isinstance(value["parsed_json"], str):
                try:
                    value["parsed_json"] = json.dumps(json.loads(value["parsed_json"]), sort_keys=True)
                except: pass

            return {
                k: canonicalize(v)
                for k, v in sorted(value.items())
                if k not in VOLATILE_KEYS
            }
        if isinstance(value, list):
            items = [canonicalize(v) for v in value]
            if all(isinstance(x, dict) for x in items):
                return sorted(items, key=stable_dict_sort_key)

            try:
                return sorted(items)
            except TypeError:
                return items
        return value

    d1_canon = canonicalize(d1)
    d4_canon = canonicalize(d4)

    if d1_canon != d4_canon:
        print("D1:")
        print(json.dumps(d1_canon, indent=2))
        print("D4:")
        print(json.dumps(d4_canon, indent=2))

    assert d1_canon == d4_canon


def test_progress_coordinator():
    coord = utils.ProgressCoordinator(quiet=True)
    coord.start_phase("test", total_items=10)
    coord.increment_completed()
    coord.increment("some_metric", 5)
    coord.finish_phase()

    assert coord.completed_items == 1
    assert coord.counters["some_metric"] == 5

@patch("subprocess.Popen")
@patch("photos_1_prep.PlanValidator.validate_plan_preflight")
def test_quiet_plan_executor_execution(mock_validate, mock_popen, workspace):
    mock_popen.return_value = MagicMock()

    # Generate a dummy plan
    journal_path = os.path.join(workspace, ".photos-ingest/journal.json")

    op = prep.Operation(
        type="mkdir",
        reason="testing",
        destination="2-missing-metadata/generated-by-execute-test",
        source="",
        operation_id="test_op_id",
        preconditions={},
        verification={},
        database_effects_after_verification=[]
    )

    plan = prep.Plan(
        plan_id="test_plan_id",
        plan_version=1,
        command="prep",
        created_at="now",
        workspace_root=workspace,
        digikam_root=None,
        config_fingerprint=prep.Fingerprint("sha256", "val"),
        instruction_fingerprints={},
        locks_required=[],
        summary={"metadata_plan_status": {}},
        blockers=[],
        warnings=[],
        operations=[op],
        workspace_file_preconditions=[],
        metadata_dependencies={"extractor": "fake"}
    )

    executor = prep.PlanExecutor(workspace)
    executor.coordinator = utils.ProgressCoordinator(quiet=True)

    # Execute the plan
    executor.execute(plan, journal_path)

    # Assert execution succeeds and generated files
    assert os.path.exists(journal_path)
    assert os.path.isdir(os.path.join(workspace, "2-missing-metadata", "generated-by-execute-test"))

    with open(journal_path, 'r') as f:
        journal_data = json.load(f)

    assert journal_data['status'] == 'success'

    # Assert progress counters did not leak into journal
    assert 'completed_items' not in journal_data
    assert 'current_phase' not in journal_data

    for op_res in journal_data['operations']:
        assert 'completed_items' not in op_res
        assert 'current_phase' not in op_res

    handoff_path = os.path.join(workspace, ".photos-ingest", "photos-11-handoff.json")
    assert os.path.exists(handoff_path)

    with open(handoff_path, 'r') as f:
        handoff_data = json.load(f)

    # Assert progress counters did not leak into handoff
    assert 'completed_items' not in handoff_data
    assert 'current_phase' not in handoff_data
    assert 'counters' not in handoff_data

    assert handoff_data['run_metadata']['plan_id'] == "test_plan_id"

def test_cli_jobs_argparse(workspace):
    import subprocess
    import os

    script = "ingest/photos-1-prep"
    # Ensure it rejects invalid jobs
    res = subprocess.run(["python3", script, "--jobs", "0", "plan", "--output", "test.json"], capture_output=True, text=True)
    assert res.returncode != 0
    assert "jobs must be a positive integer" in res.stderr

    res = subprocess.run(["python3", script, "--jobs", "-1", "plan", "--output", "test.json"], capture_output=True, text=True)
    assert res.returncode != 0

    res = subprocess.run(["python3", script, "--jobs", "abc", "plan", "--output", "test.json"], capture_output=True, text=True)
    assert res.returncode != 0

    # Ensure it accepts valid jobs and produces output plan
    os.makedirs(os.path.join(workspace, ".photos-ingest"), exist_ok=True)
    with open(os.path.join(workspace, ".photos-ingest", "photos-00-workspace-guard"), "w") as f: f.write("")

    # Create dummy exiftool to pass the Popen check
    exiftool_path = os.path.join(workspace, "exiftool")
    with open(exiftool_path, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(exiftool_path, 0o755)
    env = os.environ.copy()
    env["PATH"] = workspace + os.pathsep + env.get("PATH", "")

    import json

    plan_path_1 = os.path.join(workspace, "plan-j1.json")
    res = subprocess.run(
        ["python3", os.path.abspath(script), "-j", "1", "plan", "--output", plan_path_1],
        cwd=workspace, capture_output=True, text=True, env=env
    )
    assert res.returncode == 0, res.stderr
    assert os.path.exists(plan_path_1)

    with open(plan_path_1, "r") as f:
        plan_data_1 = json.load(f)
    assert plan_data_1["summary"]["execution_config"]["jobs_requested"] == 1
    assert plan_data_1["summary"]["execution_config"]["jobs_semantic"] is False

    plan_path_2 = os.path.join(workspace, "plan-j2.json")
    res = subprocess.run(
        ["python3", os.path.abspath(script), "--jobs", "2", "plan", "--output", plan_path_2],
        cwd=workspace, capture_output=True, text=True, env=env
    )
    assert res.returncode == 0, res.stderr
    assert os.path.exists(plan_path_2)

    with open(plan_path_2, "r") as f:
        plan_data_2 = json.load(f)
    assert plan_data_2["summary"]["execution_config"]["jobs_requested"] == 2
    assert plan_data_2["summary"]["execution_config"]["jobs_semantic"] is False

    res = subprocess.run(["python3", os.path.abspath(script), "--jobs", "2", "plan"], cwd=workspace, capture_output=True, text=True)
    assert "jobs must be a positive integer" not in res.stderr

@patch("subprocess.Popen")
@patch("photos_utils.PersistentExifToolWorker.read_metadata")
def test_exiftool_pool_failure_blocks_plan(mock_read_metadata, mock_popen, workspace):
    mock_popen.return_value = MagicMock()
    # If the process errors out constantly
    from photos_utils import ProcessCrashedError
    mock_read_metadata.side_effect = ProcessCrashedError("Crash")

    utils.ExifToolWorkerPool._instance = None

    # We should have one file triggering a metadata fetch
    cache = prep.WorkspaceCache(workspace)
    workflow = prep.WorkspacePrepWorkflow(workspace, cache)
    plan = workflow.plan()

    # Check that blockers are appended properly
    assert any("Metadata tool execution failed completely" in b for b in plan.blockers)

    # Verify it wasn't accidentally committed to the cache payload as valid
    for op in plan.operations:
        for fx in op.database_effects_after_verification or []:
            if fx.get("action") != "upsert":
                continue

            data = fx.get("data", {})
            metadata = data.get("metadata")

            if data.get("relative_path", "").endswith(".jpg"):
                assert metadata is None or metadata.get("extraction_status") != "extracted_ok"
                assert metadata is None or metadata.get("extraction_status") != "reused_from_cache"
@patch("subprocess.Popen")
@patch("photos_utils.PersistentExifToolWorker.read_metadata")
def test_exiftool_pool_failure_blocks_handoff(mock_read_metadata, mock_popen, workspace):
    mock_popen.return_value = MagicMock()
    from photos_utils import ProcessCrashedError
    mock_read_metadata.side_effect = ProcessCrashedError("Crash")

    utils.ExifToolWorkerPool._instance = None

    cache = prep.WorkspaceCache(workspace)
    workflow = prep.WorkspacePrepWorkflow(workspace, cache)
    plan = workflow.plan()

    assert plan.blockers

    executor = prep.PlanExecutor(workspace)
    executor.coordinator = utils.ProgressCoordinator(quiet=True)
    journal_path = os.path.join(workspace, ".photos-ingest/journal.json")

    import pytest
    with pytest.raises(Exception) as excinfo:
        executor.execute(plan, journal_path)

    assert "blocker" in str(excinfo.value).lower() or "metadata" in str(excinfo.value).lower()

    handoff_path = os.path.join(workspace, ".photos-ingest", "photos-11-handoff.json")
    assert not os.path.exists(handoff_path)

@patch("subprocess.Popen")
@patch("photos_utils.MetadataReader.read_metadata_concurrently")
def test_failed_folder_mapping(mock_read_metadata_concurrently, mock_popen, workspace):
    mock_popen.return_value = MagicMock()

    # Simulate a folder-level failure where all files in the folder are missing metadata
    mock_read_metadata_concurrently.return_value = ({}, {os.path.join(workspace, "0-sources")})

    cache = prep.WorkspaceCache(workspace)
    workflow = prep.WorkspacePrepWorkflow(workspace, cache)

    # Make sure we have a file to process
    src_dir = os.path.join(workspace, "0-sources")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(src_dir, "file0.jpg"), "w") as f: f.write("dummy")

    plan = workflow.plan()

    assert plan.blockers
    assert any("0-sources/file0.jpg" in b for b in plan.blockers)
    assert any("Metadata tool execution failed" in b for b in plan.blockers)




@patch("subprocess.Popen")
@patch("photos_1_prep.ContentHasher.fingerprint_image")
@patch("photos_utils.MetadataReader.read_metadata_concurrently")
def test_stale_dependency_under_concurrency_blocks_execution(mock_read_metadata_concurrently, mock_hash_image, mock_popen, workspace):
    mock_hash_image.return_value = {"status": "valid", "strategy": "image-content-hash", "value": "dummyhash"}
    mock_popen.return_value = MagicMock()

    def _mock_read_concurrently(folders, max_workers=4, progress_coordinator=None):
        import os
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:01 12:00:00",
                    "Make": "Canon",
                    "Model": "EOS R5",
                    "SerialNumber": "12345",
                    "camera_group_key": "12345|Canon|EOS R5",
                    "has_native_gps": False,
                    "has_timestamp": True,
                    "raw_payload": "{}"
                }
        return res, set()
    mock_read_metadata_concurrently.side_effect = _mock_read_concurrently

    # We should have one file triggering a metadata fetch
    os.makedirs(os.path.join(workspace, "2-missing-metadata"), exist_ok=True)
    file_path = os.path.join(workspace, "2-missing-metadata", "dummy.jpg")
    with open(file_path, "w") as f:
        f.write("dummy")

    utils.CONFIG["jobs"] = 4
    cache = prep.WorkspaceCache(workspace)
    workflow = prep.WorkspacePrepWorkflow(workspace, cache)
    workflow.coordinator = utils.ProgressCoordinator(quiet=True)
    plan = workflow.plan()

    assert not plan.blockers
    mock_read_metadata_concurrently.assert_called()
    assert mock_read_metadata_concurrently.call_args[1].get("max_workers") == 4 or mock_read_metadata_concurrently.call_args[0][1] == 4

    executor = prep.PlanExecutor(workspace)
    executor.coordinator = utils.ProgressCoordinator(quiet=True)
    journal_path = os.path.join(workspace, ".photos-ingest/journal.json")

    # Now make the input file stale by modifying its size/mtime
    import time
    time.sleep(0.01)
    with open(file_path, "a") as f:
        f.write("modified")

    import pytest
    with pytest.raises(ValueError, match="Stale plan: dependency changed"):
        executor.execute(plan, journal_path)

    handoff_path = os.path.join(workspace, ".photos-ingest", "photos-11-handoff.json")
    assert not os.path.exists(handoff_path)
    assert not os.path.exists(journal_path)

@patch("subprocess.Popen")
@patch("photos_1_prep.ContentHasher.fingerprint_image")
@patch("photos_utils.MetadataReader.read_metadata_concurrently")
def test_progress_summary_fields(mock_read_metadata_concurrently, mock_hash_image, mock_popen, workspace):
    mock_hash_image.return_value = {"status": "valid", "strategy": "image-content-hash", "value": "dummyhash"}
    mock_popen.return_value = MagicMock()

    def _mock_read_concurrently(folders, max_workers=4, progress_coordinator=None):
        import os
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:01 12:00:00",
                    "Make": "Canon",
                    "Model": "EOS R5",
                    "SerialNumber": "12345",
                    "camera_group_key": "12345|Canon|EOS R5",
                    "has_native_gps": False,
                    "has_timestamp": True,
                    "raw_payload": "{}"
                }
        return res, set()
    mock_read_metadata_concurrently.side_effect = _mock_read_concurrently

    # We should have one file triggering a metadata fetch
    os.makedirs(os.path.join(workspace, "0-sources"), exist_ok=True)
    file_path = os.path.join(workspace, "0-sources", "dummy.jpg")
    with open(file_path, "w") as f:
        f.write("dummy")

    cache = prep.WorkspaceCache(workspace)
    workflow = prep.WorkspacePrepWorkflow(workspace, cache)
    workflow.coordinator = utils.ProgressCoordinator(quiet=True)
    plan = workflow.plan()

    pc = plan.summary.get("performance_and_cache", {})
    assert pc
    assert pc["jobs_requested"] > 0
    assert pc["progress_mode"] == "quiet"
    assert pc["dependency_validation_status"] == "pending"
    assert pc["handoff_written_after_successful_validation"] is False

    executor = prep.PlanExecutor(workspace)
    executor.coordinator = utils.ProgressCoordinator(quiet=True)
    journal_path = os.path.join(workspace, ".photos-ingest/journal.json")

    executor.execute(plan, journal_path)

    pc = plan.summary.get("performance_and_cache", {})
    assert pc["dependency_validation_status"] == "success"
    assert pc["handoff_written_after_successful_validation"] is True
    assert pc["db_upserts_applied"] > 0
    assert pc["db_removes_applied"] >= 0
    assert pc["db_renames_applied"] >= 0

    # Ensure it didn't leak into handoff
    handoff_path = os.path.join(workspace, ".photos-ingest", "photos-11-handoff.json")
    with open(handoff_path, 'r') as f:
        import json
        handoff_data = json.load(f)
        assert "performance_and_cache" not in handoff_data
        assert "jobs_requested" not in handoff_data
