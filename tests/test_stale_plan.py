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

"""Phase 4a — stale-plan rejection at execute.

A plan must be rejected before any mutation if the workspace config changed since
planning (prep Section 21) or the plan schema/version differs (Section 14.3.2).

Mocked hashing/metadata, fast. photos_1_prep / photos_utils come from conftest.py.
"""
import json
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


def _build_plan(ws):
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


@pytest.mark.spec("config-wholehash-coarse-replan-1")
def test_config_change_rejects_plan_at_execute(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)

    # Hand-edit the workspace config after planning.
    cfg = utils.config_path(str(ws))
    data = json.load(open(cfg))
    data["filename_timestamp_format"] = "%Y%m%d"
    with open(cfg, "w") as f:
        json.dump(data, f)

    with pytest.raises(ValueError, match="config changed"):
        prep.PlanExecutor(str(ws)).execute(plan)
    # No mutation: the source is still in 0-sources.
    assert os.path.exists(ws / "0-sources" / "a.jpg")


def test_plan_version_mismatch_rejected(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    plan.plan_version = 99
    with pytest.raises(ValueError, match="plan_version"):
        prep.PlanExecutor(str(ws)).execute(plan)


def test_unchanged_config_executes(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)  # same config it was built from -> passes
    assert list(os.scandir(ws / "5-photos-by-date")), "the file should have been organized"
