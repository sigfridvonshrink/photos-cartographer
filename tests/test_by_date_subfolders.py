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

"""By-date organization groups media into YYYY-MM-DD/ day subfolders.

Timestamped photos/videos land in `<band>/YYYY-MM-DD/<full-timestamp-name>`; untimestamped media
stays flat in `2-missing-metadata`. Pre-existing FLAT by-date files are migrated into their day folder
on a later run, and a file already in its conforming day folder is a no-op.

photos_1_prep / photos_utils come from conftest.py.
"""
import glob
import os

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock(monkeypatch, date_for):
    """date_for(basename) -> "YYYY:MM:DD HH:MM:SS" or None (untimestamped)."""
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                                   "value": "sig-" + os.path.basename(p), "engine_version": "t"})
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video",
                        lambda p: {"status": "valid", "strategy": "video-md5-v1",
                                   "value": "vsig-" + os.path.basename(p)})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                d = date_for(f)
                rec = {"extraction_status": "extracted_ok", "raw_payload": "{}"}
                if d:
                    rec["DateTimeOriginal"] = d
                res[os.path.join(folder, f)] = rec
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def test_photo_lands_in_day_subfolder(tmp_path, monkeypatch):
    _mock(monkeypatch, lambda f: "2023:07:04 14:30:05")
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"img")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    assert (ws / "5-photos-by-date" / "2023-07-04" / "2023-07-04--14-30-05.jpg").exists()
    assert list((ws / "0-sources").iterdir()) == []


def test_video_lands_in_day_subfolder(tmp_path, monkeypatch):
    _mock(monkeypatch, lambda f: "2023:07:04 14:30:05")
    ws = _ws(tmp_path)
    (ws / "0-sources" / "clip.mp4").write_bytes(b"vid")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    assert (ws / "4-videos-by-date" / "2023-07-04" / "2023-07-04--14-30-05.mp4").exists()


def test_untimestamped_stays_flat_in_missing_metadata(tmp_path, monkeypatch):
    _mock(monkeypatch, lambda f: None)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "nodate.jpg").write_bytes(b"img")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    assert (ws / "2-missing-metadata" / "UNKN_nodate.jpg").exists()        # flat, no day folder


def test_same_day_collides_other_day_does_not(tmp_path, monkeypatch):
    # a.jpg and b.jpg share a timestamp (same day -> collision -> suffix); c.jpg is another day (no
    # collision -> bare), proving the day folder alone separates same-name files across days.
    dates = {"a.jpg": "2023:07:04 14:30:05", "b.jpg": "2023:07:04 14:30:05",
             "c.jpg": "2023:07:05 14:30:05"}
    _mock(monkeypatch, lambda f: dates[f])
    ws = _ws(tmp_path)
    for n in dates:
        (ws / "0-sources" / n).write_bytes(b"x" + n.encode())
    dests = {op.destination for op in _plan(ws).operations
             if op.type == "move_no_clobber" and op.source.startswith("0-sources/")}
    assert dests == {
        "5-photos-by-date/2023-07-04/2023-07-04--14-30-05.jpg",
        "5-photos-by-date/2023-07-04/2023-07-04--14-30-05-001.jpg",
        "5-photos-by-date/2023-07-05/2023-07-05--14-30-05.jpg",
    }, dests


def test_existing_flat_file_is_migrated_into_day_folder(tmp_path, monkeypatch):
    _mock(monkeypatch, lambda f: "2023:07:04 14:30:05")
    ws = _ws(tmp_path)
    flat = ws / "5-photos-by-date" / "2023-07-04--14-30-05.jpg"            # legacy flat placement
    flat.write_bytes(b"img")
    plan = _plan(ws)
    moves = [op for op in plan.operations if op.type == "move_no_clobber"
             and op.source == "5-photos-by-date/2023-07-04--14-30-05.jpg"]
    assert moves and moves[0].destination == "5-photos-by-date/2023-07-04/2023-07-04--14-30-05.jpg"
    prep.PlanExecutor(str(ws)).execute(plan)
    assert not flat.exists()
    assert (ws / "5-photos-by-date" / "2023-07-04" / "2023-07-04--14-30-05.jpg").exists()


def test_conforming_file_is_a_noop(tmp_path, monkeypatch):
    _mock(monkeypatch, lambda f: "2023:07:04 14:30:05")
    ws = _ws(tmp_path)
    day = ws / "5-photos-by-date" / "2023-07-04"
    day.mkdir()
    (day / "2023-07-04--14-30-05.jpg").write_bytes(b"img")                 # already in its day folder
    plan = _plan(ws)
    assert not [op for op in plan.operations
                if op.type in ("move_no_clobber", "rename_no_clobber")], \
        [op.type for op in plan.operations]
