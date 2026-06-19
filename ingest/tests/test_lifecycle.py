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

"""Phase B1 — dump-intake & workspace lifecycle.

Init (uninitialized -> create 0-6, move base dump into 0-sources structure-preserved, guard
written last), no-flatten, and the initialized-workspace root-file block. Mocked hashing/
metadata, fast. photos_1_prep / photos_utils come from conftest.py.
"""
import glob
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _bare(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws                       # no control dir, no guard, no managed folders


def _initialized(tmp_path):
    ws = _bare(tmp_path)
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1
    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                             "extraction_status": "extracted_ok", "raw_payload": "{}"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


def _guard(ws):
    return utils.guard_path(str(ws))


# --- initialization ----------------------------------------------------------

def test_init_creates_structure_and_moves_dump_structure_preserved(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _bare(tmp_path)
    (ws / "photo.jpg").write_bytes(b"img")
    (ws / "MyDump" / "sub").mkdir(parents=True)
    (ws / "MyDump" / "sub" / "a.jpg").write_bytes(b"img2")

    assert not os.path.exists(_guard(ws))                      # uninitialized
    plan = _plan(ws)
    assert not plan.blockers, plan.blockers
    assert {op.destination for op in plan.operations if op.type == "mkdir"} >= set(MANAGED)
    moves = {(op.source, op.destination) for op in plan.operations
             if op.reason and "Initialize: move" in op.reason}
    assert ("photo.jpg", "0-sources/photo.jpg") in moves          # structure preserved
    assert ("MyDump/sub/a.jpg", "0-sources/MyDump/sub/a.jpg") in moves

    prep.PlanExecutor(str(ws)).execute(plan)
    assert os.path.exists(_guard(ws))                          # sentinel written (last)
    for d in MANAGED:
        assert (ws / d).is_dir()
    assert len(glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)) == 2   # both organized
    # base is folders-only and 0-sources is left empty (no leftover dump skeleton)
    assert not (ws / "MyDump").exists()                        # init-move source pruned
    assert list((ws / "0-sources").iterdir()) == []
    # and a SECOND run does not block on a leftover (the base is clean)
    assert not _plan(ws).blockers


def test_guard_written_last_then_reentry_is_clean(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _bare(tmp_path)
    (ws / "photo.jpg").write_bytes(b"img")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    assert os.path.exists(_guard(ws))

    os.remove(_guard(ws))                                      # simulate a crash before the guard
    plan2 = _plan(ws)                                          # next run re-enters init harmlessly
    assert not plan2.blockers
    prep.PlanExecutor(str(ws)).execute(plan2)
    assert os.path.exists(_guard(ws))                          # re-written
    assert len(glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)) == 1  # still organized, no dup


# --- root-file block (initialized) -------------------------------------------

def test_loose_root_file_blocks_initialized(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "stray.jpg").write_bytes(b"img")                     # loose file at the base
    plan = _plan(ws)
    assert any("Misplaced entry at workspace root" in b and "stray.jpg" in b for b in plan.blockers), plan.blockers


def test_nonmanaged_root_dir_blocks_initialized(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "MyDump").mkdir()
    (ws / "MyDump" / "a.jpg").write_bytes(b"img")
    plan = _plan(ws)
    assert any("Misplaced entry at workspace root" in b and "MyDump" in b for b in plan.blockers), plan.blockers


def test_dump_in_sources_works_on_initialized(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"img")
    plan = _plan(ws)
    assert not plan.blockers, plan.blockers


# --- no-flatten --------------------------------------------------------------

def test_no_flatten_organizes_subtree_without_consolidation(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "0-sources" / "A" / "B").mkdir(parents=True)
    (ws / "0-sources" / "A" / "B" / "x.jpg").write_bytes(b"img")
    plan = _plan(ws)
    # no consolidation move within 0-sources; it organizes straight to the by-date band
    assert not any(op.reason and "Initialize: move" in op.reason for op in plan.operations)
    org = [op for op in plan.operations if op.type == "move_no_clobber"
           and op.source == "0-sources/A/B/x.jpg"]
    assert org and org[0].destination.startswith("5-photos-by-date/"), org


def test_no_flatten_same_name_distinct_subtrees_both_survive(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "0-sources" / "A").mkdir()
    (ws / "0-sources" / "B").mkdir()
    (ws / "0-sources" / "A" / "x.jpg").write_bytes(b"AAAA")    # distinct content
    (ws / "0-sources" / "B" / "x.jpg").write_bytes(b"BBBB")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    organized = glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)
    assert len(organized) == 2, organized                     # both survive with distinct names
