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

"""Recognition + quarantine of orphaned exiftool artifacts.

A hard kill (SIGKILL/OOM/power loss) during a geotag metadata write can orphan exiftool's
`<media>_exiftool_tmp` intermediate. (A `<media>_original` is not one: it is the backup exiftool keeps of a
user's own edit, and is treated as any file of no media class.) The live original is always intact (the rename is atomic). Prep recognizes such leftovers,
pulls them out of the media inventory, and quarantines them (recoverable, never deleted) instead of
mis-parking them forever in 1-strays.

photos_1_prep / photos_utils come from conftest.py.
"""
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


# --- unit: the recognizer is precise --------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("IMG_1234.jpg_exiftool_tmp", "IMG_1234.jpg"),   # temp from -overwrite_original
    ("shot.CR2_exiftool_tmp", "shot.CR2"),           # case-insensitive ext
    ("shot.CR2_original", None),                     # a user's own backup, not a write's leftover
    ("clip.mp4_exiftool_tmp", "clip.mp4"),           # video
    ("IMG_1234.jpg", None),                          # a normal media file, no suffix
    ("notes_original", None),                        # no media extension under the suffix
    ("data.txt_original", None),                     # .txt is not media -> not an artifact
    ("_original", None),                             # nothing before the suffix
])
def test_exiftool_artifact_base(name, expected):
    assert utils.exiftool_artifact_base(name) == expected


# --- integration: prep quarantines a leftover in a managed folder ----------

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
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "strategy": "image-content-hash-v2",
                                   "value": "sig-" + os.path.basename(p), "engine_version": "t"})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "extraction_status": "extracted_ok",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


@pytest.mark.spec("RUL-write_leftovers_quarantined", test="TST-exiftool_leftovers-managed_folder_leftover_is_quarantined")
def test_managed_folder_leftover_is_quarantined(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    leftover = ws / "5-photos-by-date" / "2023" / "IMG_1.jpg_exiftool_tmp"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"partial-jpeg-bytes")

    plan = _plan(ws)
    q_ops = [op for op in plan.operations
             if op.type == "quarantine_move" and op.verification.get("kind") == "exiftool_leftover"]
    assert len(q_ops) == 1
    assert q_ops[0].source == "5-photos-by-date/2023/IMG_1.jpg_exiftool_tmp"
    # The leftover is NOT inventoried as media (excluded from the scanned file model).
    assert all("_exiftool_tmp" not in p["relative_path"] for p in plan.workspace_file_preconditions)

    prep.PlanExecutor(str(ws)).execute(plan)
    assert not leftover.exists()                                  # moved out of the managed folder
    qbase = utils.quarantine_dir(str(ws))
    moved = [os.path.join(r, f) for r, _d, fs in os.walk(qbase) for f in fs
             if f.endswith("_exiftool_tmp")]
    assert moved, "leftover should land in recoverable quarantine"
    # It must NOT have been parked in 1-strays.
    strays = [f for _r, _d, fs in os.walk(ws / "1-strays") for f in fs]
    assert not any(s.endswith("_exiftool_tmp") for s in strays)


@pytest.mark.spec("RUL-write_leftovers_by_dest_warned", "RUL-write_leftover_in_by_dest_warned", "BLD-write_leftover_quarantined",
                  test="TST-exiftool_leftovers-bydest_leftover_left_untouched_with_warning")
def test_bydest_leftover_left_untouched_with_warning(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    leftover = ws / "6-photos-by-dest" / "Trip" / "IMG_2.jpg_exiftool_tmp"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"partial")

    plan = _plan(ws)
    assert not [op for op in plan.operations
                if op.type == "quarantine_move" and op.verification.get("kind") == "exiftool_leftover"]
    assert any("by-dest" in w and "_exiftool_tmp" in w for w in plan.warnings)

    prep.PlanExecutor(str(ws)).execute(plan)
    assert leftover.exists()                                      # read-only staging untouched


# --- a user's own `<photo>_original` backup is not a write's leftover --------

import shutil
import subprocess

requires_exiftool = pytest.mark.skipif(shutil.which("exiftool") is None, reason="exiftool not available")
CAM_SMALL = os.path.join(os.path.dirname(__file__), "fixtures", "cam_small.jpg")


def _user_backup(folder, name="IMG_1.jpg"):
    """What exiftool leaves when the USER edits a photo with it: the edited photo, and beside it
    `<photo>_original`, the camera's original."""
    folder.mkdir(parents=True, exist_ok=True)
    photo = folder / name
    shutil.copy(CAM_SMALL, photo)
    subprocess.run(["exiftool", "-q", "-Artist=me", str(photo)], check=True, capture_output=True)
    backup = folder / (name + "_original")
    assert backup.exists()
    return backup


def _ops_for(plan, rel):
    return sorted((op.type, (op.verification or {}).get("kind")) for op in plan.operations if op.source == rel)


@requires_exiftool
@pytest.mark.spec("RUL-user_backup_is_a_stray", test="TST-exiftool_leftovers-inbox_user_backup_is_a_stray")
def test_inbox_user_backup_is_a_stray(tmp_path, monkeypatch):
    """A `<photo>_original` in the inbox goes where any file of no media class goes — to the strays,
    never to the quarantine as a leftover; a `<photo>_exiftool_tmp` beside it still does."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    backup = _user_backup(ws / "0-sources")
    (ws / "0-sources" / "notes.txt").write_text("a file of no media class")
    (ws / "0-sources" / "IMG_9.jpg_exiftool_tmp").write_bytes(b"partial")

    plan = _plan(ws)
    rel = "0-sources/" + backup.name
    assert _ops_for(plan, rel) == _ops_for(plan, "0-sources/notes.txt")
    assert not any(op.type == "quarantine_move" for op in plan.operations if op.source == rel)
    assert [op.source for op in plan.operations
            if op.type == "quarantine_move" and (op.verification or {}).get("kind") == "exiftool_leftover"] \
        == ["0-sources/IMG_9.jpg_exiftool_tmp"]

    prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "1-strays" / backup.name).exists() or any(
        f == backup.name for _r, _d, fs in os.walk(ws / "1-strays") for f in fs)


@requires_exiftool
@pytest.mark.spec("RUL-user_backup_is_a_stray", test="TST-exiftool_leftovers-organized_user_backup_is_any_other_file")
def test_organized_user_backup_is_any_other_file(tmp_path, monkeypatch):
    """Outside the inbox a `<photo>_original` is treated as a file of no media class there is: never
    quarantined as a leftover."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    day = ws / "5-photos-by-date" / "2023-01-02"
    backup = _user_backup(day)
    (day / "notes.txt").write_text("a file of no media class")

    plan = _plan(ws)
    rel = os.path.relpath(backup, ws)
    assert _ops_for(plan, rel) == _ops_for(plan, os.path.relpath(day / "notes.txt", ws))
    assert not any(op.type == "quarantine_move" for op in plan.operations if op.source == rel)
