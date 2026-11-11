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

"""The prep pipeline's stages (prep §7): duplicates set aside first and as found, the JPEG beside a RAW
and nothing else set aside, extension case taken in the move that files a file, strays as they came.

Mocked hashing (content bytes) and metadata (one fixed time), fast."""
import glob
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
TIME = "2023:01:02 03:04:05"
NAME = "2023-01-02--03-04-05"


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
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
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": TIME,
                                             "extraction_status": "extracted_ok", "raw_payload": "{}"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert plan.blockers == []
    return plan


def _run(ws):
    plan = _plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)
    return plan


def _media_ops(plan):
    return [(op.type, op.source, op.destination) for op in plan.operations
            if op.type in ("move_no_clobber", "rename_no_clobber", "quarantine_move")]


def _tree(ws):
    return sorted(os.path.relpath(p, ws) for p in glob.glob(str(ws / "**" / "*.*"), recursive=True)
                  if not os.path.relpath(p, ws).startswith(".photos-ingest"))


@pytest.mark.spec("RUL-redundant_jpeg_set_aside", "BLD-jpeg_extensions",
                  test="TST-prep_pipeline-only_the_jpeg_beside_a_raw_is_set_aside")
def test_only_the_jpeg_beside_a_raw_is_set_aside(tmp_path):
    """A RAW sets aside the JPEG of its name in its folder — `.jpg` or `.jpeg` — and no other image."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "shot.arw").write_bytes(b"raw1")
    (ws / "0-sources" / "shot.jpg").write_bytes(b"jpg1")
    (ws / "0-sources" / "shot.png").write_bytes(b"png1")       # same name, not a JPEG
    (ws / "0-sources" / "other.arw").write_bytes(b"raw2")
    (ws / "0-sources" / "other.JPEG").write_bytes(b"jpg2")     # a JPEG, any case
    _run(ws)
    redundant = sorted(os.listdir(ws / "3-redundant-jpgs"))
    assert redundant == [f"{NAME}.jpeg", f"{NAME}.jpg"], redundant
    day = os.listdir(ws / "5-photos-by-date" / "2023-01-02")
    assert any(n.endswith(".png") for n in day), day                # the PNG is filed as a photo


@pytest.mark.spec("RUL-duplicates_quarantined", "RUL-copy_kept_by_folder", "BLD-prep_stage_order",
                  test="TST-prep_pipeline-a_redumped_pair_settles_in_one_run")
def test_a_redumped_pair_settles_in_one_run(tmp_path):
    """A RAW+JPEG pair dumped again is set aside as duplicates in the run that finds it — the JPEG too —
    keeping the copies already filed; the next run has nothing to do."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "shot.arw").write_bytes(b"raw")
    (ws / "0-sources" / "shot.jpg").write_bytes(b"jpg")
    _run(ws)
    filed = _tree(ws)
    (ws / "0-sources" / "shot.arw").write_bytes(b"raw")
    (ws / "0-sources" / "shot.jpg").write_bytes(b"jpg")
    second = _run(ws)
    assert sorted((t, s) for t, s, _ in _media_ops(second)) == [
        ("quarantine_move", "0-sources/shot.arw"), ("quarantine_move", "0-sources/shot.jpg")]
    assert _tree(ws) == filed                                       # the filed copies kept, as they were
    assert _media_ops(_plan(ws)) == []


@pytest.mark.spec("RUL-copy_kept_by_folder", test="TST-prep_pipeline-copies_in_one_folder_keep_the_first_by_path")
def test_copies_in_one_folder_keep_the_first_by_path(tmp_path):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "b").mkdir()
    (ws / "0-sources" / "a").mkdir()
    (ws / "0-sources" / "b" / "x.jpg").write_bytes(b"same")
    (ws / "0-sources" / "a" / "y.jpg").write_bytes(b"same")
    plan = _plan(ws)
    quarantined = [s for t, s, _ in _media_ops(plan) if t == "quarantine_move"]
    assert quarantined == ["0-sources/b/x.jpg"]


@pytest.mark.spec("RUL-duplicate_set_aside_as_found", "BLD-prep_stage_order",
                  test="TST-prep_pipeline-a_duplicate_is_set_aside_as_found")
def test_a_duplicate_is_set_aside_as_found(tmp_path):
    """A duplicate goes to quarantine from its dump path under its dump name — no rename first — and its
    record names that path."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.JPG").write_bytes(b"same")
    (ws / "0-sources" / "b.JPG").write_bytes(b"same")
    plan = _run(ws)
    ops = _media_ops(plan)
    assert not any(t == "rename_no_clobber" for t, _, _ in ops), ops
    (q,) = [op for op in plan.operations if op.type == "quarantine_move"]
    assert q.source == "0-sources/b.JPG"
    assert q.destination.endswith("/0-sources/b.JPG")
    with open(ws / ".photos-ingest-quarantine" / plan.plan_id / "manifest.json") as f:
        assert json.load(f)[0]["original_path"] == "0-sources/b.JPG"


@pytest.mark.spec("RUL-media_extension_lowercase", "BLD-two_step_case_rename", "RUL-inbox_kept_as_dumped",
                  test="TST-prep_pipeline-an_inbox_file_takes_its_lowercase_extension_as_it_is_filed")
def test_an_inbox_file_takes_its_lowercase_extension_as_it_is_filed(tmp_path):
    """An inbox file is filed in one move that lowercases its extension: no rename inside the inbox."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "card").mkdir()
    (ws / "0-sources" / "card" / "IMG.JPG").write_bytes(b"AAAA")
    plan = _plan(ws)
    assert _media_ops(plan) == [("move_no_clobber", "0-sources/card/IMG.JPG",
                                 f"5-photos-by-date/2023-01-02/{NAME}.jpg")]


@pytest.mark.spec("RUL-inbox_non_media_to_strays", test="TST-prep_pipeline-a_stray_keeps_its_place_and_name")
def test_a_stray_keeps_its_place_and_name(tmp_path):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "card").mkdir()
    (ws / "0-sources" / "card" / "NOTES.TXT").write_bytes(b"hello")
    plan = _run(ws)
    assert (ws / "1-strays" / plan.plan_id / "card" / "NOTES.TXT").exists()
    assert not any(t == "rename_no_clobber" for t, _, _ in _media_ops(plan))


def _untimed(monkeypatch):
    """Metadata holding no recorded time, for every file."""
    def meta(folders, max_workers=4, progress_coordinator=None):
        return {os.path.join(fo, fn): {"extraction_status": "extracted_empty", "raw_payload": "{}"}
                for fo in folders for fn in os.listdir(fo)}, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


@pytest.mark.spec("RUL-untimed_mark_once", "DEF-untimed_name", "BLD-untimed_mark",
                  test="TST-prep_pipeline-a_file_back_from_missing_metadata_keeps_one_mark")
def test_a_file_back_from_missing_metadata_keeps_one_mark(tmp_path, monkeypatch):
    """A file sent back to the inbox with still no time returns to missing metadata under the name it
    had there: the untimed mark is not taken twice."""
    _untimed(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "foo.JPG").write_bytes(b"AAAA")
    _run(ws)
    assert os.listdir(ws / "2-missing-metadata") == ["UNKN_foo.jpg"]
    os.rename(ws / "2-missing-metadata" / "UNKN_foo.jpg", ws / "0-sources" / "UNKN_foo.jpg")
    _run(ws)
    assert os.listdir(ws / "2-missing-metadata") == ["UNKN_foo.jpg"]


@pytest.mark.spec("RUL-redundant_jpg_timestamp_named", "RUL-untimed_mark_once",
                  test="TST-prep_pipeline-an_untimed_redundant_jpeg_takes_its_untimed_name")
def test_an_untimed_redundant_jpeg_takes_its_untimed_name(tmp_path, monkeypatch):
    """A JPEG set aside beside its RAW with no recorded time takes its untimed name, flat — the mark once,
    however it came."""
    _untimed(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "shot.arw").write_bytes(b"raw1")
    (ws / "0-sources" / "shot.JPG").write_bytes(b"jpg1")
    (ws / "0-sources" / "UNKN_old.arw").write_bytes(b"raw2")
    (ws / "0-sources" / "UNKN_old.jpg").write_bytes(b"jpg2")
    _run(ws)
    assert sorted(os.listdir(ws / "3-redundant-jpgs")) == ["UNKN_old.jpg", "UNKN_shot.jpg"]


@pytest.mark.spec("RUL-database_matches_files", "BLD-database_ops",
                  test="TST-prep_pipeline-a_file_sent_back_is_refiled_where_it_was")
def test_a_file_sent_back_is_refiled_where_it_was(tmp_path):
    """A filed file the user moves back into the inbox is filed again under the name it had; the row of
    that path is the move's, not a ghost to prune."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "IMG.JPG").write_bytes(b"AAAA")
    _run(ws)
    filed = ws / "5-photos-by-date" / "2023-01-02" / f"{NAME}.jpg"
    os.rename(filed, ws / "0-sources" / f"{NAME}.jpg")
    plan = _run(ws)
    assert filed.exists()
    assert not any(op.type == "db_remove" for op in plan.operations)
    cache = prep.WorkspaceCache(str(ws))
    assert set(cache.get_all_files()) == {f"5-photos-by-date/2023-01-02/{NAME}.jpg"}
    cache.close()


@pytest.mark.spec("RUL-quarantined_leaves_database", "BLD-move_row_effects",
                  test="TST-prep_pipeline-a_quarantined_file_leaves_the_database")
def test_a_quarantined_file_leaves_the_database(tmp_path):
    """A duplicate set aside has no row in the database and no entry in the handoff; reclaiming the
    quarantine leaves the next plan nothing to do."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.JPG").write_bytes(b"same")
    (ws / "0-sources" / "b.JPG").write_bytes(b"same")
    plan = _run(ws)
    assert any(op.type == "quarantine_move" for op in plan.operations)
    filed = f"5-photos-by-date/2023-01-02/{NAME}.jpg"
    cache = prep.WorkspaceCache(str(ws))
    assert set(cache.get_all_files()) == {filed}
    cache.close()
    with open(utils.handoff_path(str(ws))) as f:
        assert [r["relative_path"] for r in json.load(f)["files"]] == [filed]
    import shutil
    shutil.rmtree(ws / ".photos-ingest-quarantine")
    assert [op.type for op in _plan(ws).operations if op.type.startswith("db_")] == []
