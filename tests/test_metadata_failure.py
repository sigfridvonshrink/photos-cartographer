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

"""A media file whose metadata prep could not read blocks its plan, in photos by destination as anywhere
(RUL-metadata_failure_blocks, BLD-metadata_failure_blocker). Mocked hashing and metadata, fast."""
import os

import photos_1_prep as prep
import photos_utils as utils
import pytest

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch, missing=(), failed_folders=()):
    """Hashing always works; metadata is read for every file but those in `missing` (left out of the batch's
    result) and every folder in `failed_folders` (its whole batch failed)."""
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1

    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res, failed = {}, set()
        for fo in folders:
            if os.path.basename(fo) in failed_folders:
                failed.add(fo)
                continue
            for fn in os.listdir(fo):
                if fn not in missing:
                    res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                                 "extraction_status": "extracted_ok"}
        return res, failed
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    try:
        return prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    finally:
        cache.close()


@pytest.mark.spec("RUL-metadata_failure_blocks", "BLD-metadata_failure_blocker", test="TST-metadata_failure-by_dest_photo_missing_from_the_batch_blocks")
def test_by_dest_photo_missing_from_the_batch_blocks(tmp_path, monkeypatch):
    # A photo of photos by destination whose metadata the batch did not return, with no record of it in the
    # database, blocks the plan — unlike a failed fingerprint there, which decides nothing.
    _install(monkeypatch, missing={"a.jpg"})
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Paris").mkdir()
    (ws / "6-photos-by-dest" / "Paris" / "a.jpg").write_bytes(b"pixels-a")
    (ws / "6-photos-by-dest" / "Paris" / "2023-01-02--03-04-05.jpg").write_bytes(b"pixels-b")
    plan = _plan(ws)
    assert plan.summary["metadata_plan_status"]["6-photos-by-dest/Paris/a.jpg"] == "extraction_failed"
    named = [b for b in plan.blockers if "6-photos-by-dest/Paris/a.jpg" in b and "Metadata" in b]
    assert named, plan.blockers
    assert not [b for b in plan.blockers if "Paris/2023" in b]           # the photo read is not blocked


@pytest.mark.spec("RUL-metadata_failure_blocks", "BLD-metadata_failure_blocker", test="TST-metadata_failure-by_dest_folder_whose_batch_failed_blocks")
def test_by_dest_folder_whose_batch_failed_blocks(tmp_path, monkeypatch):
    # The whole batch of a destination folder failed: each of its photos blocks, the inbox's photo does not.
    _install(monkeypatch, failed_folders={"Rome"})
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Rome").mkdir()
    (ws / "6-photos-by-dest" / "Rome" / "c.jpg").write_bytes(b"pixels-c")
    (ws / "0-sources" / "d.jpg").write_bytes(b"pixels-d")
    plan = _plan(ws)
    assert plan.summary["metadata_plan_status"]["6-photos-by-dest/Rome/c.jpg"] == "extraction_failed"
    assert any("6-photos-by-dest/Rome/c.jpg" in b and "Metadata" in b for b in plan.blockers), plan.blockers
    assert not any("d.jpg" in b for b in plan.blockers)


def _replan_with_failed_folder(monkeypatch, ws, folder, unread=()):
    """Plan once with every read working but for `unread` (left out of its batch), so the plan memo keeps a record
    still valid of each other file; then plan again with the whole batch of `folder` failing."""
    _install(monkeypatch, missing=set(unread))
    _plan(ws)
    _install(monkeypatch, failed_folders={folder})
    return _plan(ws)


@pytest.mark.spec("RUL-metadata_failure_blocks", "BLD-metadata_failure_blocker",
                  test="TST-metadata_failure-failed_folder_blocks_only_the_file_with_no_valid_record")
def test_failed_folder_blocks_only_the_file_with_no_valid_record(tmp_path, monkeypatch):
    """A folder whose batch failed, holding one photo of which prep keeps a record still valid and one of which it
    keeps none: the plan blocks naming the second only; the first's record is reused."""
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Rome").mkdir()
    (ws / "6-photos-by-dest" / "Rome" / "2023-01-02--03-04-05.jpg").write_bytes(b"pixels-kept")
    (ws / "6-photos-by-dest" / "Rome" / "unread.jpg").write_bytes(b"pixels-unread")
    plan = _replan_with_failed_folder(monkeypatch, ws, "Rome", unread={"unread.jpg"})
    status = plan.summary["metadata_plan_status"]
    assert status["6-photos-by-dest/Rome/2023-01-02--03-04-05.jpg"] == "reused_from_cache"
    assert status["6-photos-by-dest/Rome/unread.jpg"] == "extraction_failed"
    assert any("Rome/unread.jpg" in b and "Metadata" in b for b in plan.blockers), plan.blockers
    assert not any("Rome/2023-01-02--03-04-05.jpg" in b for b in plan.blockers), plan.blockers


@pytest.mark.spec("RUL-metadata_failure_blocks", "BLD-metadata_failure_blocker",
                  test="TST-metadata_failure-failed_folder_of_valid_records_blocks_nothing")
def test_failed_folder_of_valid_records_blocks_nothing(tmp_path, monkeypatch):
    """A folder whose batch failed, whose every photo has a record still valid (the folder is read for a file of no
    media class beside it): no metadata blocker, and the photo's record is reused."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "Rome").mkdir()
    (ws / "0-sources" / "Rome" / "a.jpg").write_bytes(b"pixels-a")
    (ws / "0-sources" / "Rome" / "notes.txt").write_bytes(b"a note")
    plan = _replan_with_failed_folder(monkeypatch, ws, "Rome")
    assert plan.summary["metadata_plan_status"]["0-sources/Rome/a.jpg"] == "reused_from_cache"
    assert not any("Metadata" in b or "a.jpg" in b for b in plan.blockers), plan.blockers
