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

"""Phase 6 — §5 fingerprint/version coverage + §14.3.7 single-transaction cache.
Phase D — fingerprint/hash terminology (§9.1): media carries a content fingerprint and no
byte hash; the handoff/cache use fingerprint terms.

Mocked hashing/metadata, fast. photos_1_prep / photos_utils come from conftest.py.
"""
import json
import os
import sqlite3

import photos_1_prep as prep
import photos_utils as utils
import pytest


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock(monkeypatch):
    monkeypatch.setattr(
        prep.ContentHasher, "fingerprint_image",
        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                   "value": "sig-" + os.path.basename(p), "engine_version": "t"},
    )

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _run(ws):
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)
    return plan


# --- #20 fingerprint/version coverage ---------------------------------------

@pytest.mark.spec("prep-fingerprint-algo-recorded-1")
def test_cache_meta_records_versions(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    meta = dict(prep.WorkspaceCache(str(ws)).conn.execute("SELECT key, value FROM meta").fetchall())
    assert meta["cache_schema_version"] == str(prep.CACHE_SCHEMA_VERSION)
    assert meta["fingerprint_algorithm_version"] == prep.FINGERPRINT_ALGORITHM_VERSION


def test_journal_is_version_stamped(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _run(ws)
    with open(utils.journal_path(str(ws), plan.plan_id)) as f:
        dep = json.load(f)["depends_on"]
    assert dep["tool"] == "photos-1-prep"
    assert dep["config_fingerprint"] == plan.config_fingerprint.value
    assert dep["plan_schema_version"] == prep.PLAN_SCHEMA_VERSION
    assert dep["cache_schema_version"] == prep.CACHE_SCHEMA_VERSION
    assert dep["fingerprint_algorithm_version"] == prep.FINGERPRINT_ALGORITHM_VERSION


@pytest.mark.spec("prep-artifacts-carry-depends-on-1", "prep-record-min-fingerprints-1", "BLD-prep_dependencies", test="TST-fingerprints-handoff_depends_on_coverage")
def test_handoff_depends_on_coverage(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    with open(utils.handoff_path(str(ws))) as f:
        dep = json.load(f)["depends_on"]
    assert dep["plan"]["schema_version"] == prep.PLAN_SCHEMA_VERSION
    assert dep["cache"]["schema_version"] == prep.CACHE_SCHEMA_VERSION
    assert dep["cache"]["fingerprint_algorithm_version"] == prep.FINGERPRINT_ALGORITHM_VERSION
    assert dep["cache"]["image_engine"] == "imagemagick"
    assert dep["effective_config"]["fingerprint"]
    assert dep["metadata_extractor"]["camera_group_key_version"] == utils.CAMERA_GROUP_KEY_VERSION
    assert dep["final_workspace_inventory"]["content_fingerprint"]
    assert dep["execution_journal"]["sha256"]


@pytest.mark.spec("BLD-prep_log_vouched", test="TST-fingerprints-handoff_vouches_for_the_prep_log")
def test_handoff_vouches_for_the_prep_log(tmp_path, monkeypatch):
    """Prep's execution records in its handoff the hash of the log it wrote — outside the handoff's content,
    so a pointer refreshed by a run that changed nothing makes nothing downstream stale."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    with open(utils.handoff_path(str(ws))) as f:
        handoff = json.load(f)
    assert handoff["depends_on"]["prep_log"]["sha256"] == utils.sha256_file(utils.prep_log_path(str(ws)))
    assert utils.prep_log_blocker(str(ws), handoff) is None
    moved = json.loads(json.dumps(handoff))
    moved["depends_on"]["prep_log"]["sha256"] = "0" * 64
    assert utils.handoff_content_fingerprint(moved) == handoff["content_fingerprint"]


@pytest.mark.spec("RUL-unchecked_counts_as_changed", test="TST-fingerprints-a_dependency_missing_or_unrecorded_stops_execution")
@pytest.mark.parametrize("damage", ["sorted_photo_gone", "metadata_dependencies_unrecorded"])
def test_a_dependency_missing_or_unrecorded_stops_execution(tmp_path, monkeypatch, damage):
    """A dependency that cannot be checked — its record gone, or the plan recording none — counts as
    changed: execution refuses the plan before its first change."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    sorted_photo = ws / "6-photos-by-dest" / "T" / "2023-01-02--03-04-05.jpg"
    sorted_photo.parent.mkdir()
    sorted_photo.write_bytes(b"BBBB")                            # read-only: a precondition of the plan
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert not plan.blockers, plan.blockers
    if damage == "sorted_photo_gone":
        sorted_photo.unlink()
    else:
        plan.metadata_dependencies = {}
    with pytest.raises(ValueError, match="Stale plan"):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "0-sources" / "a.jpg").exists()


# --- Phase D: fingerprint/hash terminology (§9.1) ---------------------------

@pytest.mark.spec("dep-fingerprint-invariant-1", "prep-byte-sha-artifacts-only-1", test="TST-fingerprints-media_carries_fingerprint_and_no_byte_hash")
def test_media_carries_fingerprint_and_no_byte_hash(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    row = next(r for k, r in prep.WorkspaceCache(str(ws)).get_all_files().items()
               if k.startswith("5-photos-by-date/"))
    assert row["content_hash"]          # identified by its decoded-content fingerprint
    assert row["hash"] is None          # media is never byte-hashed (§9.1)


def test_handoff_uses_fingerprint_status(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    with open(utils.handoff_path(str(ws))) as f:
        handoff = json.load(f)
    media = [e for e in handoff["files"] if e["relative_path"].startswith("5-photos-by-date/")]
    assert media and media[0]["fingerprint_status"] == "valid"
    assert "hash_status" not in media[0]


# --- #21 single-transaction cache effects -----------------------------------

def test_transaction_commits_on_success(tmp_path):
    cache = prep.WorkspaceCache(str(tmp_path))
    row = {"relative_path": "a", "absolute_path": "/a", "size": 1, "mtime_ns": 1,
           "inode": 1, "media_class": "image", "hash": "h", "content_hash": "ch",
           "last_seen_ns": 1}
    with cache.transaction():
        cache.upsert_file(row)
    assert "a" in cache.get_all_files()


def test_transaction_rolls_back_on_exception(tmp_path):
    cache = prep.WorkspaceCache(str(tmp_path))
    row = {"relative_path": "b", "absolute_path": "/b", "size": 1, "mtime_ns": 1,
           "inode": 1, "media_class": "image", "hash": "h", "content_hash": "ch",
           "last_seen_ns": 1}
    try:
        with cache.transaction():
            cache.upsert_file(row)
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "b" not in cache.get_all_files()   # rolled back


def test_default_writes_still_commit_per_op(tmp_path):
    cache = prep.WorkspaceCache(str(tmp_path))
    row = {"relative_path": "c", "absolute_path": "/c", "size": 1, "mtime_ns": 1,
           "inode": 1, "media_class": "image", "hash": "h", "content_hash": "ch",
           "last_seen_ns": 1}
    cache.upsert_file(row)                     # no batch
    assert "c" in prep.WorkspaceCache(str(tmp_path)).get_all_files()  # committed (fresh conn)


def test_execute_run_lands_all_cache_rows(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    rows = prep.WorkspaceCache(str(ws)).get_all_files()
    assert any(k.startswith("5-photos-by-date/") for k in rows), rows  # organized + cached
