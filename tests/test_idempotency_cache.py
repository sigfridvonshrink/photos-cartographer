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

import os
import sys
import json
import shutil
import sqlite3
import pytest
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
@pytest.mark.spec("idem-no-op-run-1", "prep-by-dest-readonly-1", "prep-no-requarantine-1", "prep-report-no-op-facts-1", "prep-reuse-cache-unchanged-1", "prep-second-run-zero-mutations-1", "prep-tolerate-populated-folders-1", "prep-unchanged-no-op-1")
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
@pytest.mark.spec("prep-execute-no-rederive-1")
def test_execute_applies_only_recorded_operations_no_rederive(mock_meta, tmp_path):
    """§4 (anti): execute applies ONLY the recorded plan operations; it never re-derives the
    organization from the filesystem. Drop the new_img move op from the saved plan before executing:
    if execute re-derived it would still move new_img to 2-missing-metadata. Instead new_img stays
    EXACTLY where it is (0-sources, untouched), while the operations that REMAIN in the plan (the
    dup_img quarantine) still apply — proving execute is plan-driven, not a fresh derivation."""
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            return {"status": "valid", "strategy": "sha256-v1", "value": hashlib.sha256(f.read()).hexdigest()}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan1 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    moves = [op for op in plan1.operations
             if op.type == "move_no_clobber" and "new_img.jpg" in (op.source or "")]
    assert len(moves) == 1                                       # the op we will REMOVE from the plan
    before = (ws / "0-sources" / "new_img.jpg").read_bytes()
    # Drop the new_img move op; keep the rest (dup_img quarantine, by-dest db_upsert).
    plan1.operations = [op for op in plan1.operations if op not in moves]

    photos_ingest.PlanExecutor(str(ws)).execute(plan1, str(ws / ".photos-ingest/journal.json"))

    # new_img was NOT re-derived/moved — it is byte-identical at its original 0-sources path.
    assert (ws / "0-sources" / "new_img.jpg").exists()
    assert (ws / "0-sources" / "new_img.jpg").read_bytes() == before
    assert not (ws / "2-missing-metadata" / "new_img.jpg").exists()
    assert not any(p.name == "new_img.jpg"
                   for p in (ws / "5-photos-by-date").rglob("*"))   # not organized either
    # the operations that REMAINED in the plan still applied: dup_img was quarantined.
    assert list((ws / ".photos-ingest-quarantine").rglob("dup_img.jpg"))


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
@pytest.mark.spec("prep-path-conflict-bydest-no-clobber-1")
def test_chronological_destination_collision_allocates_safe_name_no_clobber(mock_meta, tmp_path):
    """§11.2 (anti): a 0-sources file whose computed chronological destination in 5-photos-by-date
    collides with an EXISTING path must not clobber. setup_workspace seeds
    5-photos-by-date/2023-01-01/2023-01-01--12-00-00.jpg = "already_date" and a 0-sources file
    (new_img, "new_source") that resolves to the same date/name. Prep must (a) plan a
    move_no_clobber to a suffixed name, never the occupied target, and (b) on execute, land the
    incoming under the safe -001 name while the colliding original stays byte-unchanged."""
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            return {"status": "valid", "strategy": "sha256-v1", "value": hashlib.sha256(f.read()).hexdigest()}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    occupied = ws / "5-photos-by-date" / "2023-01-01" / "2023-01-01--12-00-00.jpg"
    assert occupied.read_text() == "already_date"                 # the existing colliding target

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan1 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()

    # The plan moves new_img to a SAFE suffixed name, never onto the occupied path.
    mv = [op for op in plan1.operations
          if op.type == "move_no_clobber" and "new_img.jpg" in (op.source or "")]
    assert len(mv) == 1, [(o.type, o.source, o.destination) for o in plan1.operations]
    dest = mv[0].destination
    assert dest.startswith("5-photos-by-date/2023-01-01/2023-01-01--12-00-00-001"), dest
    assert dest != "5-photos-by-date/2023-01-01/2023-01-01--12-00-00.jpg"   # never the occupied name

    photos_ingest.PlanExecutor(str(ws)).execute(plan1, str(ws / ".photos-ingest/journal.json"))

    # The incoming landed under the safe name with its OWN content; the original is untouched.
    safe = ws / dest
    assert safe.exists() and safe.read_text() == "new_source"     # incoming placed safely
    assert occupied.read_text() == "already_date"                 # colliding original NOT clobbered


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
@pytest.mark.spec("prep-filesystem-source-of-truth-1", "prep-no-journal-replay-1", "prep-replan-not-resume-1")
def test_prep_replans_from_filesystem_when_journal_corrupt_or_deleted(mock_meta, tmp_path):
    """The prep journal is EVIDENCE, not a resume script: prep re-plans from the filesystem (+ cache)
    as truth. After a successful run, corrupting then deleting the journal must NOT change the re-plan
    — it still derives 0 operations from the on-disk state and never reads the journal to resume."""
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

    # Corrupt the journal to garbage — a resume-from-journal design would choke on this.
    with open(journal_path, "w") as f:
        f.write("}{ this is not json")
    cache2 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan2 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache2).plan()
    assert len(plan2.operations) == 0, "corrupt journal must not change the filesystem-derived plan"

    # Delete the journal entirely — re-plan still derives the same empty diff from disk + cache.
    os.remove(journal_path)
    cache3 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan3 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache3).plan()
    assert len(plan3.operations) == 0, "deleted journal must not resurrect already-applied operations"

    # State is intact regardless of the journal: the moved/by-dest files are still in place.
    assert (ws / "6-photos-by-dest" / "vacation" / "img1.jpg").read_text() == "already_dest"
    assert any(f.startswith("5-photos-by-date/2023-01-01/2023-01-01--12-00-00-001")
               for f in cache3.get_all_files().keys())


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
@pytest.mark.spec("prep-evidence-before-quarantine-1")
def test_quarantine_manifest_written_before_the_file_is_moved(mock_meta, tmp_path):
    """§14.3: the manifest evidence entry for a quarantined file is written BEFORE the file is moved
    into quarantine, so a crash never strands a file in quarantine with no record of why. Probe by
    wrapping both _append_quarantine_manifest and the move primitive _move_no_clobber to log a label
    in call order; setup_workspace's dup_img is the quarantined file. Assert the manifest append for
    the run precedes the quarantine move."""
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            return {"status": "valid", "strategy": "sha256-v1", "value": hashlib.sha256(f.read()).hexdigest()}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan1 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert any(op.type == "quarantine_move" and "dup_img" in (op.source or "")
               for op in plan1.operations), "dup_img must quarantine"

    events = []                                                   # ordered (label, payload) trace
    orig_manifest = photos_ingest._append_quarantine_manifest
    orig_move = photos_ingest._move_no_clobber

    def manifest_spy(manifest_dir, entry):
        events.append(("manifest", entry))
        return orig_manifest(manifest_dir, entry)

    def move_spy(src, dest):
        # the quarantine move targets the recoverable quarantine subtree
        label = "quarantine_move" if ".photos-ingest-quarantine" in dest else "move"
        events.append((label, dest))
        return orig_move(src, dest)

    monkeypatch_ctx = pytest.MonkeyPatch()
    monkeypatch_ctx.setattr(photos_ingest, "_append_quarantine_manifest", manifest_spy)
    monkeypatch_ctx.setattr(photos_ingest, "_move_no_clobber", move_spy)
    try:
        photos_ingest.PlanExecutor(str(ws)).execute(plan1, str(ws / ".photos-ingest/journal.json"))
    finally:
        monkeypatch_ctx.undo()

    labels = [e[0] for e in events]
    assert "manifest" in labels and "quarantine_move" in labels, labels
    # evidence-before-move: the manifest append precedes the quarantine move for that file
    assert labels.index("manifest") < labels.index("quarantine_move"), labels
    # and exactly one quarantine move occurred (dup_img), each preceded by its evidence write
    assert labels.count("quarantine_move") == 1
    # the file did land in quarantine (the move actually ran after the evidence)
    assert list((ws / ".photos-ingest-quarantine").rglob("dup_img.jpg"))


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
@pytest.mark.spec("prep-quarantine-restore-normal-1", "prep-restored-requarantine-if-dup-1")
def test_restored_quarantine_file_reflows_as_a_normal_dump(mock_meta, tmp_path):
    """No un-quarantine path: a file dragged back out of quarantine into 0-sources is re-evaluated as
    an ordinary fresh dump under a NEW plan_id — there is no special 'restore' handling that skips
    dedup. Here the restored file is still a duplicate of a by-dest photo, so it is quarantined AGAIN."""
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            v = hashlib.sha256(f.read()).hexdigest()
        return {"status": "valid", "strategy": "sha256-v1", "value": v}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan1 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert any(op.type == "quarantine_move" and "dup_img" in (op.source or "")
               for op in plan1.operations), "dup_img should quarantine on the first run"
    executor = photos_ingest.PlanExecutor(str(ws))
    executor.execute(plan1, str(ws / ".photos-ingest/journal.json"))

    # The dup now lives under the recoverable quarantine. Operator drags it back into the inbox.
    qfiles = list((ws / ".photos-ingest-quarantine").rglob("*.jpg"))
    assert qfiles, "the duplicate must have been quarantined by execute"
    shutil.move(str(qfiles[0]), str(ws / "0-sources" / "dup_img.jpg"))

    # Re-prep: the restored file is treated as a normal dump and re-evaluated (still a dup -> quarantine
    # again), under a fresh plan_id. No restore shortcut un-quarantined it.
    cache2 = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan2 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache2).plan()
    assert plan2.plan_id != plan1.plan_id
    assert any(op.type == "quarantine_move" and "dup_img" in (op.source or "")
               for op in plan2.operations), [(o.type, o.source) for o in plan2.operations]


@pytest.mark.spec("prep-missing-metadata-no-special-path-1")
def test_no_special_reimport_path_from_missing_metadata(tmp_path):
    """2-missing-metadata is a holding bay, not a re-entry point: prep never reprocesses a file sitting
    there in place. A file still missing a date stays put (no op); the way to re-import is to move it to
    0-sources, where it routes like any ordinary dump — here, to 5-photos-by-date by its (now present)
    date. No 2-missing-metadata-specific rescue path."""
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / ".photos-ingest").mkdir(); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / "2-missing-metadata" / "still_broken.jpg").write_text("nodate")   # left behind, no date
    (ws / "0-sources" / "fixed.jpg").write_text("hasdate")                  # moved back to the inbox

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                res[p] = {"DateTimeOriginal": "2023:05:05 09:00:00"} if "fixed" in f else {}
        return res, set()

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            return {"status": "valid", "strategy": "sha256-v1", "value": hashlib.sha256(f.read()).hexdigest()}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 1
    with mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=meta):
        cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
        plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()

    # The re-imported file routes normally to 5-photos-by-date by its date.
    assert any(op.type == "move_no_clobber" and "fixed.jpg" in (op.source or "")
               and (op.destination or "").startswith("5-photos-by-date/")
               for op in plan.operations), [(o.type, o.source, o.destination) for o in plan.operations]
    # The file still sitting in 2-missing-metadata is NOT reprocessed in place (no special rescue).
    assert not any("still_broken.jpg" in (op.source or "") for op in plan.operations), \
        [(o.type, o.source) for o in plan.operations]


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
@pytest.mark.spec("prep-cache-single-writer-1")
def test_prep_execute_cache_writes_only_from_main_thread(mock_meta, tmp_path):
    """Single-writer cache: prep applies its plan in one sequential op loop, so every DB write lands on
    the main thread even with jobs=4 (the concurrency in prep is read-only metadata extraction during
    planning, never DB writes). Probe upsert_file and assert no worker-thread write."""
    import threading
    ws = setup_workspace(tmp_path)

    def mock_hash_image(filepath):
        import hashlib
        with open(filepath, "rb") as f:
            return {"status": "valid", "strategy": "sha256-v1", "value": hashlib.sha256(f.read()).hexdigest()}

    photos_ingest.ContentHasher.fingerprint_image = mock_hash_image
    photos_ingest.CONFIG["jobs"] = 4                              # ask for concurrency

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    plan1 = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    assert any(op.type == "db_upsert" for op in plan1.operations)

    threads = []
    orig = photos_ingest.WorkspaceCache.upsert_file

    def spy(self, *a, **k):
        threads.append(threading.current_thread().name)
        return orig(self, *a, **k)

    photos_ingest.WorkspaceCache.upsert_file = spy
    try:
        photos_ingest.PlanExecutor(str(ws)).execute(plan1, str(ws / ".photos-ingest/journal.json"))
    finally:
        photos_ingest.WorkspaceCache.upsert_file = orig
    assert threads, "expected at least one cache upsert"
    assert all(t == "MainThread" for t in threads), threads


@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
@pytest.mark.spec("prep-handoff-min-contents-1")
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
@pytest.mark.spec("prep-block-on-stale-dependency-1", "prep-bydest-precondition-recorded-1", "prep-execute-revalidates-rejects-stale-1", "prep-handoff-only-on-success-1")
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
@pytest.mark.spec("prep-ghost-prune-1")
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