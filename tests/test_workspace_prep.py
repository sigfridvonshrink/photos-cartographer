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

# photos_1_prep is loaded once by conftest.py into sys.modules
import photos_1_prep as photos_ingest

def setup_workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    # An activated workspace must have the full 0-6 structure (the rest are created below).
    for _d in ("1-strays", "2-missing-metadata", "3-redundant-jpgs", "4-videos-by-date", "6-photos-by-dest"):
        (ws / _d).mkdir()

    # Initialized workspace: every dump lives in the 0-sources inbox (never at the root).
    source_dir = ws / "0-sources"
    source_dir.mkdir()

    # Case-collision pair inside the inbox (ext-norm two-step keeps both)
    (source_dir / "IMG_1234.JPG").write_text("image1234_data")
    (source_dir / "img_1234.jpg").write_text("image1234_different_data")

    # RAW/JPG pair in 0-sources
    (source_dir / "PHOTO_555.CR2").write_text("raw_data")
    (source_dir / "PHOTO_555.jpg").write_text("jpg_data")

    # Exact duplicate already organized in 5-photos-by-date
    photos_dir = ws / "5-photos-by-date"
    photos_dir.mkdir()
    (photos_dir / "20230101_120000-001.jpg").write_text("duplicate_data")

    # RAW and JPG with SAME content but shouldn't quarantine (in 0-sources)
    (source_dir / "RAW_SAME.CR2").write_text("same_hash_content")
    (source_dir / "RAW_SAME.jpg").write_text("same_hash_content")

    # Source duplicate in 0-sources
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

@mock.patch('photos_1_prep.ContentHasher.fingerprint_image', side_effect=mock_hash_image)
@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_prep_workflow_plan_and_execute(mock_meta, mock_hash_img, tmp_path, monkeypatch):
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
    journal_path = str(ws / ".photos-ingest/journal.json")
    executor.execute(plan, journal_path)

    # PR ACCEPTANCE TEST: root-to-"0-sources" collision where neither file is overwritten
    # IMG_1234.JPG moves from root to 0-sources. But 0-sources/img_1234.jpg exists!
    # They should both survive with deterministic suffix naming.
    assert not (ws / "IMG_1234.JPG").exists()

    files_in_dest = list((ws / "2-missing-metadata").iterdir())
    names_in_dest = [f.name.lower() for f in files_in_dest]

    count_1234 = sum(1 for name in names_in_dest if "1234" in name and name.endswith(".jpg"))
    assert count_1234 == 2, f"Expected 2 variants of img_1234 in dest, found {names_in_dest}"

    # PR ACCEPTANCE TEST: "IMG.JPG" vs "IMG.jpg" survival with deterministic naming;
    # (Tested implicitly by the above root-to-source case normalizations preserving both files)

    # PR ACCEPTANCE TEST: RAW/JPG not treated as disposable duplicates
    # PHOTO_555.CR2 and PHOTO_555.jpg have the same fake hash, but shouldn't quarantine.
    # The JPG should be in 3-redundant-jpgs. The RAW should be in 5-photos-by-date.
    assert (ws / "3-redundant-jpgs" / "PHOTO_555.jpg").exists()
    assert (ws / "5-photos-by-date" / "2023-02-02" / "2023-02-02--14-00-00.cr2").exists()   # lone file -> bare (§7.2)

    # PR ACCEPTANCE TEST: RAW/JPG pair (same content) is NOT quarantined — the jpg is the
    # redundant sibling (-> 3-redundant-jpgs), the raw is the master (-> 2-missing-metadata).
    assert any("raw_same" in f.name.lower() and f.name.lower().endswith(".jpg")
               for f in (ws / "3-redundant-jpgs").iterdir())
    names_in_mm = [f.name.lower() for f in (ws / "2-missing-metadata").iterdir()]
    assert any("raw_same" in name and name.endswith(".cr2") for name in names_in_mm)

# PR ACCEPTANCE TEST: quarantine manifest creation and structured evidence
    quarantine_base = ws / ".photos-ingest-quarantine" / plan.plan_id
    assert quarantine_base.exists()
    assert (quarantine_base / "0-sources" / "dup_image.jpg").exists()

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
    cache_conn = sqlite3.connect(executor.workspace_root + "/.photos-ingest/photos-00-ingest.db")
    cur = cache_conn.cursor()
    cur.execute("SELECT relative_path FROM file_cache")
    db_paths = [r[0] for r in cur.fetchall()]
    assert any("3-redundant-jpgs" in p for p in db_paths)
    assert any("5-photos-by-date" in p for p in db_paths)
    assert "IMG_1234.JPG" not in db_paths

# Assert no intermediate paths exist
    assert not any("0-sources/IMG_1234.JPG" in p for p in db_paths)
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

@mock.patch('photos_1_prep.ContentHasher.fingerprint_image', side_effect=mock_hash_image)
@mock.patch('photos_utils.MetadataReader.read_metadata_concurrently', side_effect=mock_read_metadata_concurrently)
def test_source_changed_after_plan_abort(mock_meta, mock_hash_img, tmp_path, monkeypatch):
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
    (ws / "0-sources" / "IMG_1234.JPG").write_text("modified_data_size_change")

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")

    import pytest
    with pytest.raises(ValueError, match="Precondition failed: size changed"):
        executor.execute(plan, journal_path)

def test_sidecar_blocking(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    ws = setup_workspace(tmp_path)
    photos_ingest.CONFIG["jobs"] = 1

    # PR ACCEPTANCE TEST: sidecar blocking
    (ws / "0-sources" / "PHOTO_555.xmp").touch()

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=False)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    assert len(plan.blockers) > 0
    assert "Forbidden sidecar files detected" in plan.blockers[0]

    executor = photos_ingest.PlanExecutor(str(ws))
    journal_path = str(ws / ".photos-ingest/journal.json")

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

    with mock.patch('photos_1_prep.ContentHasher.fingerprint_image', side_effect=mock_hash_fail), \
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
    # Create a symlink in 0-sources pointing outside
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("external")
    symlink_path = ws / "0-sources" / "symlink.txt"
    os.symlink(str(outside_file), str(symlink_path))

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    workflow = photos_ingest.WorkspacePrepWorkflow(str(ws), cache)
    plan = workflow.plan()

    assert len(plan.blockers) > 0
    assert any("Forbidden symlink detected" in b for b in plan.blockers)


def test_directory_symlink_at_root_blocked_during_init(tmp_path, monkeypatch):
    """A directory symlink at the root of an UNINITIALIZED workspace must be flagged as a forbidden
    symlink at PLAN time, never followed. os.path.isdir() follows a directory symlink, so the old
    isdir-first order let os.walk(path) traverse the external target and inventory (and plan a move
    for) files outside the workspace — the pipeline escape the spec forbids."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1

    external = tmp_path / "external"; external.mkdir()
    (external / "victim.jpg").write_bytes(b"PRECIOUS")          # a file the pipeline must NOT touch
    ws = tmp_path / "ws"; ws.mkdir(); (ws / ".photos-ingest").mkdir()   # uninitialized: no guard sentinel
    os.symlink(str(external), str(ws / "evil"))                # directory symlink at the root

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()

    assert any("Forbidden symlink detected: evil" in b for b in plan.blockers)
    # the external target was never walked: no operation references it, and the victim is untouched
    assert not any(op.source and "evil" in op.source for op in plan.operations)
    assert (external / "victim.jpg").exists()


def test_dot_named_directory_symlink_at_root_blocked(tmp_path, monkeypatch):
    """A DOT-named directory symlink at the root is forbidden too — it must not slip through the
    dotdir skip (os.path.isdir follows it, so it would otherwise be treated like the .photos-ingest
    control dir and silently ignored, leaving a pipeline-escape link in place)."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1
    external = tmp_path / "external"; external.mkdir()
    (external / "victim.jpg").write_bytes(b"PRECIOUS")
    ws = tmp_path / "ws"; ws.mkdir(); (ws / ".photos-ingest").mkdir()
    os.symlink(str(external), str(ws / ".evil"))                # DOT-named directory symlink at the root
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert any("Forbidden symlink detected: .evil" in b for b in plan.blockers), plan.blockers
    assert not any(op.source and "evil" in op.source for op in plan.operations)
    assert (external / "victim.jpg").exists()


def _empty_initialized_ws(tmp_path):
    """An initialized workspace with empty managed folders (no seeded media)."""
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / ".photos-ingest").mkdir(); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    return ws


def test_symlinked_managed_folder_blocked(tmp_path, monkeypatch):
    """A managed folder that is itself a symlink would let the managed-folder walk traverse its
    external target — the same escape as a root dump symlink. It must be flagged, not walked."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1
    external = tmp_path / "external"; external.mkdir(); (external / "e.jpg").write_bytes(b"E")
    ws = _empty_initialized_ws(tmp_path)
    os.rmdir(ws / "0-sources"); os.symlink(str(external), str(ws / "0-sources"))   # 0-sources is a symlink

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert any("Forbidden symlink detected: 0-sources" in b for b in plan.blockers), plan.blockers
    assert not any(op.source and "e.jpg" in (op.source or "") for op in plan.operations)


def test_nested_directory_symlink_in_managed_folder_blocked(tmp_path, monkeypatch):
    """os.walk does not descend into a subdirectory symlink (so it never escapes), but it must still
    be FLAGGED as forbidden rather than silently ignored."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1
    external = tmp_path / "external"; external.mkdir(); (external / "deep.jpg").write_bytes(b"D")
    ws = _empty_initialized_ws(tmp_path)
    os.symlink(str(external), str(ws / "0-sources" / "nested"))   # dir symlink INSIDE a managed folder

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert any("Forbidden symlink detected" in b and "nested" in b for b in plan.blockers), plan.blockers


def test_init_does_not_move_a_dump_folder_named_like_a_managed_folder(tmp_path, monkeypatch):
    """Reserved-name guard (prep §6.2): on an INIT run a base entry whose name collides with a managed
    folder (e.g. an as-arrived dump dir named `5-photos-by-date`) is treated AS that managed folder —
    NEVER inventoried as a dump and moved beneath itself into 0-sources/5-photos-by-date (a silent
    data-shuffling hazard). Assert no init-move op relocates it under 0-sources."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1
    ws = tmp_path / "ws"; ws.mkdir(); (ws / ".photos-ingest").mkdir()   # uninitialized: init run
    managed = ws / "5-photos-by-date"; managed.mkdir()                  # base dir named like a managed folder
    (managed / "photo.jpg").write_bytes(b"M")

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()

    # It is never moved beneath itself: no op relocates the folder (or its file) into 0-sources/...
    assert not any((op.destination or "").startswith("0-sources/5-photos-by-date")
                   for op in plan.operations), [op.destination for op in plan.operations]
    assert not any((op.source or "") == "5-photos-by-date" for op in plan.operations)
    assert not any("not a managed" in b or "Misplaced" in b for b in plan.blockers), plan.blockers


def test_initialized_root_dotfile_is_a_misplaced_entry_hard_block(tmp_path, monkeypatch):
    """Root strictness (prep §6.2 item 2): on an INITIALIZED workspace the root holds only the managed
    folders + control dirs. A plain root dotfile (e.g. `.DS_Store`) is a misplaced dump and a hard
    block — the dot-prefix earns no exemption for files (only dot DIRS are control/skip dirs)."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1
    ws = _empty_initialized_ws(tmp_path)
    (ws / ".DS_Store").write_bytes(b"junk")                             # a plain root dotfile

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert any("Misplaced entry at workspace root" in b and ".DS_Store" in b
               for b in plan.blockers), plan.blockers


def test_plan_is_non_mutating(tmp_path, monkeypatch):
    """Planning NEVER mutates the workspace: workflow.plan() derives operations but applies none —
    0-sources is byte-identical afterwards and no journal/handoff artifact is written (those are
    execute-only)."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image", mock_hash_image)
    photos_ingest.CONFIG["jobs"] = 1
    ws = setup_workspace(tmp_path)

    def snap(d):
        return {os.path.relpath(os.path.join(r, f), d): open(os.path.join(r, f), "rb").read()
                for r, _dn, fns in os.walk(d) for f in fns}

    before = snap(str(ws / "0-sources"))
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()

    assert len(plan.operations) > 0                              # there WAS work to do
    assert snap(str(ws / "0-sources")) == before                # ...but the inbox is untouched
    cd = ws / ".photos-ingest"
    assert not (cd / "journal.json").exists()                   # no journal (execute-only)
    assert not (cd / "photos-11-handoff.json").exists()         # no handoff (execute-only)


def test_gpx_root_inside_managed_tree_is_skipped(tmp_path, monkeypatch, seed_from_live_config):
    """Defensive GPX skip (shared contract §8.2): a gpx_root misconfigured to resolve inside a managed
    folder must be skipped during scanning so the GPX tracks are never organized / swept to strays —
    while ordinary media in the same managed folder is still organized."""
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "sig-" + os.path.basename(p),
                                   "strategy": "image-content-hash-v1", "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1
    ws = _empty_initialized_ws(tmp_path)
    gpx_dir = ws / "0-sources" / "gpx_tracks"; gpx_dir.mkdir()
    (gpx_dir / "track1.gpx").write_text("<gpx/>")
    (ws / "0-sources" / "photo.jpg").write_bytes(b"P")            # normal media — still organized
    monkeypatch.setitem(photos_ingest.CONFIG, "gpx_root", str(gpx_dir))   # misconfigured inside 0-6

    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert not any(op.source and "track1.gpx" in (op.source or "") for op in plan.operations), \
        "the misconfigured-in-tree gpx_root subtree must be skipped, not organized"
    assert any(op.source and op.source.endswith("photo.jpg") for op in plan.operations)


def test_deterministic_temp_names_with_existing(tmp_path, monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)

    # Minimal fixture explicitly constructed to trigger the suffix logic precisely
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()

    src_dir = ws / "0-sources"
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
    cfg_sha = utils.load_or_seed_config(str(ws))

    # Hand build a plan and verify executor fails it without making a DB
    plan = photos_ingest.Plan(
        plan_version=1,
        plan_id="dummy",
        command="prep",
        created_at="now",
        workspace_root=str(ws),
        digikam_root=None,
        config_fingerprint=photos_ingest.Fingerprint("sha256", cfg_sha),
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
    journal_path = str(ws / ".photos-ingest/journal.json")
    db_path = str(ws / ".photos-ingest/photos-00-ingest.db")

    assert not os.path.exists(db_path)

    import pytest
    with pytest.raises(ValueError, match="Precondition failed"):
        executor.execute(plan, journal_path)

    assert not os.path.exists(db_path)


def _mock_for_plan(monkeypatch):
    import photos_utils as utils
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", mock_read_metadata_concurrently)
    monkeypatch.setattr(photos_ingest.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "value": "s", "strategy": "image-content-hash-v1",
                                   "engine_version": "t"})
    photos_ingest.CONFIG["jobs"] = 1


def test_missing_managed_folder_on_activated_workspace_hard_stops(tmp_path, monkeypatch):
    """An activated workspace (guard present) missing managed 0-6 folder(s) is non-conforming — prep
    hard-stops with a blocker rather than silently recreating them (which could mask lost media)."""
    _mock_for_plan(monkeypatch)
    ws = _empty_initialized_ws(tmp_path)
    import shutil
    shutil.rmtree(ws / "5-photos-by-date")                            # user deleted a managed folder
    (ws / "1-strays").rmdir()                                          # ...and another
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert any("non-conforming" in b and "1-strays" in b and "5-photos-by-date" in b
               for b in plan.blockers), plan.blockers


def test_missing_folder_during_init_is_exempt(tmp_path, monkeypatch):
    """An uninitialized workspace (no guard) is exempt — prep's first run CREATES the 0-6 structure."""
    _mock_for_plan(monkeypatch)
    ws = tmp_path / "ws"; ws.mkdir(); (ws / ".photos-ingest").mkdir()   # no guard -> uninitialized
    cache = photos_ingest.WorkspaceCache(str(ws), in_memory=True)
    plan = photos_ingest.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert not any("non-conforming" in b for b in plan.blockers)
    assert any(op.type == "mkdir" for op in plan.operations)           # init plans the structure
