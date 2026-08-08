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

"""Plan-time decode memo (prep Section 10.3).

Cache rows are written by execute only, so before the memo a plan that was never executed
threw away every fingerprint it computed and the next plan re-decoded the whole workspace.
The memo remembers those observations in its own database so a re-plan reuses them — without
the workspace cache losing its meaning as the state of the EXECUTED workspace, and without
planning gaining write access to it.

Hashing/metadata are mocked; `fingerprint_image` is a spy so a reused fingerprint is provably
not recomputed. photos_1_prep / photos_utils come from conftest.py.
"""
import glob
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


def _install_mocks(monkeypatch, hash_calls):
    def spy(p):
        hash_calls.append(p)
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", spy)
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "t")   # match the spy's engine_version

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


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


def _memo_stats(plan):
    rs = plan.summary["performance_and_cache"]["rehash_summary"]
    return rs["memo_reused"], rs["memo_rows"], rs["total"]


def _seed(ws, n=2):
    for i in range(n):
        (ws / "0-sources" / f"a{i}.jpg").write_bytes(b"CONTENT-%d" % i)
    prep.CONFIG["jobs"] = 1


@pytest.mark.spec("prep-plan-memo-reuse-1")
def test_replan_without_execute_reuses_fingerprints(tmp_path, monkeypatch):
    """The point of the memo: plan, do NOT execute, plan again — the second plan decodes nothing.
    Before the memo this re-hashed the whole workspace, because cache rows are written by execute."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 2)

    plan1 = _plan(ws)
    assert len(hash_calls) == 2                      # first plan really decodes
    reused1, rows1, total1 = _memo_stats(plan1)
    assert (reused1, rows1, total1) == (0, 2, 2)

    hash_calls.clear()
    plan2 = _plan(ws)
    assert hash_calls == []                          # nothing decoded again
    reused2, rows2, total2 = _memo_stats(plan2)
    assert (reused2, rows2, total2) == (2, 2, 0)

    # The reused identity is the same one the first plan computed, not a placeholder.
    def _hashes(plan):
        return sorted(fx["data"]["content_hash"]
                      for op in plan.operations if op.type == "move_no_clobber"
                      for fx in op.database_effects_after_verification if fx.get("action") == "upsert")
    assert _hashes(plan2) == _hashes(plan1)


@pytest.mark.spec("prep-plan-memo-not-the-cache-1")
def test_plan_does_not_write_the_workspace_cache(tmp_path, monkeypatch):
    """The memo must not become a back door into the cache: planning still leaves file_cache empty,
    and the memo lives in its own database file."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 1)
    _plan(ws)

    cache = prep.WorkspaceCache(str(ws))
    assert cache.get_all_files() == {}
    cache.close()
    assert os.path.exists(utils.plan_memo_db_path(str(ws)))
    assert utils.plan_memo_db_path(str(ws)) != utils.db_path(str(ws))


@pytest.mark.spec("prep-plan-memo-subordinate-1")
def test_executed_cache_wins_over_the_memo(tmp_path, monkeypatch):
    """A cache row is the executed state and always outranks a memo row for the same path: after
    execute, reuse is attributed to the cache (memo_reused 0), not to the memo."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 1)
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    organized = glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)
    assert len(organized) == 1

    hash_calls.clear()
    reused, _rows, total = _memo_stats(_plan(ws))
    assert hash_calls == []                          # reused, whichever source
    assert (reused, total) == (0, 0)                 # ... and the source was the cache


@pytest.mark.spec("prep-plan-memo-freshness-1")
def test_changed_file_is_not_reused_from_the_memo(tmp_path, monkeypatch):
    """A memo row faces the same freshness gate as a cache row: bump the mtime and it is rejected,
    the file is re-decoded, and the re-hash diagnostic names a reason rather than staying silent."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 1)
    _plan(ws)

    os.utime(ws / "0-sources" / "a0.jpg", ns=(10**18, 10**18))
    hash_calls.clear()
    plan2 = _plan(ws)
    assert len(hash_calls) == 1
    reused, _rows, total = _memo_stats(plan2)
    assert reused == 0 and total == 1
    assert plan2.summary["performance_and_cache"]["rehash_summary"]["by_reason"] == {"mtime-changed": 1}


@pytest.mark.spec("prep-plan-memo-freshness-1")
def test_engine_change_invalidates_memo_rows(tmp_path, monkeypatch):
    """The memo stores the engine version bound to each pixel signature, so an ImageMagick bump
    restales memo rows exactly as it restales cache rows."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 1)
    _plan(ws)

    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "t2")   # engine upgraded
    hash_calls.clear()
    plan2 = _plan(ws)
    assert len(hash_calls) == 1
    assert plan2.summary["performance_and_cache"]["rehash_summary"]["by_reason"] == {"engine-changed": 1}


@pytest.mark.spec("prep-plan-memo-pruned-1")
def test_memo_drops_paths_it_no_longer_sees(tmp_path, monkeypatch):
    """The memo tracks the workspace instead of growing forever: a file that disappears loses its row."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 2)
    _plan(ws)

    os.remove(ws / "0-sources" / "a1.jpg")
    _plan(ws)
    memo = utils.PlanFingerprintMemo(str(ws))
    rows = memo.load()
    memo.close()
    assert sorted(rows) == ["0-sources/a0.jpg"]


@pytest.mark.spec("prep-plan-memo-disposable-1")
def test_a_broken_memo_degrades_instead_of_failing_the_plan(tmp_path, monkeypatch):
    """The memo is an accelerator, never a dependency: a corrupt memo database costs the decode it
    was saving and nothing else — the plan still completes."""
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    _seed(ws, 1)
    _plan(ws)

    with open(utils.plan_memo_db_path(str(ws)), "wb") as f:
        f.write(b"this is not a database")
    hash_calls.clear()
    plan2 = _plan(ws)
    assert len(hash_calls) == 1                      # fell back to decoding
    assert plan2.summary["blockers_found"] == 0
    assert _memo_stats(plan2)[0] == 0


def test_memo_skips_records_it_could_never_reuse(tmp_path, monkeypatch):
    """Only complete observations are stored. A record without a metadata row could not satisfy the
    all-or-nothing freshness gate, so storing it would buy nothing and relabel its re-hash reason."""
    memo = utils.PlanFingerprintMemo(str(tmp_path), in_memory=True)
    written = memo.replace_all([
        {"relative_path": "a.jpg", "size": 1, "mtime_ns": 2,
         "content_hash": json.dumps({"status": "valid"}), "metadata": {"extractor": "exiftool"}},
        {"relative_path": "b.jpg", "size": 1, "mtime_ns": 2,
         "content_hash": json.dumps({"status": "valid"}), "metadata": None},   # extraction failed
        {"relative_path": "c.txt", "size": 1, "mtime_ns": 2,
         "content_hash": None, "metadata": {"extractor": "exiftool"}},         # non-media
    ])
    assert written == 1
    assert sorted(memo.load()) == ["a.jpg"]
    memo.close()


def test_memo_row_is_rejected_when_it_disagrees_with_its_own_key(tmp_path, monkeypatch):
    """A row whose stored record contradicts its (size, mtime_ns) key is dropped rather than trusted —
    the memo is disposable, so an inconsistency costs a re-decode, never a wrong identity."""
    path = utils.plan_memo_db_path(str(tmp_path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    memo = utils.PlanFingerprintMemo(str(tmp_path))
    memo.replace_all([{"relative_path": "a.jpg", "size": 1, "mtime_ns": 2,
                       "content_hash": json.dumps({"status": "valid"}),
                       "metadata": {"extractor": "exiftool"}}])
    memo.close()

    conn = sqlite3.connect(path)
    with conn:
        conn.execute("UPDATE plan_fingerprint_memo SET mtime_ns = 999")
    conn.close()

    memo = utils.PlanFingerprintMemo(str(tmp_path))
    assert memo.load() == {}
    memo.close()
