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

"""Outside the inbox every media file carries the name the pipeline gave it, and the filename format
is fixed once prep has named files in it (shared contract §6)."""
import hashlib
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

TIME = "2023:01:02 03:04:05"
NAME = "2023-01-02--03-04-05"


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
def mocks(monkeypatch):
    """Every file is recorded at TIME, but for a name holding "notime", which has no recorded time."""
    def fp(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + hashlib.sha256(f.read()).hexdigest(), "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", fp)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                md = {"extraction_status": "extracted_ok", "raw_payload": "{}"}
                if "notime" not in f:
                    md["DateTimeOriginal"] = TIME
                res[os.path.join(folder, f)] = md
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    prep.CONFIG["jobs"] = 1


def _put(ws, rel, content=None):
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if content is not None else rel.encode())


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    try:
        return prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    finally:
        cache.close()


def _misnamed(plan):
    return [b for b in plan.blockers if b.startswith("Misnamed file")]


@pytest.mark.spec("RUL-misnamed_file_stops_prep", "RUL-misnamed_file_named", test="TST-filename_format-misnamed_file_outside_inbox_stops_prep")
def test_misnamed_file_outside_inbox_stops_prep(tmp_path, mocks):
    ws = _ws(tmp_path)
    fine = [f"5-photos-by-date/2023-01-02/{NAME}.jpg", f"5-photos-by-date/2023-01-02/{NAME}-001.jpg",
            f"6-photos-by-dest/Rome/{NAME}-002.jpg", f"3-redundant-jpgs/{NAME}.jpg",
            "2-missing-metadata/UNKN_notime.jpg", "6-photos-by-dest/Rome/UNKN_notime-b.jpg"]
    bad = ["5-photos-by-date/2023-01-02/holiday.jpg",              # renamed by hand
           "6-photos-by-dest/Rome/2023-01-02--03-04-06.jpg",       # another time than its own
           "3-redundant-jpgs/IMG_0001.jpg",                        # a dump name
           "2-missing-metadata/notime.jpg",                        # no untimed mark
           "6-photos-by-dest/Rome/notime-c.jpg"]                   # no time, no mark
    for rel in fine + bad:
        _put(ws, rel)
    found = _misnamed(_plan(ws))
    assert len(found) == len(bad), found
    for rel in bad:                                                # every one named, none of the rest
        assert sum(rel in b for b in found) == 1, (rel, found)


@pytest.mark.spec("RUL-no_meaning_from_names", test="TST-filename_format-inbox_name_off_its_time_named_from_metadata")
def test_inbox_name_off_its_time_named_from_metadata(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/2020-05-05--10-10-10.jpg")                 # looks like another time
    _put(ws, "0-sources/whatever.jpg", b"other")
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    dests = sorted(op.destination for op in plan.operations if op.type == "move_no_clobber")
    assert dests == [f"5-photos-by-date/2023-01-02/{NAME}-001.jpg", f"5-photos-by-date/2023-01-02/{NAME}.jpg"]


@pytest.mark.spec("RUL-misnamed_file_stops_prep", test="TST-filename_format-wrong_day_file_moves_without_blocker")
def test_wrong_day_file_moves_without_blocker(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, f"5-photos-by-date/2023-01-05/{NAME}.jpg")             # its name is right, its day folder not
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    assert [op.destination for op in plan.operations if op.type == "move_no_clobber"] == \
        [f"5-photos-by-date/2023-01-02/{NAME}.jpg"]


@pytest.mark.spec("RUL-redundant_jpg_timestamp_named", test="TST-filename_format-redundant_jpg_named_from_its_time")
def test_redundant_jpg_named_from_its_time(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/DSC_1.ARW")
    _put(ws, "0-sources/DSC_1.jpg")
    _put(ws, "0-sources/notime.ARW")
    _put(ws, "0-sources/notime.jpg")
    _put(ws, f"5-photos-by-date/2023-01-02/{NAME}.jpg")             # the timestamp name is taken
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    moved = {op.source: op.destination for op in plan.operations if op.type == "move_no_clobber"}
    assert moved["0-sources/DSC_1.jpg"] == f"3-redundant-jpgs/{NAME}-001.jpg"
    assert moved["0-sources/notime.jpg"] == "3-redundant-jpgs/UNKN_notime.jpg"


def _set_format(ws, fmt):
    p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(p.read_text())
    cfg["filename_timestamp_format"] = fmt
    p.write_text(json.dumps(cfg))


@pytest.mark.spec("RUL-format_fixed_once_named", test="TST-filename_format-format_change_after_naming_stops_prep")
def test_format_change_after_naming_stops_prep(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/a.jpg")
    _put(ws, "0-sources/b.jpg", b"b")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    handoff = json.loads(open(utils.handoff_path(str(ws))).read())
    assert handoff["filename_timestamp_format"] == "%Y-%m-%d--%H-%M-%S"   # the format the names are in
    _set_format(ws, "%Y%m%d_%H%M%S")
    plan = _plan(ws)
    assert _misnamed(plan) == []                                     # one blocker, not one per name
    assert [b for b in plan.blockers if "filename format has changed" in b] == [
        utils.filename_format_changed("%Y-%m-%d--%H-%M-%S", "%Y%m%d_%H%M%S")]


@pytest.mark.spec("RUL-format_fixed_once_named", test="TST-filename_format-format_free_while_nothing_named")
def test_format_free_while_nothing_named(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/notime.jpg")                                 # untimed: named by its mark only
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    _set_format(ws, "%Y%m%d_%H%M%S")
    _put(ws, "0-sources/a.jpg")
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    assert any(op.destination == "5-photos-by-date/2023-01-02/20230102_030405.jpg" for op in plan.operations)
