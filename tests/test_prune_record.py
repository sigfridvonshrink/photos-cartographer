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

"""A prune that deletes records what it deletes and when, before it deletes, in photos-16-prune-record.json; a later
prune sets the earlier record aside under -NNN (RUL-prune_recorded, RUL-prune_record_kept, BLD-prune_record)."""
import json
import os
import shutil

import pytest

import photos_1_prep as prep
import photos_utils as utils

A = "20200101T000000Z-aaaaaa"
B = "20200202T000000Z-bbbbbb"


def _ws(tmp_path):
    ws = tmp_path / "ws"
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir(parents=True)
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    qbase = utils.quarantine_dir(str(ws))
    for run, files in ((A, {"0-sources/dup.jpg": b"twelve bytes"}), (B, {"0-sources/sub/x.jpg": b"xx"})):
        manifest = []
        for rel, data in files.items():
            os.makedirs(os.path.dirname(os.path.join(qbase, run, rel)), exist_ok=True)
            with open(os.path.join(qbase, run, rel), "wb") as f:
                f.write(data)
            manifest.append({"original_path": rel, "retained_counterpart": "5-photos-by-date/k.jpg"})
        with open(os.path.join(qbase, run, "manifest.json"), "w") as f:
            json.dump(manifest, f)
    return str(ws), qbase


def _record(ws):
    with open(utils.prune_record_path(ws)) as f:
        return json.load(f)


@pytest.mark.spec("RUL-prune_recorded", "BLD-prune_record", "RUL-prune_only_quarantine", test="TST-prune_record-a_deleting_prune_records_what_it_deletes_first")
def test_a_deleting_prune_records_what_it_deletes_first(tmp_path, monkeypatch):
    """The record is whole before the first folder goes: each removed run's files with their bytes, and what its
    manifest said; nothing else changes outside the quarantine."""
    ws, qbase = _ws(tmp_path)
    seen = []
    real = shutil.rmtree

    def rmtree(path, *a, **k):
        seen.append(os.path.exists(utils.prune_record_path(ws)))
        return real(path, *a, **k)
    monkeypatch.setattr(shutil, "rmtree", rmtree)
    before = sorted(os.listdir(os.path.join(ws, ".photos-ingest")))
    prep.prune_quarantine(ws, plan_ids=[A], do_delete=True)
    assert seen == [True]                                             # recorded before it deleted
    assert sorted(os.listdir(qbase)) == [B]
    rec = _record(ws)
    assert rec["pruned_at"] and rec["selectors"]["plan_ids"] == [A]
    (removed,) = rec["removed"]
    assert removed["quarantine_run"] == A
    assert removed["files"] == [{"path": "0-sources/dup.jpg", "bytes": 12}]
    assert removed["manifest"] == [{"original_path": "0-sources/dup.jpg",
                                    "retained_counterpart": "5-photos-by-date/k.jpg"}]
    after = sorted(os.listdir(os.path.join(ws, ".photos-ingest")))
    assert sorted(set(after) - set(before)) == ["photos-16-prune-record.json"]


@pytest.mark.spec("RUL-prune_record_kept", "BLD-prune_record", test="TST-prune_record-a_later_prune_keeps_the_earlier_record")
def test_a_later_prune_keeps_the_earlier_record(tmp_path):
    ws, qbase = _ws(tmp_path)
    prep.prune_quarantine(ws, plan_ids=[A], do_delete=True)
    first = open(utils.prune_record_path(ws)).read()
    prep.prune_quarantine(ws, plan_ids=[B], do_delete=True)
    kept = os.path.join(ws, ".photos-ingest", "photos-16-prune-record-001.json")
    assert open(kept).read() == first
    assert [r["quarantine_run"] for r in _record(ws)["removed"]] == [B]


@pytest.mark.spec("RUL-prune_recorded", "BLD-prune_record", "RUL-prune_lists_unless_told", test="TST-prune_record-a_listing_prune_records_nothing")
def test_a_listing_prune_records_nothing(tmp_path):
    ws, qbase = _ws(tmp_path)
    prep.prune_quarantine(ws)                                         # lists only
    prep.prune_quarantine(ws, plan_ids=["20990101T000000Z-none"], do_delete=True)   # deletes nothing
    assert not os.path.exists(utils.prune_record_path(ws))
    assert sorted(os.listdir(qbase)) == [A, B]
