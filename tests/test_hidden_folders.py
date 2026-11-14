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

"""A hidden (dot-named) folder holding files inside a managed folder other than the inbox stops prep, naming
the folder: prep does not read into it, so its files would never be inventoried, fingerprinted, link-checked or
handed on. The re-prep gate geotag and prep's nothing-to-do guard share agrees with prep about it. An empty
hidden folder and hidden files stay as they are; hidden things in the inbox still go to the quarantine.
From conftest.py.
"""
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "strategy": utils.IMAGE_FINGERPRINT_STRATEGY,
                                   "value": "sig-" + os.path.basename(p), "engine_version": "t"})
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video",
                        lambda p: {"status": "valid", "strategy": utils.VIDEO_FINGERPRINT_STRATEGY,
                                   "value": "v-" + os.path.basename(p)})

    def meta(folders, max_workers=4, progress_coordinator=None):
        return {os.path.join(folder, f): {"DateTimeOriginal": "2023:01:02 03:04:05",
                                          "extraction_status": "extracted_ok"}
                for folder in folders for f in os.listdir(folder)}, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def _hidden_blockers(plan):
    return [b for b in plan.blockers if "hidden folder" in b.lower()]


@pytest.mark.parametrize("folder", ["2-missing-metadata", "3-redundant-jpgs", "4-videos-by-date",
                                    "5-photos-by-date/2023-01-02", "6-photos-by-dest/Trip"])
@pytest.mark.spec("RUL-hidden_folder_among_photos_blocks",
                  test="TST-hidden_folders-hidden_folder_holding_a_photo_blocks")
def test_hidden_folder_holding_a_photo_blocks(tmp_path, mocked, folder):
    ws = _ws(tmp_path)
    hidden = ws / folder / ".edits" / "deeper"
    hidden.mkdir(parents=True)
    (hidden / "IMG_1.jpg").write_bytes(b"jpeg")

    plan = _plan(ws)
    found = _hidden_blockers(plan)
    assert len(found) == 1 and f"{folder}/.edits" in found[0], plan.blockers
    assert "IMG_1.jpg" not in found[0]                       # the folder is named, once


@pytest.mark.spec("RUL-hidden_folder_among_photos_blocks",
                  test="TST-hidden_folders-hidden_folder_holding_any_file_blocks")
def test_hidden_folder_holding_any_file_blocks(tmp_path, mocked):
    """Any file counts, a hidden one or one of no media class too."""
    ws = _ws(tmp_path)
    for name, inner in ((".picasaoriginals", "notes.txt"), (".cache", ".index")):
        d = ws / "5-photos-by-date" / name
        d.mkdir()
        (d / inner).write_text("x")
    found = _hidden_blockers(_plan(ws))
    assert len(found) == 2, found
    assert any("5-photos-by-date/.picasaoriginals" in b for b in found)
    assert any("5-photos-by-date/.cache" in b for b in found)


@pytest.mark.spec("RUL-hidden_folder_among_photos_blocks", "RUL-not_inventoried",
                  test="TST-hidden_folders-empty_hidden_folder_and_hidden_files_left_alone")
def test_empty_hidden_folder_and_hidden_files_left_alone(tmp_path, mocked):
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / ".empty" / "inner").mkdir(parents=True)
    (ws / "6-photos-by-dest" / "Trip").mkdir()
    (ws / "6-photos-by-dest" / "Trip" / ".DS_Store").write_bytes(b"junk")
    (ws / "5-photos-by-date" / ".DS_Store").write_bytes(b"junk")

    plan = _plan(ws)
    assert _hidden_blockers(plan) == [] and plan.blockers == [], plan.blockers
    touched = {op.source for op in plan.operations} | {op.destination for op in plan.operations}
    assert not any(".DS_Store" in (p or "") for p in touched)
    # The empty one goes as any empty folder there goes.
    assert {(op.type, op.source) for op in plan.operations if ".empty" in (op.source or "")} \
        == {("rmdir", "5-photos-by-date/.empty/inner"), ("rmdir", "5-photos-by-date/.empty")}


@pytest.mark.spec("RUL-dump_hidden_files_quarantined",
                  test="TST-hidden_folders-inbox_hidden_folder_goes_to_quarantine")
def test_inbox_hidden_folder_goes_to_quarantine(tmp_path, mocked):
    """In the inbox a hidden folder does not block: everything in it — a photo too — goes to the
    quarantine, recoverable, as today."""
    ws = _ws(tmp_path)
    hidden = ws / "0-sources" / "trip" / ".thumbnails"
    hidden.mkdir(parents=True)
    (hidden / "IMG_1.jpg").write_bytes(b"jpeg")
    (hidden / ".meta").write_bytes(b"x")

    plan = _plan(ws)
    assert _hidden_blockers(plan) == [], plan.blockers
    quarantined = sorted(op.source for op in plan.operations if op.type == "quarantine_move")
    assert quarantined == ["0-sources/trip/.thumbnails/.meta", "0-sources/trip/.thumbnails/IMG_1.jpg"]


@pytest.mark.spec("RUL-hidden_folder_among_photos_blocks",
                  test="TST-hidden_folders-reprep_gate_agrees_with_prep")
def test_reprep_gate_agrees_with_prep(tmp_path, mocked):
    """The re-prep gate names the hidden folder prep blocks on — never a photo inside it, which no re-prep
    could record — and says nothing of an empty one."""
    ws = _ws(tmp_path)
    trip = ws / "6-photos-by-dest" / "Trip"
    (trip / ".empty").mkdir(parents=True)
    assert utils.by_dest_reprep_pending(str(ws), {"files": []}) is None
    assert _hidden_blockers(_plan(ws)) == []

    (trip / ".edits").mkdir()
    (trip / ".edits" / "notes.txt").write_text("x")
    assert utils.by_dest_reprep_pending(str(ws), {"files": []}) == "6-photos-by-dest/Trip/.edits"
    assert any("6-photos-by-dest/Trip/.edits" in b for b in _hidden_blockers(_plan(ws)))

    (trip / ".edits" / "IMG_1.jpg").write_bytes(b"jpeg")
    assert utils.by_dest_reprep_pending(str(ws), {"files": []}) == "6-photos-by-dest/Trip/.edits"
